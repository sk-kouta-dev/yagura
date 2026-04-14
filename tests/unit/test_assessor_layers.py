"""DangerAssessor Layer 2 / Layer 3 / policy integration tests."""

from __future__ import annotations

import pytest

from tests.conftest import MockLLMProvider, assess_response
from yagura.errors import DangerAssessmentError
from yagura.safety.assessor import DangerAssessor, LLMAssessor
from yagura.safety.policy import PolicyCheckResult, SecurityPolicyProvider
from yagura.safety.rules import DangerLevel, DangerRules
from yagura.tools.tool import Tool


def _unknown_tool(name: str = "custom_thing") -> Tool:
    """A tool whose name doesn't match any prefix rule, forcing Layer 2."""
    return Tool(
        name=name,
        description=f"{name} tool",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: None,
    )


# ---------------------------------------------------------------------------
# Layer 2 — LLM assessor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_layer2_assessor_uses_executor_llm_when_rules_miss() -> None:
    executor = MockLLMProvider(responses=[assess_response("MODIFY", confidence=0.9, reason="creates draft")])
    assessor = DangerAssessor(rules=DangerRules.default(), executor_llm=executor)
    assessment = await assessor.assess(_unknown_tool("wibble_create_thing"), {"arg": "value"})

    assert assessment.layer == 2
    assert assessment.level is DangerLevel.MODIFY
    assert assessment.confidence == 0.9
    assert "creates draft" in assessment.reason
    assert len(executor.calls) == 1


@pytest.mark.asyncio
async def test_layer2_classifies_shell_command_as_read() -> None:
    """Simulates DangerAssessor inspecting a shell command as READ (ls) vs MODIFY."""
    executor = MockLLMProvider(responses=[assess_response("READ", confidence=0.95, reason="listing files")])
    assessor = DangerAssessor(rules=DangerRules.default(), executor_llm=executor)
    assessment = await assessor.assess(_unknown_tool("shell_execute"), {"command": "ls -la /tmp"})

    assert assessment.layer == 2
    assert assessment.level is DangerLevel.READ


@pytest.mark.asyncio
async def test_layer2_classifies_shell_command_as_destructive() -> None:
    executor = MockLLMProvider(
        responses=[assess_response("DESTRUCTIVE", confidence=0.98, reason="rm -rf deletes files irrecoverably")]
    )
    assessor = DangerAssessor(rules=DangerRules.default(), executor_llm=executor)
    assessment = await assessor.assess(_unknown_tool("shell_execute"), {"command": "rm -rf /tmp/data"})

    assert assessment.layer == 2
    assert assessment.level is DangerLevel.DESTRUCTIVE


@pytest.mark.asyncio
async def test_layer2_raises_when_no_executor_llm_configured() -> None:
    assessor = DangerAssessor(rules=DangerRules.default(), executor_llm=None)
    with pytest.raises(DangerAssessmentError):
        await assessor.assess(_unknown_tool("wibble_thing"), {})


# ---------------------------------------------------------------------------
# Layer 3 — fallback LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_layer3_activates_when_layer2_confidence_below_threshold() -> None:
    executor = MockLLMProvider(responses=[assess_response("MODIFY", confidence=0.5, reason="unsure")])
    fallback = MockLLMProvider(responses=[assess_response("DESTRUCTIVE", confidence=0.95, reason="definitive")])
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        executor_llm=executor,
        fallback_llm=fallback,
        confidence_threshold=0.8,
    )
    assessment = await assessor.assess(_unknown_tool("ambiguous_op"), {"x": 1})

    assert assessment.layer == 3
    assert assessment.level is DangerLevel.DESTRUCTIVE
    assert assessment.confidence == 0.95


@pytest.mark.asyncio
async def test_layer3_skipped_when_layer2_confidence_sufficient() -> None:
    executor = MockLLMProvider(responses=[assess_response("READ", confidence=0.9)])
    fallback = MockLLMProvider()
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        executor_llm=executor,
        fallback_llm=fallback,
        confidence_threshold=0.8,
    )
    assessment = await assessor.assess(_unknown_tool("some_tool"), {})

    assert assessment.layer == 2
    # Fallback LLM never called.
    assert len(fallback.calls) == 0


@pytest.mark.asyncio
async def test_layer3_not_available_accepts_low_confidence_layer2() -> None:
    """When fallback_llm is None, spec says Layer 2 result is used regardless of confidence."""
    executor = MockLLMProvider(responses=[assess_response("MODIFY", confidence=0.3, reason="weak")])
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        executor_llm=executor,
        fallback_llm=None,
        confidence_threshold=0.8,
    )
    assessment = await assessor.assess(_unknown_tool("some_tool"), {})

    assert assessment.layer == 2
    assert assessment.level is DangerLevel.MODIFY
    assert assessment.metadata.get("fallback_skipped") is True


# ---------------------------------------------------------------------------
# Layer 3 low-confidence escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_layer3_low_confidence_escalates_to_destructive() -> None:
    """If Layer 3 still returns below-threshold confidence, escalate to DESTRUCTIVE."""
    executor = MockLLMProvider(responses=[assess_response("MODIFY", confidence=0.4)])
    # Fallback LLM returns READ with LOW confidence (< 0.8).
    fallback = MockLLMProvider(responses=[assess_response("READ", confidence=0.5, reason="still unsure")])
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        executor_llm=executor,
        fallback_llm=fallback,
        confidence_threshold=0.8,
    )
    assessment = await assessor.assess(_unknown_tool("mystery_tool"), {"x": 1})

    assert assessment.layer == 3
    # Escalated from READ → DESTRUCTIVE.
    assert assessment.level is DangerLevel.DESTRUCTIVE
    assert assessment.metadata.get("escalated_due_to_low_confidence") is True
    assert assessment.metadata.get("original_level") == "READ"
    # Reason explains the escalation.
    assert "escalated" in assessment.reason
    assert "still unsure" in assessment.reason  # original reason preserved
    assert "0.50" in assessment.reason  # confidence rendered
    assert "0.80" in assessment.reason  # threshold rendered


@pytest.mark.asyncio
async def test_layer3_low_confidence_forces_confirmation_regardless_of_threshold() -> None:
    """Even with auto_execute_threshold=DESTRUCTIVE (would normally skip confirm),
    a low-confidence Layer 3 escalation still forces confirmation."""
    executor = MockLLMProvider(responses=[assess_response("MODIFY", confidence=0.4)])
    fallback = MockLLMProvider(responses=[assess_response("READ", confidence=0.5)])
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        executor_llm=executor,
        fallback_llm=fallback,
        confidence_threshold=0.8,
        # This threshold would normally auto-execute DESTRUCTIVE plans.
        auto_execute_threshold=DangerLevel.INSTALL,
    )
    assessment = await assessor.assess(_unknown_tool("mystery_tool"), {})

    assert assessment.level is DangerLevel.DESTRUCTIVE
    assert assessment.requires_confirmation is True


@pytest.mark.asyncio
async def test_layer3_high_confidence_uses_reported_level_unchanged() -> None:
    """If Layer 3 IS confident, no escalation happens — use its level as-is."""
    executor = MockLLMProvider(responses=[assess_response("MODIFY", confidence=0.4)])
    fallback = MockLLMProvider(responses=[assess_response("READ", confidence=0.95, reason="confident read")])
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        executor_llm=executor,
        fallback_llm=fallback,
        confidence_threshold=0.8,
    )
    assessment = await assessor.assess(_unknown_tool("mystery_tool"), {})

    assert assessment.layer == 3
    assert assessment.level is DangerLevel.READ  # unchanged; no escalation
    assert "escalated_due_to_low_confidence" not in assessment.metadata
    assert assessment.reason == "confident read"


@pytest.mark.asyncio
async def test_layer3_escalation_does_not_downgrade_destructive() -> None:
    """If Layer 3 already returns DESTRUCTIVE/INSTALL with low confidence,
    the escalated level is still max(level, DESTRUCTIVE) — never downgraded."""
    executor = MockLLMProvider(responses=[assess_response("MODIFY", confidence=0.4)])
    # Layer 3 says INSTALL with low confidence.
    fallback = MockLLMProvider(responses=[assess_response("INSTALL", confidence=0.3, reason="maybe install")])
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        executor_llm=executor,
        fallback_llm=fallback,
        confidence_threshold=0.8,
    )
    assessment = await assessor.assess(_unknown_tool("mystery_tool"), {})

    # INSTALL is already higher than DESTRUCTIVE, so escalation keeps INSTALL.
    assert assessment.level is DangerLevel.INSTALL
    # But the escalation flag is still set so requires_confirmation is forced.
    assert assessment.metadata.get("escalated_due_to_low_confidence") is True
    assert assessment.metadata.get("original_level") == "INSTALL"
    assert assessment.requires_confirmation is True


# ---------------------------------------------------------------------------
# LLMAssessor JSON parsing edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_assessor_tolerates_code_fenced_json() -> None:
    executor = MockLLMProvider()

    # Pre-populate a single response with code-fenced JSON.
    from yagura.llm.provider import LLMResponse, TokenUsage

    executor.responses = [
        LLMResponse(
            content='```json\n{"level": "READ", "confidence": 1.0, "reason": "no side effects"}\n```',
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )
    ]
    assessor = LLMAssessor(executor)
    assessment = await assessor.assess(_unknown_tool("tool"), {}, layer=2)
    assert assessment.level is DangerLevel.READ


@pytest.mark.asyncio
async def test_llm_assessor_raises_on_malformed_response() -> None:
    executor = MockLLMProvider()
    from yagura.llm.provider import LLMResponse

    executor.responses = [LLMResponse(content="not json at all")]
    assessor = LLMAssessor(executor)
    with pytest.raises(DangerAssessmentError):
        await assessor.assess(_unknown_tool("tool"), {}, layer=2)


# ---------------------------------------------------------------------------
# SecurityPolicyProvider integration
# ---------------------------------------------------------------------------


class _AllowProvider(SecurityPolicyProvider):
    async def check(self, tool_name: str, params: dict, danger_level: DangerLevel) -> PolicyCheckResult:
        return PolicyCheckResult(allowed=True, reason="ok")


class _DenyProvider(SecurityPolicyProvider):
    async def check(self, tool_name: str, params: dict, danger_level: DangerLevel) -> PolicyCheckResult:
        return PolicyCheckResult(allowed=False, reason="forbidden by policy")


class _AdminRequiredProvider(SecurityPolicyProvider):
    async def check(self, tool_name: str, params: dict, danger_level: DangerLevel) -> PolicyCheckResult:
        return PolicyCheckResult(allowed=True, reason="ok", requires_admin_approval=True)


@pytest.mark.asyncio
async def test_policy_check_called_for_destructive() -> None:
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        policy_provider=_AllowProvider(),
    )
    tool = Tool(
        name="delete_user",
        description="delete",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: None,
    )
    assessment = await assessor.assess(tool, {})
    assert assessment.policy_check is not None
    assert assessment.policy_check.allowed is True


@pytest.mark.asyncio
async def test_policy_check_skipped_for_read() -> None:
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        policy_provider=_AllowProvider(),
    )
    tool = Tool(
        name="list_users",
        description="list",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: None,
    )
    assessment = await assessor.assess(tool, {})
    # READ should not consult the policy provider.
    assert assessment.policy_check is None


@pytest.mark.asyncio
async def test_policy_denial_forces_confirmation() -> None:
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        policy_provider=_DenyProvider(),
        auto_execute_threshold=DangerLevel.DESTRUCTIVE,  # Would normally skip confirmation.
    )
    tool = Tool(
        name="delete_user",
        description="delete",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: None,
    )
    assessment = await assessor.assess(tool, {})
    # Even with a high threshold, a policy denial must halt.
    assert assessment.requires_confirmation is True
    assert assessment.policy_check.allowed is False


@pytest.mark.asyncio
async def test_admin_approval_forces_confirmation() -> None:
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        policy_provider=_AdminRequiredProvider(),
        auto_execute_threshold=DangerLevel.INSTALL,  # Would normally skip confirmation.
    )
    tool = Tool(
        name="install_package",
        description="install",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: None,
    )
    assessment = await assessor.assess(tool, {})
    assert assessment.requires_confirmation is True
    assert assessment.policy_check.requires_admin_approval is True
