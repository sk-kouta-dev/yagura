"""ToolExecutor and RemoteExecutor / ClientExecutor interfaces.

ToolExecutor dispatches a Tool invocation to the correct target:
  - LOCAL target: calls the handler directly (sync or async).
  - REMOTE target: delegates to the configured RemoteExecutor.
  - CLIENT target: delegates to the configured ClientExecutor.

For Dynamic Tools (requires_llm=True), the executor LLM is consulted
before the handler to generate or transform parameters.
"""

from __future__ import annotations

import asyncio
import inspect
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from yagura.errors import ToolExecutionError
from yagura.tools.tool import ExecutionTarget, Tool, ToolResult

if TYPE_CHECKING:
    from yagura.llm.provider import LLMProvider


class RemoteExecutor(ABC):
    """Abstract executor for tools whose ExecutionTarget is REMOTE."""

    @abstractmethod
    async def execute(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        """Execute the named tool with params on the remote backend."""


class ClientExecutor(ABC):
    """Abstract executor for tools whose ExecutionTarget is CLIENT."""

    @abstractmethod
    async def execute(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        """Execute the named tool with params on the client device."""


class ToolExecutor:
    """Orchestrates tool invocation.

    Selects local / remote / client dispatch based on the Tool's
    `execution_target`. Coerces arbitrary handler return values into
    a `ToolResult`, preserving the tool's default reliability if the
    result did not specify one.
    """

    def __init__(
        self,
        remote_executor: RemoteExecutor | None = None,
        client_executor: ClientExecutor | None = None,
    ) -> None:
        self.remote_executor = remote_executor
        self.client_executor = client_executor

    async def execute(
        self,
        tool: Tool,
        params: dict[str, Any],
        executor_llm: LLMProvider | None = None,
    ) -> ToolResult:
        """Execute a tool and return a ToolResult.

        For Dynamic Tools (`requires_llm=True`), the caller is responsible
        for having already transformed `params` via the executor LLM. This
        method performs the final handler dispatch.
        """
        try:
            if tool.execution_target is ExecutionTarget.REMOTE:
                result = await self._execute_remote(tool, params)
            elif tool.execution_target is ExecutionTarget.CLIENT:
                result = await self._execute_client(tool, params)
            else:
                result = await self._execute_local(tool, params)
        except ToolExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 — we want to wrap anything the handler raises.
            raise ToolExecutionError(f"Tool '{tool.name}' raised {type(exc).__name__}: {exc}") from exc

        # Apply the Tool's default reliability if the ToolResult did not override it.
        if result.reliability is None:
            result.reliability = tool.default_reliability
        return result

    # --- Dispatchers ------------------------------------------------------

    async def _execute_local(self, tool: Tool, params: dict[str, Any]) -> ToolResult:
        if tool.handler is None:
            raise ToolExecutionError(f"Tool '{tool.name}' has no handler bound")
        handler = tool.handler
        if inspect.iscoroutinefunction(handler):
            raw = await handler(**params)
        else:
            # Run sync handler in default executor to avoid blocking the loop.
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(None, lambda: handler(**params))
        return self._coerce_result(raw)

    async def _execute_remote(self, tool: Tool, params: dict[str, Any]) -> ToolResult:
        if self.remote_executor is None:
            raise ToolExecutionError(f"Tool '{tool.name}' targets REMOTE but no RemoteExecutor is configured")
        return await self.remote_executor.execute(tool.name, params)

    async def _execute_client(self, tool: Tool, params: dict[str, Any]) -> ToolResult:
        if self.client_executor is None:
            raise ToolExecutionError(f"Tool '{tool.name}' targets CLIENT but no ClientExecutor is configured")
        return await self.client_executor.execute(tool.name, params)

    # --- Result coercion --------------------------------------------------

    @staticmethod
    def _coerce_result(raw: Any) -> ToolResult:
        """Turn an arbitrary handler return value into a ToolResult."""
        if isinstance(raw, ToolResult):
            return raw
        return ToolResult(success=True, data=raw)
