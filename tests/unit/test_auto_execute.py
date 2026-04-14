"""Auto-execute threshold behavior — P0."""

from __future__ import annotations

import pytest

from tests.conftest import MockLLMProvider, plan_tool_response
from yagura import (
    Agent,
    Config,
    DangerLevel,
    ExecutionEnvironment,
    Tool,
    ToolResult,
)
from yagura.confirmation.handler import AutoApproveHandler


def _build_agent(
    threshold: DangerLevel | None,
    plan_steps: list[dict],
    tools: list[Tool],
) -> tuple[Agent, MockLLMProvider]:
    llm = MockLLMProvider(responses=[plan_tool_response(plan_steps)])
    agent = Agent(
        Config(
            planner_llm=llm,
            auto_execute_threshold=threshold,
            execution_env=ExecutionEnvironment.LOCAL,
            confirmation_handler=AutoApproveHandler(),
        )
    )
    agent.register_tools(tools)
    return agent, llm


def _simple_tool(name: str, *, handler_return=None):
    return Tool(
        name=name,
        description=f"{name} tool",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: ToolResult(success=True, data=handler_return),
    )


@pytest.mark.asyncio
async def test_all_read_steps_auto_execute_when_threshold_is_read() -> None:
    tools = [_simple_tool("list_files")]
    agent, _ = _build_agent(
        DangerLevel.READ,
        [{"step_number": 1, "tool_name": "list_files", "parameters": {}, "description": "list"}],
        tools,
    )
    response = await agent.run("anything")
    assert response.needs_confirmation is False
    assert response.plan.state.value == "completed"


@pytest.mark.asyncio
async def test_modify_step_requires_confirmation_when_threshold_is_read() -> None:
    tools = [_simple_tool("copy_file")]
    agent, _ = _build_agent(
        DangerLevel.READ,
        [{"step_number": 1, "tool_name": "copy_file", "parameters": {}, "description": "copy"}],
        tools,
    )
    response = await agent.run("anything")
    assert response.needs_confirmation is True
    assert response.plan.state.value == "draft"


@pytest.mark.asyncio
async def test_none_threshold_always_requires_confirmation() -> None:
    tools = [_simple_tool("list_files")]
    agent, _ = _build_agent(
        None,
        [{"step_number": 1, "tool_name": "list_files", "parameters": {}, "description": "list"}],
        tools,
    )
    response = await agent.run("anything")
    assert response.needs_confirmation is True


@pytest.mark.asyncio
async def test_mixed_plan_fails_if_any_step_exceeds_threshold() -> None:
    tools = [_simple_tool("list_files"), _simple_tool("delete_file")]
    agent, _ = _build_agent(
        DangerLevel.MODIFY,
        [
            {"step_number": 1, "tool_name": "list_files", "parameters": {}, "description": "list"},
            {"step_number": 2, "tool_name": "delete_file", "parameters": {}, "description": "delete"},
        ],
        tools,
    )
    response = await agent.run("anything")
    # Any DESTRUCTIVE step → confirmation required, even with a MODIFY threshold.
    assert response.needs_confirmation is True


@pytest.mark.asyncio
async def test_threshold_destructive_auto_executes_modify_plans() -> None:
    tools = [_simple_tool("copy_file")]
    agent, _ = _build_agent(
        DangerLevel.DESTRUCTIVE,
        [{"step_number": 1, "tool_name": "copy_file", "parameters": {}, "description": "copy"}],
        tools,
    )
    response = await agent.run("anything")
    assert response.needs_confirmation is False
