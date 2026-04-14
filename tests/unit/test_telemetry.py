"""OpenTelemetry integration (optional; tests verify no-op when OTEL is absent)."""

from __future__ import annotations

import pytest

from tests.conftest import MockLLMProvider, plan_tool_response
from yagura import Agent, Config, DangerLevel, Tool, ToolResult
from yagura.confirmation.handler import AutoApproveHandler
from yagura.telemetry import span, tracer


def test_span_noop_when_otel_absent_does_not_crash() -> None:
    """Without opentelemetry-api installed, span() returns a no-op context manager."""
    with span("yagura.test", key="value", number=42, none_val=None) as s:
        # Setting attributes must work on the no-op span.
        s.set_attribute("extra", "hello")
        s.set_status("irrelevant")
        s.record_exception(RuntimeError("ignored"))


def test_tracer_is_always_callable() -> None:
    t = tracer()
    assert t is not None


def test_span_exception_propagates() -> None:
    with pytest.raises(ValueError):
        with span("yagura.test"):
            raise ValueError("boom")


@pytest.mark.asyncio
async def test_agent_run_inside_span_succeeds() -> None:
    """Normal agent.run should succeed under the telemetry wrapper (no OTEL installed)."""
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {"step_number": 1, "tool_name": "list_it", "parameters": {}, "description": "list"},
                ]
            )
        ]
    )
    tool = Tool(
        name="list_it",
        description="list",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: ToolResult(success=True, data={"ok": True}),
        danger_level=DangerLevel.READ,
    )
    agent = Agent(
        Config(
            planner_llm=planner,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=AutoApproveHandler(),
        )
    )
    agent.register_tool(tool)

    response = await agent.run("list it")
    assert response.plan.state.value == "completed"
