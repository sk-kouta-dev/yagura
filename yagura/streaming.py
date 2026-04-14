"""Event types for Agent.run_stream() and PlanExecutor.execute_stream().

Step-level streaming for WebSocket / SSE / CLI progressive UX. Each event
is a typed dataclass; producers yield them, consumers dispatch by type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from yagura.plan import Plan, PlanStep
    from yagura.safety.assessor import DangerAssessment
    from yagura.tools.tool import ToolResult


@dataclass(kw_only=True)
class StreamEvent:
    """Base for all streaming events — includes a coarse `type` tag and timestamp."""

    type: str
    session_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class PlanGenerated(StreamEvent):
    type: Literal["plan_generated"] = "plan_generated"
    plan: Plan | None = None


@dataclass(kw_only=True)
class PlanNeedsConfirmation(StreamEvent):
    type: Literal["plan_needs_confirmation"] = "plan_needs_confirmation"
    plan: Plan | None = None
    reason: str = ""


@dataclass(kw_only=True)
class StepStarted(StreamEvent):
    type: Literal["step_started"] = "step_started"
    step: PlanStep | None = None


@dataclass(kw_only=True)
class StepAssessed(StreamEvent):
    type: Literal["step_assessed"] = "step_assessed"
    step_number: int = 0
    assessment: DangerAssessment | None = None


@dataclass(kw_only=True)
class StepCompleted(StreamEvent):
    type: Literal["step_completed"] = "step_completed"
    step_number: int = 0
    result: ToolResult | None = None


@dataclass(kw_only=True)
class StepFailed(StreamEvent):
    type: Literal["step_failed"] = "step_failed"
    step_number: int = 0
    error: str = ""


@dataclass(kw_only=True)
class PlanCompleted(StreamEvent):
    type: Literal["plan_completed"] = "plan_completed"
    plan: Plan | None = None


@dataclass(kw_only=True)
class PlanFailed(StreamEvent):
    type: Literal["plan_failed"] = "plan_failed"
    plan: Plan | None = None
    reason: str = ""


@dataclass(kw_only=True)
class PlanPaused(StreamEvent):
    type: Literal["plan_paused"] = "plan_paused"
    plan: Plan | None = None


@dataclass(kw_only=True)
class PlanCancelled(StreamEvent):
    type: Literal["plan_cancelled"] = "plan_cancelled"
    plan: Plan | None = None


# ---------------------------------------------------------------------------
# Token-level LLM streaming
# ---------------------------------------------------------------------------


@dataclass
class LLMStreamChunk:
    """One delta from an LLM stream. Content is plain text; ToolCall deltas
    are surfaced via the non-text fields for provider-specific consumers."""

    content: str = ""
    tool_call_delta: dict[str, Any] | None = None
    finished: bool = False
    raw: Any = None


def event_to_dict(event: StreamEvent) -> dict[str, Any]:
    """Serialize a StreamEvent to a JSON-safe dict (for WebSocket / SSE)."""
    from dataclasses import asdict
    from enum import Enum

    def _default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        return str(obj)

    import json

    # Round-trip through JSON to strip non-serializable fields (Plan etc.).
    return json.loads(json.dumps(asdict(event), default=_default))
