"""Dynamic Tool (requires_llm) execution — P1."""

from __future__ import annotations

import json

import pytest

from tests.conftest import MockLLMProvider, plan_tool_response
from yagura import Agent, Config, DangerLevel, Tool, ToolResult
from yagura.confirmation.handler import AutoApproveHandler
from yagura.llm.provider import LLMResponse, TokenUsage


@pytest.mark.asyncio
async def test_dynamic_tool_invokes_executor_llm_before_handler() -> None:
    received: list[dict] = []

    def handler(command: str) -> ToolResult:
        received.append({"command": command})
        return ToolResult(success=True, data="ok")

    tool = Tool(
        name="shell_execute",
        description="run shell",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        handler=handler,
        danger_level=DangerLevel.READ,  # keep it auto-executable for the test
        requires_llm=True,
    )

    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "shell_execute",
                        "parameters": {"command": "list files"},
                        "description": "list",
                    }
                ]
            )
        ]
    )
    # Executor LLM transforms "list files" → "ls -la"
    executor = MockLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps({"command": "ls -la"}),
                tool_calls=[],
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )
        ]
    )

    agent = Agent(
        Config(
            planner_llm=planner,
            executor_llm=executor,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=AutoApproveHandler(),
        )
    )
    agent.register_tool(tool)

    response = await agent.run("list my files")
    assert response.plan.state.value == "completed"
    assert received == [{"command": "ls -la"}]


@pytest.mark.asyncio
async def test_static_tool_does_not_call_executor_llm() -> None:
    def handler() -> ToolResult:
        return ToolResult(success=True, data="direct")

    tool = Tool(
        name="list_files",
        description="list",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=handler,
        danger_level=DangerLevel.READ,
        requires_llm=False,
    )
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "list_files",
                        "parameters": {},
                        "description": "list",
                    }
                ]
            )
        ]
    )
    executor = MockLLMProvider()

    agent = Agent(
        Config(
            planner_llm=planner,
            executor_llm=executor,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=AutoApproveHandler(),
        )
    )
    agent.register_tool(tool)
    await agent.run("list")
    # Executor LLM was never called (no calls were scripted, but also
    # recorded calls == 0 because the tool was static).
    assert executor.calls == []
