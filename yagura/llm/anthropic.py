"""AnthropicProvider — Claude Messages API with tool-use."""

from __future__ import annotations

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


class AnthropicProvider(LLMProvider):
    """Claude API via the official `anthropic` SDK.

    Rate-limits and timeouts are automatically retried up to 3 times with
    exponential backoff (configurable via `retry_policy`). Other errors
    propagate immediately. Pass `retry_policy=RetryPolicy(max_attempts=1)`
    to opt out of retries (useful for tests).
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
                import anthropic  # type: ignore
            except ImportError as exc:  # pragma: no cover — guarded at runtime.
                raise ImportError(
                    "AnthropicProvider requires the `anthropic` package. Install with `pip install anthropic`."
                ) from exc
            self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        api_messages = [self._to_anthropic_message(m) for m in messages]
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": api_messages,
        }
        if system is not None:
            request["system"] = system
        if tools:
            request["tools"] = tools
        if self.timeout is not None:
            request["timeout"] = self.timeout
        request.update(kwargs)

        async def _call() -> Any:
            try:
                return await self._client.messages.create(**request)
            except Exception as exc:  # noqa: BLE001
                self._translate_error(exc)
                raise

        raw = await with_retry(_call, policy=self.retry_policy, provider_name="Anthropic")
        return self._parse_response(raw)

    # --- Translation ------------------------------------------------------

    @staticmethod
    def _to_anthropic_message(message: Message) -> dict[str, Any]:
        # Anthropic accepts role + content (string or structured list).
        return {"role": message.role, "content": message.content}

    @staticmethod
    def _parse_response(raw: Any) -> LLMResponse:
        content_text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        blocks = getattr(raw, "content", None) or []
        for block in blocks:
            block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
            if block_type == "text":
                text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else "")
                if text:
                    content_text_parts.append(text)
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=getattr(block, "id", None) or (block.get("id") if isinstance(block, dict) else ""),
                        name=getattr(block, "name", None) or (block.get("name") if isinstance(block, dict) else ""),
                        arguments=dict(
                            getattr(block, "input", None) or (block.get("input") if isinstance(block, dict) else {})
                        ),
                    )
                )

        usage_obj = getattr(raw, "usage", None)
        usage: TokenUsage | None = None
        if usage_obj is not None:
            usage = TokenUsage(
                input_tokens=getattr(usage_obj, "input_tokens", 0)
                or (usage_obj.get("input_tokens", 0) if isinstance(usage_obj, dict) else 0),
                output_tokens=getattr(usage_obj, "output_tokens", 0)
                or (usage_obj.get("output_tokens", 0) if isinstance(usage_obj, dict) else 0),
            )

        stop_reason = getattr(raw, "stop_reason", None) or (raw.get("stop_reason") if isinstance(raw, dict) else None)

        return LLMResponse(
            content="".join(content_text_parts),
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=stop_reason,
            raw=raw,
        )

    @staticmethod
    def _translate_error(exc: Exception) -> None:
        name = type(exc).__name__
        if "RateLimit" in name:
            raise LLMRateLimitError(str(exc)) from exc
        if "Timeout" in name or "APITimeout" in name:
            raise LLMTimeoutError(str(exc)) from exc
        if "APIError" in name or "BadRequest" in name:
            raise LLMInvalidResponseError(str(exc)) from exc
