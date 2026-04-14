"""The `create_plan` tool schema and response parser.

Extracted into its own module so LLMProvider.generate_plan can use it
without creating an import cycle with yagura.plan.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from yagura.errors import PlanGenerationError

if TYPE_CHECKING:
    from yagura.llm.provider import LLMResponse
    from yagura.plan import Plan


PLAN_TOOL_SCHEMA = {
    "name": "create_plan",
    "description": "Create an execution plan for the user's request.",
    "input_schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step_number": {"type": "integer"},
                        "tool_name": {"type": "string"},
                        "parameters": {"type": "object"},
                        "description": {"type": "string"},
                    },
                    "required": [
                        "step_number",
                        "tool_name",
                        "parameters",
                        "description",
                    ],
                },
            }
        },
        "required": ["steps"],
    },
}


def parse_plan_from_response(response: LLMResponse) -> Plan:
    """Extract a Plan from an LLMResponse that should contain a create_plan tool call."""
    # Imported here to avoid a circular import at module load time.
    from yagura.plan import Plan, PlanState, PlanStep, StepStatus

    for call in response.tool_calls or []:
        if call.name != "create_plan":
            continue
        raw_steps = call.arguments.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise PlanGenerationError("create_plan tool_use had empty or invalid 'steps'")
        steps: list[PlanStep] = []
        for raw in raw_steps:
            try:
                steps.append(
                    PlanStep(
                        step_number=int(raw["step_number"]),
                        tool_name=str(raw["tool_name"]),
                        parameters=dict(raw.get("parameters") or {}),
                        description=str(raw.get("description", "")),
                        status=StepStatus.PENDING,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise PlanGenerationError(f"create_plan returned a malformed step: {raw!r} ({exc})") from exc
        return Plan(
            id=str(uuid4()),
            steps=steps,
            state=PlanState.DRAFT,
            created_at=datetime.now(UTC),
        )

    raise PlanGenerationError(
        "LLM did not return a `create_plan` tool_use block. "
        f"Got stop_reason={response.stop_reason!r}, content={response.content!r}"
    )
