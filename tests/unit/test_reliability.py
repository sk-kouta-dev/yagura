"""Reliability propagation and override — P0."""

from __future__ import annotations

import pytest

from tests.conftest import MockLLMProvider, plan_tool_response
from yagura import (
    Agent,
    Config,
    DangerLevel,
    ReliabilityLevel,
    Tool,
    ToolResult,
)
from yagura.confirmation.handler import ConfirmationHandler
from yagura.plan import Plan, PlanConfirmation, PlanStep
from yagura.safety.assessor import DangerAssessment
from yagura.tools.executor import ToolExecutor
from yagura.tools.tool import Tool as ToolDC


class RecordingHandler(ConfirmationHandler):
    def __init__(self) -> None:
        self.reference_calls: list[tuple[int, ToolResult]] = []

    async def confirm_plan(self, plan: Plan) -> PlanConfirmation:
        return PlanConfirmation(approved=True)

    async def confirm_danger(self, step: PlanStep, assessment: DangerAssessment) -> bool:
        return True

    async def confirm_reference_result(self, step: PlanStep, result: ToolResult) -> bool:
        self.reference_calls.append((step.step_number, result))
        return True


@pytest.mark.asyncio
async def test_tool_default_reliability_flows_to_result() -> None:
    tool = ToolDC(
        name="list_files",
        description="list",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: ["a", "b"],
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    )
    executor = ToolExecutor()
    result = await executor.execute(tool, {})
    assert result.reliability is ReliabilityLevel.AUTHORITATIVE


@pytest.mark.asyncio
async def test_result_reliability_overrides_default() -> None:
    tool = ToolDC(
        name="list_files",
        description="list",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: ToolResult(success=True, data=[], reliability=ReliabilityLevel.VERIFIED),
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    )
    executor = ToolExecutor()
    result = await executor.execute(tool, {})
    assert result.reliability is ReliabilityLevel.VERIFIED


@pytest.mark.asyncio
async def test_reference_result_triggers_confirmation_step() -> None:
    handler = RecordingHandler()
    llm = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "search_notes",
                        "parameters": {},
                        "description": "search",
                    }
                ]
            )
        ]
    )
    tool = Tool(
        name="search_notes",
        description="search personal notes",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: "draft info",
        default_reliability=ReliabilityLevel.REFERENCE,
        danger_level=DangerLevel.READ,
    )
    agent = Agent(
        Config(
            planner_llm=llm,
            confirmation_handler=handler,
            auto_execute_threshold=DangerLevel.READ,
        )
    )
    agent.register_tool(tool)
    await agent.run("give me info")
    assert len(handler.reference_calls) == 1
    step_number, result = handler.reference_calls[0]
    assert step_number == 1
    assert result.reliability is ReliabilityLevel.REFERENCE
