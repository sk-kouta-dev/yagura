"""ConfirmationHandler ABC and an AutoApproveHandler for rule-engine use."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yagura.plan import Plan, PlanConfirmation, PlanStep
    from yagura.safety.assessor import DangerAssessment
    from yagura.tools.tool import ToolResult


class ConfirmationHandler(ABC):
    """Interface for getting user approval on plans and individual steps.

    Three interaction points:
      - confirm_plan: shown the full plan before execution begins.
      - confirm_danger: invoked per-step when DangerAssessor requires it.
      - confirm_reference_result: invoked after a step whose result has
        REFERENCE reliability, before subsequent steps use it.
    """

    @abstractmethod
    async def confirm_plan(self, plan: Plan) -> PlanConfirmation:
        """Present a plan and return the user's approval + scope."""

    @abstractmethod
    async def confirm_danger(self, step: PlanStep, assessment: DangerAssessment) -> bool:
        """Return True to approve execution of this DESTRUCTIVE/INSTALL step."""

    async def confirm_reference_result(self, step: PlanStep, result: ToolResult) -> bool:
        """Return True to continue using a REFERENCE-level result.

        Default implementation auto-approves. Override to present the
        result to the user.
        """
        return True


class AutoApproveHandler(ConfirmationHandler):
    """Approves everything. Used by RuleEngine (rules are pre-approved)."""

    async def confirm_plan(self, plan: Plan) -> PlanConfirmation:
        from yagura.plan import PlanConfirmation

        return PlanConfirmation(approved=True)

    async def confirm_danger(self, step: PlanStep, assessment: DangerAssessment) -> bool:
        # Spec: DESTRUCTIVE operations in automated rules still require
        # confirmation via the configured ConfirmationHandler. So a rule
        # engine that wants truly silent execution should combine this
        # with a relaxed DangerAssessor configuration, not override this
        # method with True.
        return assessment.level.name in ("READ", "MODIFY")

    async def confirm_reference_result(self, step: PlanStep, result: ToolResult) -> bool:
        return True
