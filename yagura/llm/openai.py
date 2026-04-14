"""OpenAIProvider — Chat Completions with function calling."""

from __future__ import annotations

import json
from typing import Any

from yagura.errors import (
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from yagura.llm.provider import (
    LLMProvider,
    LLMResponse,
    Message,
    TokenUsage,
    ToolCall,
)
from yagura.llm.retry import DEFAULT_POLICY, RetryPolicy, with_retry


class OpenAIProvider(LLMProvider):
    """OpenAI API via the official `openai` SDK.

    Rate-limits and timeouts are retried with exponential backoff via
    `retry_policy`; see yagura.llm.retry.RetryPolicy.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        client: Any | None = None,
        max_tokens: int = 4096,
        timeout: float | None = None,
        retry_policy: RetryPolicy = DEFAULT_POLICY,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retry_policy = retry_policy
        if client is not None:
            self._client = client
        else:
            try:
                import openai  # type: ignore
            except ImportError as exc:  # pragma: no cover
                raise ImportError(
                    "OpenAIProvider requires the `openai` package. Install with `pip install openai`."
                ) from exc
            self._client = openai.AsyncOpenAI(api_key=api_key)

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        api_messages: list[dict[str, Any]] = []
        if system:
            api_messages.append({"role": "system", "content": system})
        for m in messages:
            api_messages.append({"role": m.role, "content": m.content})

        request: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": self.max_tokens,
        }
        if tools:
            request["tools"] = [self._translate_tool(t) for t in tools]
        if self.timeout is not None:
            request["timeout"] = self.timeout
        request.update(kwargs)

        async def _call() -> Any:
            try:
                return await self._client.chat.completions.create(**request)
            except Exception as exc:  # noqa: BLE001
                self._translate_error(exc)
                raise

        raw = await with_retry(_call, policy=self.retry_policy, provider_name="OpenAI")
        return self._parse_response(raw)

    @staticmethod
    def _translate_tool(tool_schema: dict[str, Any]) -> dict[str, Any]:
        """Convert Anthropic-style tool schema → OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": tool_schema["name"],
                "description": tool_schema.get("description", ""),
                "parameters": tool_schema.get("input_schema") or tool_schema.get("parameters") or {},
            },
        }

    @staticmethod
    def _parse_response(raw: Any) -> LLMResponse:
        choice = raw.choices[0]
        message = choice.message
        content = getattr(message, "content", None) or ""

        tool_calls: list[ToolCall] = []
        for tc in getattr(message, "tool_calls", None) or []:
            fn = getattr(tc, "function", None) or tc.get("function", {})
            raw_args = getattr(fn, "arguments", None) or fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError as exc:
                raise LLMInvalidResponseError(f"OpenAI returned non-JSON tool arguments: {raw_args!r}") from exc
            tool_calls.append(
                ToolCall(
                    id=getattr(tc, "id", None) or tc.get("id", ""),
                    name=getattr(fn, "name", None) or fn.get("name", ""),
                    arguments=args,
                )
            )

        usage_obj = getattr(raw, "usage", None)
        usage: TokenUsage | None = None
        if usage_obj is not None:
            usage = TokenUsage(
                input_tokens=getattr(usage_obj, "prompt_tokens", 0),
                output_tokens=getattr(usage_obj, "completion_tokens", 0),
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=getattr(choice, "finish_reason", None),
            raw=raw,
        )

    @staticmethod
    def _translate_error(exc: Exception) -> None:
        name = type(exc).__name__
        if "RateLimit" in name:
            raise LLMRateLimitError(str(exc)) from exc
        if "Timeout" in name:
            raise LLMTimeoutError(str(exc)) from exc
        if "APIError" in name or "BadRequest" in name:
            raise LLMInvalidResponseError(str(exc)) from exc
