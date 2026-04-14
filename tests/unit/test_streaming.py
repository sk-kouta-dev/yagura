"""PlanExecutor.execute_stream + Agent.run_stream / confirm_stream tests."""

from __future__ import annotations

import pytest

from tests.conftest import MockLLMProvider, plan_tool_response
from yagura import Agent, Config, DangerLevel, Tool, ToolResult
from yagura.confirmation.handler import AutoApproveHandler, ConfirmationHandler
from yagura.plan import Plan, PlanConfirmation, PlanState, PlanStep
from yagura.safety.assessor import DangerAssessment
from yagura.streaming import (
    LLMStreamChunk,
    PlanCancelled,
    PlanCompleted,
    PlanGenerated,
    PlanNeedsConfirmation,
    StepStarted,
    event_to_dict,
)


class _AlwaysApprove(ConfirmationHandler):
    async def confirm_plan(self, plan: Plan) -> PlanConfirmation:
        return PlanConfirmation(approved=True)

    async def confirm_danger(self, step: PlanStep, assessment: DangerAssessment) -> bool:
        return True

    async def confirm_reference_result(self, step: PlanStep, result: ToolResult) -> bool:
        return True


def _ok_tool(name: str, data=None, danger: DangerLevel = DangerLevel.READ) -> Tool:
    return Tool(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: ToolResult(success=True, data=data or {"name": name}),
        danger_level=danger,
    )


def _fail_tool(name: str) -> Tool:
    def _raise():
        raise RuntimeError("boom")

    return Tool(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_raise,
        danger_level=DangerLevel.READ,
    )


# ---------------------------------------------------------------------------
# run_stream: auto-execute path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stream_yields_step_events_and_final_completed() -> None:
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {"step_number": 1, "tool_name": "list_a", "parameters": {}, "description": "a"},
                    {"step_number": 2, "tool_name": "list_b", "parameters": {}, "description": "b"},
                ]
            )
        ]
    )
    agent = Agent(
        Config(
            planner_llm=planner,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=AutoApproveHandler(),
        )
    )
    agent.register_tools([_ok_tool("list_a"), _ok_tool("list_b")])

    events = [e async for e in agent.run_stream("do it")]
    event_types = [type(e).__name__ for e in events]
    # Expected order: PlanGenerated → StepStarted(1) → StepCompleted(1) →
    # StepStarted(2) → StepCompleted(2) → PlanCompleted.
    assert event_types == [
        "PlanGenerated",
        "StepStarted",
        "StepCompleted",
        "StepStarted",
        "StepCompleted",
        "PlanCompleted",
    ]
    # Inspect specific events.
    assert isinstance(events[0], PlanGenerated)
    assert isinstance(events[-1], PlanCompleted)
    assert events[-1].plan.state is PlanState.COMPLETED


@pytest.mark.asyncio
async def test_run_stream_yields_plan_failed_on_mid_sequence_failure() -> None:
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {"step_number": 1, "tool_name": "list_a", "parameters": {}, "description": "a"},
                    {"step_number": 2, "tool_name": "list_b", "parameters": {}, "description": "b"},
                ]
            )
        ]
    )
    agent = Agent(
        Config(
            planner_llm=planner,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=AutoApproveHandler(),
        )
    )
    agent.register_tools([_ok_tool("list_a"), _fail_tool("list_b")])

    events = [e async for e in agent.run_stream("do it")]
    types = [type(e).__name__ for e in events]
    assert "StepFailed" in types
    assert types[-1] == "PlanFailed"


# ---------------------------------------------------------------------------
# run_stream: confirmation path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stream_stops_at_confirmation_then_confirm_stream_continues() -> None:
    """A plan with DESTRUCTIVE steps streams PlanNeedsConfirmation; confirm_stream resumes."""
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {"step_number": 1, "tool_name": "delete_thing", "parameters": {}, "description": "destroy"},
                ]
            )
        ]
    )
    # delete_thing → DESTRUCTIVE via DangerRules, threshold READ → confirmation required.
    agent = Agent(
        Config(
            planner_llm=planner,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=_AlwaysApprove(),
        )
    )
    agent.register_tool(_ok_tool("delete_thing", danger=DangerLevel.DESTRUCTIVE))

    events = [e async for e in agent.run_stream("destroy it")]
    types = [type(e).__name__ for e in events]
    assert types == ["PlanGenerated", "PlanNeedsConfirmation"]
    needs = events[1]
    assert isinstance(needs, PlanNeedsConfirmation)

    # Now stream the confirmation (approve).
    from yagura.plan import PlanConfirmation

    confirm_events = [e async for e in agent.confirm_stream(needs.session_id, PlanConfirmation(approved=True))]
    confirm_types = [type(e).__name__ for e in confirm_events]
    assert confirm_types[-1] == "PlanCompleted"


@pytest.mark.asyncio
async def test_confirm_stream_cancelled_yields_plan_cancelled() -> None:
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {"step_number": 1, "tool_name": "delete_thing", "parameters": {}, "description": "destroy"},
                ]
            )
        ]
    )
    agent = Agent(
        Config(
            planner_llm=planner,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=_AlwaysApprove(),
        )
    )
    agent.register_tool(_ok_tool("delete_thing", danger=DangerLevel.DESTRUCTIVE))

    needs = None
    async for event in agent.run_stream("destroy it"):
        if isinstance(event, PlanNeedsConfirmation):
            needs = event
    assert needs is not None

    from yagura.plan import PlanConfirmation

    cancel_events = [e async for e in agent.confirm_stream(needs.session_id, PlanConfirmation(approved=False))]
    assert any(isinstance(e, PlanCancelled) for e in cancel_events)


# ---------------------------------------------------------------------------
# event_to_dict serialization
# ---------------------------------------------------------------------------


def test_event_to_dict_is_json_serializable() -> None:
    import json

    event = StepStarted(session_id="abc", step=None)
    encoded = event_to_dict(event)
    assert encoded["type"] == "step_started"
    assert encoded["session_id"] == "abc"
    # Must round-trip through json.dumps.
    json.dumps(encoded)


# ---------------------------------------------------------------------------
# LLMProvider.generate_stream default implementation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_stream_default_yields_single_chunk() -> None:
    provider = MockLLMProvider()
    from yagura.llm.provider import LLMResponse, Message

    provider.responses = [LLMResponse(content="hello from llm")]
    chunks = []
    async for chunk in provider.generate_stream(messages=[Message(role="user", content="hi")]):
        chunks.append(chunk)
    assert len(chunks) == 1
    assert isinstance(chunks[0], LLMStreamChunk)
    assert chunks[0].content == "hello from llm"
    assert chunks[0].finished is True
