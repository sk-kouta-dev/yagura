"""Plan system: Plan, PlanStep, PlanState, StepContext, and PlanExecutor.

PlanExecutor is the heart of the framework's execution loop:
  1. Walk through plan steps in order.
  2. Resolve $step_N references in parameters (Phase A: direct; Phase B: LLM).
  3. Run DangerAssessor on the step (if not already assessed).
  4. Ask ConfirmationHandler if required.
  5. Dispatch through ToolExecutor.
  6. On failure: halt, mark remaining SKIPPED, preserve results.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from yagura.errors import (
    InvalidPlanStateTransitionError,
    StepReferenceError,
    ToolExecutionError,
    ToolNotFoundError,
)
from yagura.llm.provider import LLMProvider, Message
from yagura.safety.reliability import ReliabilityLevel
from yagura.safety.rules import DangerLevel
from yagura.tools.executor import ToolExecutor
from yagura.tools.registry import ToolRegistry
from yagura.tools.tool import Tool, ToolResult

if TYPE_CHECKING:
    from yagura.confirmation.handler import ConfirmationHandler
    from yagura.logging.logger import AuditLogger
    from yagura.safety.assessor import DangerAssessor


class PlanState(Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REPLANNED = "replanned"


# Valid Plan state transitions.
_VALID_TRANSITIONS: dict[PlanState, set[PlanState]] = {
    PlanState.DRAFT: {PlanState.CONFIRMED, PlanState.RUNNING, PlanState.CANCELLED},
    PlanState.CONFIRMED: {PlanState.RUNNING, PlanState.CANCELLED},
    PlanState.RUNNING: {
        PlanState.COMPLETED,
        PlanState.FAILED,
        PlanState.PAUSED,
        PlanState.CANCELLED,
    },
    PlanState.PAUSED: {PlanState.RUNNING, PlanState.CANCELLED},
    PlanState.FAILED: {PlanState.REPLANNED, PlanState.CANCELLED},
    PlanState.REPLANNED: {PlanState.CONFIRMED, PlanState.CANCELLED},
    PlanState.COMPLETED: set(),
    PlanState.CANCELLED: set(),
}


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    step_number: int
    tool_name: str
    parameters: dict[str, Any]
    description: str
    danger_level: DangerLevel | None = None
    status: StepStatus = StepStatus.PENDING
    result: ToolResult | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


@dataclass
class Plan:
    id: str
    steps: list[PlanStep]
    scope: int | None = None  # User-confirmed execution scope. None = all.
    state: PlanState = PlanState.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    confirmed_at: datetime | None = None

    def transition_to(self, new_state: PlanState) -> None:
        if new_state not in _VALID_TRANSITIONS.get(self.state, set()):
            raise InvalidPlanStateTransitionError(
                f"Invalid Plan state transition: {self.state.value} → {new_state.value}"
            )
        self.state = new_state
        if new_state is PlanState.CONFIRMED:
            self.confirmed_at = datetime.now(UTC)

    def steps_in_scope(self) -> list[PlanStep]:
        if self.scope is None:
            return list(self.steps)
        return [s for s in self.steps if s.step_number <= self.scope]


@dataclass
class PlanConfirmation:
    """User decision returned by ConfirmationHandler.confirm_plan."""

    approved: bool
    scope: int | None = None
    modifications: list[str] = field(default_factory=list)


@dataclass
class PlanStepSummary:
    step_number: int
    label: str
    details: list[str] = field(default_factory=list)


@dataclass
class PlanSummary:
    steps: list[PlanStepSummary]


@dataclass
class PlanProgress:
    """Snapshot of plan execution progress for persistence/resume."""

    plan_id: str
    current_step: int
    completed_steps: list[int]
    failed_step: int | None = None


@dataclass
class PausedState:
    session_id: str
    plan: Plan
    progress: PlanProgress
    paused_at: datetime
    paused_reason: str
    context: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Step context / reference resolution
# ---------------------------------------------------------------------------


@dataclass
class StepContext:
    """Per-plan context that accumulates completed ToolResults.

    Subsequent steps reference earlier results via `$step_N.path.to.value`.
    """

    results: dict[int, ToolResult] = field(default_factory=dict)

    def get(self, step_number: int) -> ToolResult:
        if step_number not in self.results:
            raise StepReferenceError(f"Step {step_number} has no recorded result")
        return self.results[step_number]

    def record(self, step_number: int, result: ToolResult) -> None:
        self.results[step_number] = result

    def resolve_ref(self, ref: str) -> Any:
        """Resolve a `$step_N.path.to.value` reference against stored results.

        Supports dot-notation and list indexing: `$step_1.data.files[0]`.
        """
        if not ref.startswith("$step_"):
            raise StepReferenceError(f"Not a step reference: {ref!r}")
        match = re.match(r"^\$step_(\d+)(.*)$", ref)
        if not match:
            raise StepReferenceError(f"Malformed step reference: {ref!r}")
        step_num = int(match.group(1))
        path = match.group(2)  # e.g., ".data.files[0]" or "".
        result = self.get(step_num)

        # Start traversal from the ToolResult itself. The spec's example
        # `$step_1.data.files[0]` expects `.data` to step into ToolResult.data.
        current: Any = result
        # Tokenize the path into (attr|index) tokens.
        for token in _tokenize_path(path):
            if isinstance(token, int):
                try:
                    current = current[token]
                except (TypeError, IndexError, KeyError) as exc:
                    raise StepReferenceError(f"Cannot index {current!r} with [{token}] in ref {ref!r}") from exc
            else:  # attribute / key
                if isinstance(current, dict):
                    if token not in current:
                        raise StepReferenceError(f"Key '{token}' not found in ref {ref!r}")
                    current = current[token]
                else:
                    if not hasattr(current, token):
                        raise StepReferenceError(
                            f"Attribute '{token}' not found on {type(current).__name__} in ref {ref!r}"
                        )
                    current = getattr(current, token)
        return current


_PATH_TOKEN_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\-?\d+)\]")


def _tokenize_path(path: str) -> Iterable[str | int]:
    """Tokenize `.a.b[0].c` → ['a', 'b', 0, 'c']."""
    pos = 0
    while pos < len(path):
        m = _PATH_TOKEN_RE.match(path, pos)
        if not m:
            raise StepReferenceError(f"Cannot parse path fragment: {path[pos:]!r}")
        attr, idx = m.group(1), m.group(2)
        yield attr if attr is not None else int(idx)
        pos = m.end()


# ---------------------------------------------------------------------------
# PlanExecutor
# ---------------------------------------------------------------------------


def _contains_step_ref(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("$step_")
    if isinstance(value, dict):
        return any(_contains_step_ref(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_step_ref(v) for v in value)
    return False


class PlanExecutor:
    """Executes a confirmed Plan step-by-step with full safety pipeline."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        danger_assessor: DangerAssessor,
        confirmation_handler: ConfirmationHandler,
        executor_llm: LLMProvider | None = None,
        audit_logger: AuditLogger | None = None,
        session_id: str = "default",
        user_id: str = "default",
        pause_event: asyncio.Event | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.danger_assessor = danger_assessor
        self.confirmation_handler = confirmation_handler
        self.executor_llm = executor_llm
        self.audit_logger = audit_logger
        self.session_id = session_id
        self.user_id = user_id
        # If set between steps, the executor transitions the plan to PAUSED
        # and returns control to the caller. See Agent.pause().
        self.pause_event = pause_event

    async def execute_stream(
        self,
        plan: Plan,
        context: StepContext | None = None,
    ):
        """Same as execute(), but yields streaming events (see yagura.streaming).

        Consumers drive this from an async for loop — each yield is a
        StreamEvent suitable for WebSocket / SSE serialization.
        """
        from yagura.streaming import (
            PlanCompleted,
            PlanFailed,
            PlanPaused,
            StepCompleted,
            StepFailed,
            StepStarted,
        )

        if context is None:
            context = StepContext()
        if plan.state in (PlanState.DRAFT, PlanState.CONFIRMED, PlanState.PAUSED):
            if plan.state is not PlanState.RUNNING:
                plan.transition_to(PlanState.RUNNING)

        try:
            for step in plan.steps_in_scope():
                if step.status is not StepStatus.PENDING:
                    continue
                if self.pause_event is not None and self.pause_event.is_set():
                    plan.transition_to(PlanState.PAUSED)
                    yield PlanPaused(session_id=self.session_id, plan=plan)
                    return
                yield StepStarted(session_id=self.session_id, step=step)
                await self._run_step(plan, step, context)
                if step.status is StepStatus.FAILED:
                    yield StepFailed(
                        session_id=self.session_id,
                        step_number=step.step_number,
                        error=step.error or "unknown error",
                    )
                    self._skip_remaining(plan, after=step.step_number)
                    plan.transition_to(PlanState.FAILED)
                    yield PlanFailed(session_id=self.session_id, plan=plan, reason=step.error or "")
                    return
                yield StepCompleted(
                    session_id=self.session_id,
                    step_number=step.step_number,
                    result=step.result,
                )
            plan.transition_to(PlanState.COMPLETED)
            yield PlanCompleted(session_id=self.session_id, plan=plan)
        finally:
            if self.audit_logger:
                from yagura.logging.logger import PlanLog

                await self.audit_logger.log_plan(
                    PlanLog(
                        session_id=self.session_id,
                        user_id=self.user_id,
                        timestamp=datetime.now(UTC),
                        plan_json=_plan_to_dict(plan),
                        confirmed_scope=plan.scope or len(plan.steps),
                        final_state=plan.state,
                        total_steps=len(plan.steps),
                        completed_steps=sum(1 for s in plan.steps if s.status is StepStatus.COMPLETED),
                    )
                )

    async def execute(self, plan: Plan, context: StepContext | None = None) -> Plan:
        """Execute a CONFIRMED or (auto-execute) DRAFT plan to completion.

        The caller is expected to have transitioned the plan to RUNNING before
        calling. If the plan is DRAFT or CONFIRMED, this method performs the
        transition itself.

        If `pause_event` is set between steps, the plan transitions to PAUSED
        and the executor returns immediately without running further steps.
        Completed step results are preserved on the Plan and in `context`;
        subsequent resume calls pick up from the first PENDING step.
        """
        if context is None:
            context = StepContext()
        if plan.state in (PlanState.DRAFT, PlanState.CONFIRMED, PlanState.PAUSED):
            # From DRAFT or CONFIRMED this is the initial transition.
            # From PAUSED (resume) we go back into RUNNING.
            target = PlanState.RUNNING
            if plan.state is not target:
                plan.transition_to(target)

        try:
            for step in plan.steps_in_scope():
                if step.status is not StepStatus.PENDING:
                    continue
                # Check for pause before each step.
                if self.pause_event is not None and self.pause_event.is_set():
                    plan.transition_to(PlanState.PAUSED)
                    return plan
                await self._run_step(plan, step, context)
                if step.status is StepStatus.FAILED:
                    self._skip_remaining(plan, after=step.step_number)
                    plan.transition_to(PlanState.FAILED)
                    return plan
            plan.transition_to(PlanState.COMPLETED)
            return plan
        finally:
            if self.audit_logger:
                from yagura.logging.logger import PlanLog

                total_usage = None  # Aggregating token usage is provider-specific; left as hook.
                await self.audit_logger.log_plan(
                    PlanLog(
                        session_id=self.session_id,
                        user_id=self.user_id,
                        timestamp=datetime.now(UTC),
                        plan_json=_plan_to_dict(plan),
                        confirmed_scope=plan.scope or len(plan.steps),
                        final_state=plan.state,
                        total_steps=len(plan.steps),
                        completed_steps=sum(1 for s in plan.steps if s.status is StepStatus.COMPLETED),
                        total_tokens=total_usage,
                    )
                )

    # --- Per-step lifecycle ----------------------------------------------

    async def _run_step(
        self,
        plan: Plan,
        step: PlanStep,
        context: StepContext,
    ) -> None:
        from yagura.telemetry import span

        with span(
            "yagura.plan.step",
            session_id=self.session_id,
            plan_id=plan.id,
            step_number=step.step_number,
            tool_name=step.tool_name,
        ):
            await self._run_step_inner(plan, step, context)

    async def _run_step_inner(
        self,
        plan: Plan,
        step: PlanStep,
        context: StepContext,
    ) -> None:
        step.status = StepStatus.RUNNING
        step.started_at = datetime.now(UTC)

        try:
            tool = self.tool_registry.get(step.tool_name)
        except ToolNotFoundError as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)
            step.completed_at = datetime.now(UTC)
            return

        # Resolve $step_N references in parameters.
        try:
            resolved_params = await self._resolve_parameters(step.parameters, context, tool, step)
        except StepReferenceError as exc:
            step.status = StepStatus.FAILED
            step.error = f"Parameter resolution failed: {exc}"
            step.completed_at = datetime.now(UTC)
            return

        # Safety assessment.
        assessment = await self.danger_assessor.assess(tool, resolved_params)
        step.danger_level = assessment.level

        if self.audit_logger:
            from yagura.logging.logger import AssessmentLog

            await self.audit_logger.log_assessment(
                AssessmentLog(
                    session_id=self.session_id,
                    timestamp=datetime.now(UTC),
                    tool_name=tool.name,
                    danger_level=assessment.level,
                    assessment_layer=assessment.layer,
                    confidence=assessment.confidence,
                    reason=assessment.reason,
                    user_approved=None,
                    policy_check_result=assessment.policy_check,
                )
            )

        # Policy denial halts the plan immediately (never prompts user).
        if assessment.policy_check and not assessment.policy_check.allowed:
            step.status = StepStatus.FAILED
            step.error = f"SecurityPolicy denied: {assessment.policy_check.reason}"
            step.completed_at = datetime.now(UTC)
            return

        # User confirmation for dangerous operations.
        if assessment.requires_confirmation:
            approved = await self.confirmation_handler.confirm_danger(step, assessment)
            if self.audit_logger:
                from yagura.logging.logger import AssessmentLog

                await self.audit_logger.log_assessment(
                    AssessmentLog(
                        session_id=self.session_id,
                        timestamp=datetime.now(UTC),
                        tool_name=tool.name,
                        danger_level=assessment.level,
                        assessment_layer=assessment.layer,
                        confidence=assessment.confidence,
                        reason="user_confirmation",
                        user_approved=approved,
                        policy_check_result=assessment.policy_check,
                    )
                )
            if not approved:
                step.status = StepStatus.FAILED
                step.error = "User denied confirmation"
                step.completed_at = datetime.now(UTC)
                return

        # Dynamic Tool: transform parameters via executor LLM before handler.
        if tool.requires_llm and tool.llm_task_template is None:
            resolved_params = await self._transform_params_via_llm(tool, resolved_params, context)

        # Execute.
        start = datetime.now(UTC)
        try:
            if tool.llm_task_template is not None:
                # LLM-as-tool: call the executor LLM directly, bypass handler.
                result = await self._run_llm_task_tool(tool, resolved_params)
            else:
                result = await self.tool_executor.execute(tool, resolved_params)
        except ToolExecutionError as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)
            step.completed_at = datetime.now(UTC)
            if self.audit_logger:
                from yagura.logging.logger import OperationLog

                await self.audit_logger.log_operation(
                    OperationLog(
                        session_id=self.session_id,
                        user_id=self.user_id,
                        timestamp=start,
                        tool_name=tool.name,
                        parameters=resolved_params,
                        result_status="failure",
                        duration_ms=_ms_since(start),
                    )
                )
            return

        step.result = result
        step.status = StepStatus.COMPLETED if result.success else StepStatus.FAILED
        step.completed_at = datetime.now(UTC)
        step.error = result.error if not result.success else None
        context.record(step.step_number, result)

        if self.audit_logger:
            from yagura.logging.logger import OperationLog

            await self.audit_logger.log_operation(
                OperationLog(
                    session_id=self.session_id,
                    user_id=self.user_id,
                    timestamp=start,
                    tool_name=tool.name,
                    parameters=resolved_params,
                    result_status="success" if result.success else "failure",
                    duration_ms=_ms_since(start),
                )
            )

        # REFERENCE-level reliability triggers a user confirmation step.
        effective_reliability = result.reliability or tool.default_reliability
        if step.status is StepStatus.COMPLETED and effective_reliability is ReliabilityLevel.REFERENCE:
            ok = await self.confirmation_handler.confirm_reference_result(step, result)
            if not ok:
                # User rejected the REFERENCE data; halt the plan.
                step.status = StepStatus.FAILED
                step.error = "User rejected REFERENCE-reliability result"

    def _skip_remaining(self, plan: Plan, *, after: int) -> None:
        for step in plan.steps:
            if step.step_number > after and step.status is StepStatus.PENDING:
                step.status = StepStatus.SKIPPED

    # --- Parameter resolution --------------------------------------------

    async def _resolve_parameters(
        self,
        params: dict[str, Any],
        context: StepContext,
        tool: Tool,
        step: PlanStep,
    ) -> dict[str, Any]:
        """Two-phase resolution of $step_N references in parameters."""
        if not _contains_step_ref(params):
            return params

        # Phase A: direct resolution.
        try:
            return _resolve_value(params, context)
        except StepReferenceError:
            # Phase B: LLM resolution.
            if self.executor_llm is None:
                raise
            return await self._resolve_via_llm(params, context, tool, step)

    async def _resolve_via_llm(
        self,
        params: dict[str, Any],
        context: StepContext,
        tool: Tool,
        step: PlanStep,
    ) -> dict[str, Any]:
        """Phase B: ask the executor LLM to produce concrete parameters.

        Gives the LLM the tool schema, the step description, the parameter
        template (with references), and the prior step results.
        """
        import json

        previous_results = {f"step_{k}": _summarize_result(v) for k, v in context.results.items()}
        system = (
            "You are a parameter resolver for an AI agent. Given prior step "
            "results and a parameter template containing $step_N references "
            "that could not be resolved directly, produce concrete parameter "
            "values that match the tool's JSON schema.\n"
            "\n"
            "Respond with ONLY a JSON object matching the tool's input_schema."
        )
        user = json.dumps(
            {
                "tool_name": tool.name,
                "tool_description": tool.description,
                "tool_input_schema": tool.parameters,
                "step_description": step.description,
                "parameter_template": params,
                "previous_results": previous_results,
            },
            ensure_ascii=False,
            default=str,
        )
        response = await self.executor_llm.generate(  # type: ignore[union-attr]
            messages=[Message(role="user", content=user)],
            system=system,
        )
        text = response.content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json\n"):
                text = text[5:]
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise StepReferenceError(
                f"Executor LLM failed to produce valid JSON parameters: {response.content!r}"
            ) from exc

    async def _run_llm_task_tool(
        self,
        tool: Tool,
        params: dict[str, Any],
    ) -> ToolResult:
        """Execute an LLM-as-tool: render the task template, call the LLM, wrap the output.

        The template supports Python format-string interpolation with the
        resolved parameters. Missing placeholders degrade gracefully: an
        unfilled `{foo}` leaves a literal warning in the rendered prompt
        rather than crashing.
        """
        if self.executor_llm is None:
            return ToolResult(
                success=False,
                error=f"Tool '{tool.name}' is an LLM-as-tool but no executor_llm is configured.",
            )
        try:
            prompt = tool.llm_task_template.format(**params)  # type: ignore[union-attr]
        except KeyError as exc:
            return ToolResult(
                success=False,
                error=f"Tool '{tool.name}' template references unknown parameter {exc}",
            )
        except (IndexError, ValueError) as exc:
            return ToolResult(
                success=False,
                error=f"Tool '{tool.name}' template render failed: {exc}",
            )

        response = await self.executor_llm.generate(
            messages=[Message(role="user", content=prompt)],
        )
        output_text = (response.content or "").strip()
        return ToolResult(
            success=True,
            data={tool.llm_output_key: output_text, "prompt": prompt},
            reliability=tool.default_reliability,
        )

    async def _transform_params_via_llm(
        self,
        tool: Tool,
        params: dict[str, Any],
        context: StepContext,
    ) -> dict[str, Any]:
        """For Dynamic Tools: let the executor LLM refine parameters.

        Example: shell_execute receives a natural-language task in params
        and expects the LLM to produce a concrete shell command.
        """
        if self.executor_llm is None:
            return params
        import json

        system = (
            "You are the execution assistant for an AI agent's Dynamic Tool. "
            "Given the tool schema and the current parameter values (which "
            "may be natural-language), transform them into concrete, schema- "
            "compliant parameters. Respond with ONLY a JSON object."
        )
        user = json.dumps(
            {
                "tool_name": tool.name,
                "tool_description": tool.description,
                "tool_input_schema": tool.parameters,
                "current_parameters": params,
                "previous_results": {f"step_{k}": _summarize_result(v) for k, v in context.results.items()},
            },
            ensure_ascii=False,
            default=str,
        )
        response = await self.executor_llm.generate(
            messages=[Message(role="user", content=user)],
            system=system,
        )
        text = response.content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json\n"):
                text = text[5:]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # If the LLM declines to transform, fall back to the original params.
            return params


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_value(value: Any, context: StepContext) -> Any:
    if isinstance(value, str):
        if value.startswith("$step_"):
            return context.resolve_ref(value)
        return value
    if isinstance(value, dict):
        return {k: _resolve_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(v, context) for v in value]
    return value


def _summarize_result(result: ToolResult) -> dict[str, Any]:
    """Trim a ToolResult for inclusion in an LLM prompt."""
    data = result.data
    # Very large data bodies are truncated in string form.
    data_preview: Any
    try:
        import json

        text = json.dumps(data, ensure_ascii=False, default=str)
    except TypeError:
        text = repr(data)
    if len(text) > 4000:
        data_preview = text[:4000] + f"... [truncated {len(text) - 4000} chars]"
    else:
        data_preview = data
    return {
        "success": result.success,
        "data": data_preview,
        "reliability": result.reliability.value if result.reliability else None,
        "error": result.error,
    }


def _plan_to_dict(plan: Plan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "state": plan.state.value,
        "scope": plan.scope,
        "created_at": plan.created_at.isoformat(),
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        "steps": [
            {
                "step_number": s.step_number,
                "tool_name": s.tool_name,
                "parameters": s.parameters,
                "description": s.description,
                "status": s.status.value,
                "danger_level": s.danger_level.name if s.danger_level else None,
                "error": s.error,
            }
            for s in plan.steps
        ],
    }


def _ms_since(start: datetime) -> int:
    return int((datetime.now(UTC) - start).total_seconds() * 1000)


# ---------------------------------------------------------------------------
# Planner wrapper
# ---------------------------------------------------------------------------


class Planner:
    """Thin wrapper around an LLMProvider that generates Plans.

    Kept as a separate class so it can be extended (e.g., with caching,
    prompt customization, cost controls) without touching Agent.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def generate(
        self,
        user_input: str,
        tool_schemas: list[dict[str, Any]],
        system: str | None = None,
    ) -> Plan:
        return await self.llm.generate_plan(user_input, tool_schemas, system=system)


# ---------------------------------------------------------------------------
# Plan summary / display
# ---------------------------------------------------------------------------


_READ_PREFIXES = ("search_", "read_", "list_", "get_", "grep_", "find_")


def make_plan_summary(plan: Plan, registry: ToolRegistry) -> PlanSummary:
    """Produce a display-safe PlanSummary (hides internal tool names)."""
    summaries: list[PlanStepSummary] = []
    for step in plan.steps:
        if step.tool_name.startswith(_READ_PREFIXES):
            label = "Investigation"
        elif step.tool_name.startswith(("delete_", "remove_")):
            label = "Deletion"
        elif step.tool_name.startswith(("send_", "notify_")):
            label = "Notification"
        elif step.tool_name.startswith(("create_", "write_", "copy_", "rename_")):
            label = "File Operation"
        elif step.tool_name.startswith(("install_", "package_")):
            label = "Installation"
        else:
            # Fall back to the tool's human description.
            try:
                label = registry.get(step.tool_name).description
            except ToolNotFoundError:
                label = step.description
        summaries.append(
            PlanStepSummary(
                step_number=step.step_number,
                label=label,
                details=[step.description] if step.description else [],
            )
        )
    return PlanSummary(steps=summaries)


# Exported symbols used by the package __init__.
__all__ = [
    "PausedState",
    "Plan",
    "PlanConfirmation",
    "PlanExecutor",
    "PlanProgress",
    "PlanState",
    "PlanStep",
    "PlanStepSummary",
    "PlanSummary",
    "Planner",
    "StepContext",
    "StepStatus",
    "make_plan_summary",
]


# Keep `asyncio` imported for type checkers that run this module bare.
_ = asyncio
