"""PlanExecutor flow tests (failure halt, SKIPPED remainder, $step_N) — P1."""

from __future__ import annotations

import pytest

from tests.conftest import MockLLMProvider, plan_tool_response
from yagura import (
    Agent,
    Config,
    DangerLevel,
    PlanState,
    Tool,
    ToolResult,
)
from yagura.confirmation.handler import AutoApproveHandler
from yagura.plan import StepStatus


def _make_agent(llm) -> Agent:
    return Agent(
        Config(
            planner_llm=llm,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=AutoApproveHandler(),
        )
    )


def _ok(name: str, data=None) -> Tool:
    return Tool(
        name=name,
        description=f"{name} tool",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: ToolResult(success=True, data=data),
        danger_level=DangerLevel.READ,
    )


def _fail(name: str) -> Tool:
    def _raise():
        raise RuntimeError("boom")

    return Tool(
        name=name,
        description=f"{name} tool",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_raise,
        danger_level=DangerLevel.READ,
    )


@pytest.mark.asyncio
async def test_mid_sequence_failure_halts_and_marks_skipped() -> None:
    llm = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {"step_number": 1, "tool_name": "list_a", "parameters": {}, "description": "a"},
                    {"step_number": 2, "tool_name": "list_b", "parameters": {}, "description": "b"},
                    {"step_number": 3, "tool_name": "list_c", "parameters": {}, "description": "c"},
                ]
            )
        ]
    )
    agent = _make_agent(llm)
    agent.register_tools([_ok("list_a", 1), _fail("list_b"), _ok("list_c", 3)])

    response = await agent.run("run")
    plan = response.plan
    assert plan.state is PlanState.FAILED
    assert plan.steps[0].status is StepStatus.COMPLETED
    assert plan.steps[1].status is StepStatus.FAILED
    assert plan.steps[2].status is StepStatus.SKIPPED
    # Completed step's result is preserved.
    assert plan.steps[0].result is not None
    assert plan.steps[0].result.data == 1


@pytest.mark.asyncio
async def test_step_ref_resolution_passes_data_between_steps() -> None:
    recorded: dict[str, object] = {}

    def consume(path: str) -> ToolResult:
        recorded["path"] = path
        return ToolResult(success=True, data=None)

    llm = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "get_data",
                        "parameters": {},
                        "description": "get",
                    },
                    {
                        "step_number": 2,
                        "tool_name": "read_consume",
                        "parameters": {"path": "$step_1.data.file"},
                        "description": "consume",
                    },
                ]
            )
        ]
    )
    source = Tool(
        name="get_data",
        description="get",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: ToolResult(success=True, data={"file": "/tmp/out.txt"}),
        danger_level=DangerLevel.READ,
    )
    sink = Tool(
        name="read_consume",
        description="consume",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=consume,
        danger_level=DangerLevel.READ,
    )
    agent = _make_agent(llm)
    agent.register_tools([source, sink])
    response = await agent.run("pipe it")
    assert response.plan.state is PlanState.COMPLETED
    assert recorded["path"] == "/tmp/out.txt"


@pytest.mark.asyncio
async def test_unknown_tool_fails_step_without_crash() -> None:
    llm = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "does_not_exist",
                        "parameters": {},
                        "description": "x",
                    }
                ]
            )
        ]
    )
    agent = _make_agent(llm)
    response = await agent.run("run")
    # Unknown tool → step 1 fails, plan fails, response returned (no exception).
    assert response.plan.state in (PlanState.FAILED, PlanState.DRAFT)
    assert response.plan.steps[0].status in (StepStatus.FAILED, StepStatus.PENDING)
