"""Plan state transition tests — P0."""

from __future__ import annotations

import pytest

from yagura.errors import InvalidPlanStateTransitionError
from yagura.plan import Plan, PlanState


def _plan() -> Plan:
    return Plan(id="p1", steps=[])


# --- Valid transitions -----------------------------------------------------


@pytest.mark.parametrize(
    "from_state, to_state",
    [
        (PlanState.DRAFT, PlanState.CONFIRMED),
        (PlanState.DRAFT, PlanState.RUNNING),
        (PlanState.DRAFT, PlanState.CANCELLED),
        (PlanState.CONFIRMED, PlanState.RUNNING),
        (PlanState.CONFIRMED, PlanState.CANCELLED),
        (PlanState.RUNNING, PlanState.COMPLETED),
        (PlanState.RUNNING, PlanState.FAILED),
        (PlanState.RUNNING, PlanState.PAUSED),
        (PlanState.RUNNING, PlanState.CANCELLED),
        (PlanState.PAUSED, PlanState.RUNNING),
        (PlanState.PAUSED, PlanState.CANCELLED),
        (PlanState.FAILED, PlanState.REPLANNED),
        (PlanState.FAILED, PlanState.CANCELLED),
        (PlanState.REPLANNED, PlanState.CONFIRMED),
        (PlanState.REPLANNED, PlanState.CANCELLED),
    ],
)
def test_valid_transitions_are_accepted(from_state: PlanState, to_state: PlanState) -> None:
    plan = _plan()
    plan.state = from_state
    plan.transition_to(to_state)
    assert plan.state is to_state


# --- Invalid transitions ---------------------------------------------------


@pytest.mark.parametrize(
    "from_state, to_state",
    [
        (PlanState.COMPLETED, PlanState.RUNNING),
        (PlanState.CANCELLED, PlanState.RUNNING),
        (PlanState.COMPLETED, PlanState.DRAFT),
        (PlanState.DRAFT, PlanState.COMPLETED),
        (PlanState.DRAFT, PlanState.FAILED),
        (PlanState.CONFIRMED, PlanState.COMPLETED),
        (PlanState.CANCELLED, PlanState.REPLANNED),
    ],
)
def test_invalid_transitions_are_rejected(from_state: PlanState, to_state: PlanState) -> None:
    plan = _plan()
    plan.state = from_state
    with pytest.raises(InvalidPlanStateTransitionError):
        plan.transition_to(to_state)


def test_confirmed_at_is_set_on_confirmation() -> None:
    plan = _plan()
    assert plan.confirmed_at is None
    plan.transition_to(PlanState.CONFIRMED)
    assert plan.confirmed_at is not None
