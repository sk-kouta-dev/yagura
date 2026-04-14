"""CLIConfirmationHandler — default ConfirmationHandler for terminal use."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from yagura.confirmation.handler import ConfirmationHandler

if TYPE_CHECKING:
    from yagura.plan import Plan, PlanConfirmation, PlanStep
    from yagura.safety.assessor import DangerAssessment
    from yagura.tools.tool import ToolResult


class CLIConfirmationHandler(ConfirmationHandler):
    """Prompts the user via stdin/stdout.

    Plan display shows step numbers, labels, and descriptions (internal
    tool names are hidden in the friendly summary, but exposed when the
    user requests details).
    """

    def __init__(self, show_tool_names: bool = False) -> None:
        self.show_tool_names = show_tool_names

    async def confirm_plan(self, plan: Plan) -> PlanConfirmation:
        from yagura.plan import PlanConfirmation

        self._render_plan(plan)
        answer = await _aask("Approve plan? [y=yes / n=no / scope=N to limit to step N] > ")
        answer = answer.strip().lower()
        if answer in ("y", "yes", ""):
            return PlanConfirmation(approved=True)
        if answer.startswith("scope="):
            try:
                scope = int(answer.split("=", 1)[1])
            except ValueError:
                scope = None
            return PlanConfirmation(approved=True, scope=scope)
        return PlanConfirmation(approved=False)

    async def confirm_danger(self, step: PlanStep, assessment: DangerAssessment) -> bool:
        print()
        print("⚠  Confirmation required for potentially dangerous step.")
        print(f"   Step {step.step_number}: {step.description}")
        if self.show_tool_names:
            print(f"   Tool: {step.tool_name}")
            print(f"   Parameters: {json.dumps(step.parameters, ensure_ascii=False)}")
        print(f"   Danger level: {assessment.level.name}")
        print(f"   Assessment layer: {assessment.layer} (confidence={assessment.confidence:.2f})")
        print(f"   Reason: {assessment.reason}")
        if assessment.policy_check is not None:
            pc = assessment.policy_check
            print(f"   Policy: allowed={pc.allowed}, admin_required={pc.requires_admin_approval}, reason={pc.reason}")
        answer = await _aask("   Approve this step? [y/N] > ")
        return answer.strip().lower() in ("y", "yes")

    async def confirm_reference_result(self, step: PlanStep, result: ToolResult) -> bool:
        print()
        print(f"ℹ  Step {step.step_number} returned REFERENCE-level data.")
        preview = _short_repr(result.data, 400)
        print(f"   Preview: {preview}")
        answer = await _aask("   Continue using this data? [Y/n] > ")
        return answer.strip().lower() not in ("n", "no")

    # --- Plan rendering --------------------------------------------------

    def _render_plan(self, plan: Plan) -> None:
        print()
        print(f"Plan {plan.id} ({len(plan.steps)} steps)")
        for step in plan.steps:
            label = step.description or "(no description)"
            line = f"  {step.step_number:>2}. {label}"
            if self.show_tool_names:
                line += f"  [tool={step.tool_name}]"
            if step.danger_level is not None:
                line += f"  [{step.danger_level.name}]"
            print(line)


def _short_repr(value: object, limit: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = repr(value)
    if len(text) > limit:
        return text[:limit] + f"... [truncated {len(text) - limit} chars]"
    return text


async def _aask(prompt: str) -> str:
    # input() is blocking; run it in the default executor so we don't stall the loop.
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))
