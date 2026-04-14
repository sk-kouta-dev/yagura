"""Shared fixtures and a mock LLM provider."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from yagura.llm.provider import (
    LLMProvider,
    LLMResponse,
    Message,
    TokenUsage,
    ToolCall,
)


@dataclass
class MockLLMProvider(LLMProvider):
    """Scriptable LLM for tests.

    Responses are either a list (consumed in order) or a callable that
    receives (messages, tools, system) and returns an LLMResponse.
    """

    responses: list[LLMResponse] | Callable[..., LLMResponse] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "system": system, "kwargs": kwargs})
        if callable(self.responses):
            return self.responses(messages=messages, tools=tools, system=system)
        if not self.responses:
            raise AssertionError("MockLLMProvider has no more scripted responses")
        return self.responses.pop(0)


def plan_tool_response(steps: list[dict[str, Any]]) -> LLMResponse:
    """Build an LLMResponse that carries a single create_plan tool_use block."""
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="plan-1",
                name="create_plan",
                arguments={"steps": steps},
            )
        ],
        usage=TokenUsage(input_tokens=10, output_tokens=20),
        stop_reason="tool_use",
    )


def assess_response(level: str, confidence: float = 1.0, reason: str = "") -> LLMResponse:
    """Build an LLMResponse that mimics the LLMAssessor JSON format."""
    return LLMResponse(
        content=json.dumps({"level": level, "confidence": confidence, "reason": reason}),
        tool_calls=[],
        usage=TokenUsage(input_tokens=5, output_tokens=5),
    )


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    return MockLLMProvider()
