"""Conversational memory — Session.history is carried into Planner system prompt."""

from __future__ import annotations

import pytest

from tests.conftest import MockLLMProvider, plan_tool_response
from yagura import Agent, Config, DangerLevel, Tool, ToolResult
from yagura.confirmation.handler import AutoApproveHandler
from yagura.plan import PlanState


def _list_tool() -> Tool:
    return Tool(
        name="list_files",
        description="list files",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=lambda path: ToolResult(success=True, data={"files": [f"{path}/a.txt"]}),
        danger_level=DangerLevel.READ,
    )


@pytest.mark.asyncio
async def test_second_turn_receives_prior_history_in_system_prompt() -> None:
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "list_files",
                        "parameters": {"path": "/tmp"},
                        "description": "list /tmp",
                    }
                ]
            ),
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "list_files",
                        "parameters": {"path": "/opt"},
                        "description": "list /opt",
                    }
                ]
            ),
        ]
    )
    agent = Agent(
        Config(
            planner_llm=planner,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=AutoApproveHandler(),
        )
    )
    agent.register_tool(_list_tool())

    r1 = await agent.run("show /tmp")
    assert r1.plan.state is PlanState.COMPLETED
    # Turn 1 had no prior history; the MockLLMProvider sees the DEFAULT planner
    # system prompt (from LLMProvider.generate_plan), NOT a history-prefixed one.
    first_call_system = planner.calls[0]["system"]
    assert first_call_system is not None  # generate_plan always passes a default
    assert "Prior conversation turns" not in first_call_system

    # Turn 2 reuses the session and should receive history in the system prompt.
    r2 = await agent.run("show /opt", session_id=r1.session.id)
    assert r2.plan.state is PlanState.COMPLETED

    second_call_system = planner.calls[1]["system"]
    assert second_call_system is not None
    assert "Prior conversation turns" in second_call_system
    assert "show /tmp" in second_call_system
    # The completed step from turn 1 is summarized.
    assert "list_files" in second_call_system


@pytest.mark.asyncio
async def test_session_history_is_appended_after_each_turn() -> None:
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "list_files",
                        "parameters": {"path": "/a"},
                        "description": "list /a",
                    }
                ]
            ),
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "list_files",
                        "parameters": {"path": "/b"},
                        "description": "list /b",
                    }
                ]
            ),
        ]
    )
    agent = Agent(
        Config(
            planner_llm=planner,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=AutoApproveHandler(),
        )
    )
    agent.register_tool(_list_tool())

    r1 = await agent.run("first request")
    # The returned session reflects the completed turn.
    assert len(r1.session.history) == 1
    assert r1.session.history[0].user_input == "first request"
    # And the persisted session agrees.
    reloaded = await agent.session_manager.load(r1.session.id)
    assert len(reloaded.history) == 1

    r2 = await agent.run("second request", session_id=r1.session.id)
    assert len(r2.session.history) == 2
    reloaded2 = await agent.session_manager.load(r2.session.id)
    assert len(reloaded2.history) == 2
    assert reloaded2.history[1].user_input == "second request"


@pytest.mark.asyncio
async def test_history_bounded_to_history_max_turns_in_prompt() -> None:
    """Only the most recent `history_max_turns` turns reach the Planner."""
    # Generate 10 canned plan responses (one per turn).
    responses = [
        plan_tool_response(
            [
                {
                    "step_number": 1,
                    "tool_name": "list_files",
                    "parameters": {"path": f"/dir-{i}"},
                    "description": f"list dir-{i}",
                }
            ]
        )
        for i in range(10)
    ]
    planner = MockLLMProvider(responses=list(responses))
    agent = Agent(
        Config(
            planner_llm=planner,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=AutoApproveHandler(),
        )
    )
    agent.history_max_turns = 3  # Tighten the cap for the test.
    agent.register_tool(_list_tool())

    session_id = None
    for i in range(10):
        response = await agent.run(f"request {i}", session_id=session_id)
        session_id = response.session.id

    # The final call's system prompt should reference at most `history_max_turns`
    # prior turns — the 7th, 8th, 9th (indices 6..8 out of 0..9, since turn 10
    # is the one we just made and isn't yet in history at prompt-build time).
    final_system = planner.calls[-1]["system"]
    assert final_system is not None
    # Oldest included turn is "request 6" (index 6). Earlier turns must be gone.
    assert "request 6" in final_system
    assert "request 7" in final_system
    assert "request 8" in final_system
    assert "request 0" not in final_system
    assert "request 3" not in final_system
