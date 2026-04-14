"""DangerAssessor — the 3-layer safety assessment engine.

Layer 1: Rule-based (DangerRules pattern matching). Zero cost, instant.
         Handles ~90% of assessments.
Layer 2: LLM-based (executor LLM). Analyzes parameters when the tool
         name alone is insufficient (e.g. shell_execute, api_call).
Layer 3: Fallback LLM (more capable). Activated only when Layer 2
         confidence is below threshold. Expected <1% of assessments.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from yagura.errors import DangerAssessmentError
from yagura.safety.policy import PolicyCheckResult, SecurityPolicyProvider
from yagura.safety.rules import DangerLevel, DangerRules
from yagura.tools.tool import Tool

if TYPE_CHECKING:
    from yagura.llm.provider import LLMProvider


@dataclass
class DangerAssessment:
    """The result of a DangerAssessor evaluation."""

    level: DangerLevel
    layer: int  # 1, 2, or 3
    confidence: float  # 1.0 for rule-based; variable for LLM
    reason: str
    policy_check: PolicyCheckResult | None = None
    requires_confirmation: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMAssessor:
    """Layer 2/3 helper: ask an LLM to classify an operation."""

    _PROMPT = (
        "You are a safety classifier for an AI agent. Given a tool invocation "
        "(tool name, description, and parameters), return a JSON object with "
        "fields:\n"
        "  - level: one of READ, MODIFY, DESTRUCTIVE, INSTALL\n"
        "  - confidence: number between 0 and 1\n"
        "  - reason: short justification\n"
        "\n"
        "Definitions:\n"
        "  READ: no side effects, no state change.\n"
        "  MODIFY: reversible side effects (create folder, copy file, draft).\n"
        "  DESTRUCTIVE: irreversible or high-impact (delete, send email, push).\n"
        "  INSTALL: system-level changes (install package, change system config).\n"
        "\n"
        "Respond with ONLY the JSON object, no prose."
    )

    def __init__(self, llm: LLMProvider, confidence_threshold: float = 0.8) -> None:
        self.llm = llm
        self.confidence_threshold = confidence_threshold

    async def assess(self, tool: Tool, params: dict[str, Any], layer: int) -> DangerAssessment:
        from yagura.llm.provider import Message

        user_content = (
            f"tool_name: {tool.name}\n"
            f"description: {tool.description}\n"
            f"parameters: {json.dumps(params, ensure_ascii=False, default=str)}"
        )
        response = await self.llm.generate(
            messages=[Message(role="user", content=user_content)],
            system=self._PROMPT,
        )
        level, confidence, reason = self._parse(response.content)
        return DangerAssessment(
            level=level,
            layer=layer,
            confidence=confidence,
            reason=reason,
        )

    @staticmethod
    def _parse(content: str) -> tuple[DangerLevel, float, str]:
        text = content.strip()
        # Tolerate models that wrap JSON in code fences.
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json\n"):
                text = text[5:]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DangerAssessmentError(f"LLM returned non-JSON assessment: {content!r}") from exc
        try:
            level = DangerLevel[data["level"].upper()]
            confidence = float(data.get("confidence", 0.0))
            reason = str(data.get("reason", ""))
        except (KeyError, AttributeError, ValueError) as exc:
            raise DangerAssessmentError(f"LLM assessment missing required fields: {data!r}") from exc
        return level, confidence, reason


class DangerAssessor:
    """Runs the 3-layer assessment for a tool invocation.

    Workflow:
      1. If tool.danger_level is set explicitly, use it (layer 1).
      2. Else try DangerRules.classify(tool.name) → rule-based (layer 1).
      3. If rules don't match and executor_llm is available → layer 2.
      4. If layer 2 confidence < threshold and fallback_llm is available → layer 3.
      5. SecurityPolicyProvider.check is applied for DESTRUCTIVE/INSTALL.
      6. requires_confirmation is derived from level + auto_execute_threshold.
    """

    def __init__(
        self,
        rules: DangerRules | None = None,
        executor_llm: LLMProvider | None = None,
        fallback_llm: LLMProvider | None = None,
        policy_provider: SecurityPolicyProvider | None = None,
        auto_execute_threshold: DangerLevel | None = DangerLevel.READ,
        confidence_threshold: float = 0.8,
    ) -> None:
        self.rules = rules or DangerRules.default()
        self.executor_llm = executor_llm
        self.fallback_llm = fallback_llm
        self.policy_provider = policy_provider
        self.auto_execute_threshold = auto_execute_threshold
        self.confidence_threshold = confidence_threshold

    async def assess(self, tool: Tool, params: dict[str, Any]) -> DangerAssessment:
        """Return a full DangerAssessment for the given tool invocation."""
        assessment = await self._classify(tool, params)
        if assessment.level in (DangerLevel.DESTRUCTIVE, DangerLevel.INSTALL) and self.policy_provider:
            assessment.policy_check = await self.policy_provider.check(tool.name, params, assessment.level)
        assessment.requires_confirmation = self._requires_confirmation(assessment)
        return assessment

    async def assess_plan(
        self,
        steps: list[tuple[Tool, dict[str, Any]]],
    ) -> list[DangerAssessment]:
        """Assess every step of a plan (convenience for PlanExecutor)."""
        return [await self.assess(tool, params) for tool, params in steps]

    # --- Internal ---------------------------------------------------------

    async def _classify(self, tool: Tool, params: dict[str, Any]) -> DangerAssessment:
        # Explicit tool-level override takes precedence over everything.
        if tool.danger_level is not None:
            return DangerAssessment(
                level=tool.danger_level,
                layer=1,
                confidence=1.0,
                reason=f"Explicit Tool.danger_level={tool.danger_level.name}",
            )

        rule_level = self.rules.classify(tool.name)
        if rule_level is not None:
            return DangerAssessment(
                level=rule_level,
                layer=1,
                confidence=1.0,
                reason=f"DangerRules matched tool name '{tool.name}'",
            )

        # Layer 2 — executor LLM.
        if self.executor_llm is None:
            raise DangerAssessmentError(
                f"Cannot assess tool '{tool.name}': no rule match and no executor_llm configured."
            )
        layer2 = LLMAssessor(self.executor_llm, self.confidence_threshold)
        assessment = await layer2.assess(tool, params, layer=2)

        if assessment.confidence >= self.confidence_threshold:
            return assessment

        # Layer 3 — fallback LLM.
        if self.fallback_llm is None:
            # Spec: Layer 2 result is used regardless of confidence when no fallback.
            assessment.metadata["fallback_skipped"] = True
            return assessment
        layer3 = LLMAssessor(self.fallback_llm, self.confidence_threshold)
        return await layer3.assess(tool, params, layer=3)

    def _requires_confirmation(self, assessment: DangerAssessment) -> bool:
        # INSTALL always requires admin approval if policy says so.
        if assessment.policy_check and assessment.policy_check.requires_admin_approval:
            return True
        # Policy denial — confirmation is irrelevant, the plan will halt.
        if assessment.policy_check and not assessment.policy_check.allowed:
            return True
        # auto_execute_threshold=None → always confirm.
        if self.auto_execute_threshold is None:
            return True
        return assessment.level > self.auto_execute_threshold
