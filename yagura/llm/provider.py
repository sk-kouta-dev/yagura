"""LLMProvider ABC, message/response dataclasses, and LLMRouter ABC."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yagura.plan import Plan, StepContext
    from yagura.tools.tool import Tool


@dataclass
class Message:
    """A single chat turn."""

    role: str  # "system", "user", "assistant", "tool"
    content: str | list[dict[str, Any]]
    name: str | None = None


@dataclass
class ToolCall:
    """A tool-use block returned by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class TokenUsage:
    """Token counts reported by the LLM provider."""

    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


@dataclass
class LLMResponse:
    """Normalized response from an LLMProvider."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    stop_reason: str | None = None
    raw: Any = None  # Provider-specific response, for advanced consumers.


class LLMProvider(ABC):
    """Abstract base class for all LLM backends.

    `generate` is the low-level primitive; `generate_plan` is a higher-level
    convenience that wraps `generate` with the `create_plan` tool schema
    and returns a parsed Plan.

    `generate_stream` is optional: the default implementation wraps
    `generate` and yields a single `LLMStreamChunk` with the full content.
    Providers that support native streaming should override it.
    """

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response. If tools are provided, may return tool_use blocks."""

    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ):
        """Stream deltas from the LLM.

        Default implementation: call `generate` once and yield the full
        content as a single chunk. Providers with native streaming should
        override to yield progressive chunks.
        """
        from yagura.streaming import LLMStreamChunk

        response = await self.generate(messages=messages, tools=tools, system=system, **kwargs)
        yield LLMStreamChunk(content=response.content, finished=True, raw=response)

    async def generate_plan(
        self,
        user_input: str,
        tool_schemas: list[dict[str, Any]],
        system: str | None = None,
    ) -> Plan:
        """Generate an execution Plan from user input and available tools.

        The default implementation uses the `create_plan` tool-use schema
        described in the framework spec. Subclasses can override for
        provider-specific optimizations.
        """
        # Import here to avoid circular imports (plan imports LLMProvider indirectly).
        from yagura.llm.plan_schema import PLAN_TOOL_SCHEMA, parse_plan_from_response

        combined_tools = [PLAN_TOOL_SCHEMA, *tool_schemas]
        default_system = (
            "You are the Planner for an AI agent. Given the user's request and the "
            "available tools, produce a step-by-step execution plan by calling the "
            "`create_plan` tool. Each step must reference exactly one registered tool. "
            "Use $step_N.field references to pass data between steps. Do not invent tools."
        )
        response = await self.generate(
            messages=[Message(role="user", content=user_input)],
            tools=combined_tools,
            system=system or default_system,
        )
        return parse_plan_from_response(response)


class LLMRouter(ABC):
    """Routes LLM selection per Dynamic Tool step.

    Enables data-attribute-based routing: confidential data to local LLM,
    general data to cloud API, cost optimization, compliance, etc.
    """

    @abstractmethod
    async def select(
        self,
        tool: Tool,
        params: dict[str, Any],
        context: StepContext,
    ) -> LLMProvider:
        """Return the LLMProvider to use for this Dynamic Tool execution."""


class DefaultLLMRouter(LLMRouter):
    """Always returns executor_llm (or planner_llm as fallback)."""

    def __init__(
        self,
        executor_llm: LLMProvider | None = None,
        planner_llm: LLMProvider | None = None,
    ) -> None:
        self.executor_llm = executor_llm
        self.planner_llm = planner_llm

    async def select(
        self,
        tool: Tool,
        params: dict[str, Any],
        context: StepContext,
    ) -> LLMProvider:
        chosen = self.executor_llm or self.planner_llm
        if chosen is None:
            raise RuntimeError(
                "DefaultLLMRouter has no LLMProvider configured. Set executor_llm or planner_llm on the Config."
            )
        return chosen
