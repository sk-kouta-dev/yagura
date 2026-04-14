"""LLMRouter tests — P1."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import MockLLMProvider
from yagura.llm.provider import DefaultLLMRouter, LLMRouter
from yagura.plan import StepContext
from yagura.tools.tool import Tool


def _tool() -> Tool:
    return Tool(
        name="shell_execute",
        description="run shell",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: None,
    )


@pytest.mark.asyncio
async def test_default_router_returns_executor_when_set() -> None:
    planner = MockLLMProvider()
    executor = MockLLMProvider()
    router = DefaultLLMRouter(executor_llm=executor, planner_llm=planner)
    selected = await router.select(_tool(), {}, StepContext())
    assert selected is executor


@pytest.mark.asyncio
async def test_default_router_falls_back_to_planner() -> None:
    planner = MockLLMProvider()
    router = DefaultLLMRouter(executor_llm=None, planner_llm=planner)
    selected = await router.select(_tool(), {}, StepContext())
    assert selected is planner


@pytest.mark.asyncio
async def test_custom_router_receives_all_args() -> None:
    planner = MockLLMProvider()
    confidential = MockLLMProvider()

    class ConfidentialRouter(LLMRouter):
        def __init__(self) -> None:
            self.saw: list[tuple[Tool, dict[str, Any], StepContext]] = []

        async def select(self, tool, params, context):  # noqa: ANN001
            self.saw.append((tool, params, context))
            if params.get("path", "").startswith("/secret/"):
                return confidential
            return planner

    router = ConfidentialRouter()
    secret = await router.select(_tool(), {"path": "/secret/x"}, StepContext())
    assert secret is confidential
    public = await router.select(_tool(), {"path": "/public/y"}, StepContext())
    assert public is planner
    assert len(router.saw) == 2
