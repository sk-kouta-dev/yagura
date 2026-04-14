"""End-to-end tests for yagura-tools-llm (LLM-as-tool execution path)."""

from __future__ import annotations

import pytest
from yagura_tools.llm import tools as llm_tools

from tests.conftest import MockLLMProvider, plan_tool_response
from yagura import Agent, Config, DangerLevel, ReliabilityLevel
from yagura.confirmation.handler import ConfirmationHandler
from yagura.llm.provider import LLMResponse, TokenUsage
from yagura.plan import Plan, PlanConfirmation, PlanStep
from yagura.safety.assessor import DangerAssessment
from yagura.tools.tool import ToolResult


def _find_tool(name: str):
    return next(t for t in llm_tools if t.name == name)


class _PassthroughHandler(ConfirmationHandler):
    """Auto-approves everything including REFERENCE results (LLM outputs)."""

    async def confirm_plan(self, plan: Plan) -> PlanConfirmation:
        return PlanConfirmation(approved=True)

    async def confirm_danger(self, step: PlanStep, assessment: DangerAssessment) -> bool:
        return True

    async def confirm_reference_result(self, step: PlanStep, result: ToolResult) -> bool:
        return True


def _text_response(text: str) -> LLMResponse:
    return LLMResponse(
        content=text,
        tool_calls=[],
        usage=TokenUsage(input_tokens=5, output_tokens=5),
    )


# ---------------------------------------------------------------------------
# Per-tool smoke tests — the executor LLM returns plain text, which becomes
# ToolResult.data[output_key].
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_summarize_end_to_end() -> None:
    summarize = _find_tool("llm_summarize")
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "llm_summarize",
                        "parameters": {"text": "Long text here.", "max_length": 50, "style": "concise"},
                        "description": "summarize text",
                    }
                ]
            )
        ]
    )
    executor = MockLLMProvider(responses=[_text_response("Short summary.")])
    agent = Agent(
        Config(
            planner_llm=planner,
            executor_llm=executor,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=_PassthroughHandler(),
        )
    )
    agent.register_tool(summarize)

    response = await agent.run("summarize this")
    assert response.plan.state.value == "completed"
    data = response.plan.steps[0].result.data
    assert data["summary"] == "Short summary."
    # The prompt sent to the executor LLM is preserved for debugging/audit.
    assert "Long text here." in data["prompt"]
    assert response.plan.steps[0].result.reliability is ReliabilityLevel.REFERENCE


@pytest.mark.asyncio
async def test_llm_translate_end_to_end() -> None:
    translate = _find_tool("llm_translate")
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "llm_translate",
                        "parameters": {
                            "text": "Hello world",
                            "target_language": "ja",
                            "source_language": "en",
                        },
                        "description": "translate",
                    }
                ]
            )
        ]
    )
    executor = MockLLMProvider(responses=[_text_response("こんにちは世界")])
    agent = Agent(
        Config(
            planner_llm=planner,
            executor_llm=executor,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=_PassthroughHandler(),
        )
    )
    agent.register_tool(translate)

    response = await agent.run("translate this")
    assert response.plan.state.value == "completed"
    assert response.plan.steps[0].result.data["translation"] == "こんにちは世界"


@pytest.mark.asyncio
async def test_llm_classify_end_to_end() -> None:
    classify = _find_tool("llm_classify")
    planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "llm_classify",
                        "parameters": {
                            "text": "The food was cold",
                            "categories": ["positive", "negative", "neutral"],
                        },
                        "description": "classify sentiment",
                    }
                ]
            )
        ]
    )
    executor = MockLLMProvider(responses=[_text_response("negative")])
    agent = Agent(
        Config(
            planner_llm=planner,
            executor_llm=executor,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=_PassthroughHandler(),
        )
    )
    agent.register_tool(classify)

    response = await agent.run("classify this")
    assert response.plan.state.value == "completed"
    assert response.plan.steps[0].result.data["category"] == "negative"


# ---------------------------------------------------------------------------
# Metadata checks
# ---------------------------------------------------------------------------


def test_all_llm_tools_use_llm_task_template() -> None:
    """Every llm_* tool must be an LLM-as-tool (template set, requires_llm=False)."""
    for tool in llm_tools:
        assert tool.llm_task_template is not None, f"{tool.name} must set llm_task_template"
        assert tool.llm_output_key, f"{tool.name} must define an output_key"
        assert tool.danger_level is DangerLevel.READ
        assert tool.default_reliability is ReliabilityLevel.REFERENCE
        # They are NOT Dynamic Tools in the requires_llm sense; they're a
        # distinct execution path.
        assert tool.requires_llm is False


def test_missing_executor_llm_is_reported_gracefully() -> None:
    """If an LLM-as-tool runs without an executor_llm, the step fails cleanly."""
    # This is a contract test: we don't run it end-to-end because the agent
    # builder always has an executor_llm (fallback to planner). We instead
    # verify the PlanExecutor helper that enforces this invariant.
    import asyncio

    from yagura.plan import PlanExecutor

    summarize = _find_tool("llm_summarize")
    executor = PlanExecutor(
        tool_registry=None,  # not used by this helper
        tool_executor=None,  # not used by this helper
        danger_assessor=None,  # not used
        confirmation_handler=None,  # not used
        executor_llm=None,
    )
    result = asyncio.run(executor._run_llm_task_tool(summarize, {"text": "hi", "max_length": 10, "style": "x"}))
    assert result.success is False
    assert "executor_llm" in (result.error or "")


def test_template_rendering_handles_missing_params() -> None:
    """If a template references a missing parameter, the tool fails cleanly with a clear error."""
    import asyncio

    from tests.conftest import MockLLMProvider
    from yagura.plan import PlanExecutor

    summarize = _find_tool("llm_summarize")
    executor = PlanExecutor(
        tool_registry=None,
        tool_executor=None,
        danger_assessor=None,
        confirmation_handler=None,
        executor_llm=MockLLMProvider(),
    )
    # The summarize template uses {text}, {max_length}, {style}. We omit `text`.
    result = asyncio.run(executor._run_llm_task_tool(summarize, {"max_length": 10, "style": "concise"}))
    assert result.success is False
    assert "text" in (result.error or "")
