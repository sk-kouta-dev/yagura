"""OllamaProvider — local LLM via Ollama."""

from __future__ import annotations

import json
from typing import Any

from yagura.errors import LLMInvalidResponseError, LLMTimeoutError
from yagura.llm.provider import (
    LLMProvider,
    LLMResponse,
    Message,
    TokenUsage,
    ToolCall,
)
from yagura.llm.retry import DEFAULT_POLICY, RetryPolicy, with_retry


class OllamaProvider(LLMProvider):
    """Local LLM via the `ollama` Python package.

    Timeouts are retried with exponential backoff via `retry_policy`.
    Ollama rarely returns true rate-limits (it's local), so in practice
    only timeouts trigger retries.
    """

    def __init__(
        self,
        model: str,
        host: str | None = None,
        client: Any | None = None,
        options: dict[str, Any] | None = None,
        retry_policy: RetryPolicy = DEFAULT_POLICY,
    ) -> None:
        self.model = model
        self.options = options or {}
        self.retry_policy = retry_policy
        if client is not None:
            self._client = client
        else:
            try:
                import ollama  # type: ignore
            except ImportError as exc:  # pragma: no cover
                raise ImportError(
                    "OllamaProvider requires the `ollama` package. Install with `pip install ollama`."
                ) from exc
            self._client = ollama.AsyncClient(host=host) if host else ollama.AsyncClient()

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
            content = m.content if isinstance(m.content, str) else json.dumps(m.content)
            api_messages.append({"role": m.role, "content": content})

        request: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "options": {**self.options, **kwargs},
        }
        if tools:
            # Ollama uses the OpenAI-style tool schema.
            request["tools"] = [self._translate_tool(t) for t in tools]

        async def _call() -> Any:
            try:
                return await self._client.chat(**request)
            except Exception as exc:  # noqa: BLE001
                if "timeout" in str(exc).lower():
                    raise LLMTimeoutError(str(exc)) from exc
                raise

        raw = await with_retry(_call, policy=self.retry_policy, provider_name="Ollama")
        return self._parse_response(raw)

    @staticmethod
    def _translate_tool(tool_schema: dict[str, Any]) -> dict[str, Any]:
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
        # Ollama returns either a pydantic-like object or a dict, depending on version.
        if isinstance(raw, dict):
            message = raw.get("message", {})
            content = message.get("content", "") or ""
            raw_tool_calls = message.get("tool_calls") or []
            prompt_eval = raw.get("prompt_eval_count", 0) or 0
            eval_count = raw.get("eval_count", 0) or 0
        else:
            message = getattr(raw, "message", None)
            content = getattr(message, "content", "") or ""
            raw_tool_calls = getattr(message, "tool_calls", None) or []
            prompt_eval = getattr(raw, "prompt_eval_count", 0) or 0
            eval_count = getattr(raw, "eval_count", 0) or 0

        tool_calls: list[ToolCall] = []
        for i, tc in enumerate(raw_tool_calls):
            fn = tc.get("function", {}) if isinstance(tc, dict) else getattr(tc, "function", {})
            args = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", None)
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError as exc:
                    raise LLMInvalidResponseError(f"Ollama returned non-JSON tool arguments: {args!r}") from exc
            elif args is None:
                args = {}
            tool_calls.append(
                ToolCall(
                    id=str(i),
                    name=(fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", "")),
                    arguments=dict(args),
                )
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(input_tokens=prompt_eval, output_tokens=eval_count),
            stop_reason=None,
            raw=raw,
        )
