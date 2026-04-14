"""ToolRegistry: in-memory registry for Tool definitions and handlers."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from yagura.errors import (
    DuplicateToolError,
    HandlerAlreadyBoundError,
    ToolNotFoundError,
)
from yagura.safety.reliability import ReliabilityLevel
from yagura.safety.rules import DangerLevel
from yagura.tools.tool import ExecutionTarget, Tool


class ToolRegistry:
    """Registers and looks up Tools by name.

    Supports two registration modes:
      1. Code-defined: `register(Tool(...))` — schema + handler together.
      2. Schema-defined: `load_from_schema(json)` then `register_handler(name, fn)`.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise DuplicateToolError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool '{name}' not found")
        del self._tools[name]

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool '{name}' not found")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_all(self) -> list[Tool]:
        return list(self._tools.values())

    def list_by_tag(self, tag: str) -> list[Tool]:
        return [t for t in self._tools.values() if tag in (t.tags or [])]

    def get_schemas(self) -> list[dict[str, Any]]:
        """Return all registered tools as JSON schemas for LLM consumption."""
        return [t.to_schema() for t in self._tools.values()]

    def load_from_schema(self, source: str | Path | dict[str, Any] | list[dict[str, Any]]) -> None:
        """Load tool definitions (without handlers) from a file path, dict, or list of dicts.

        Handlers must be bound separately via `register_handler`.
        """
        definitions = self._coerce_to_definitions(source)
        for definition in definitions:
            tool = self._definition_to_tool(definition)
            self.register(tool)

    def register_handler(self, tool_name: str, handler: Callable[..., Any]) -> None:
        """Bind a handler to a previously loaded tool schema."""
        tool = self.get(tool_name)
        if tool.handler is not None:
            raise HandlerAlreadyBoundError(f"Tool '{tool_name}' already has a handler bound")
        tool.handler = handler

    # --- Internal helpers --------------------------------------------------

    @staticmethod
    def _coerce_to_definitions(
        source: str | Path | dict[str, Any] | list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if isinstance(source, (str, Path)):
            text = Path(source).read_text(encoding="utf-8")
            data = json.loads(text)
        else:
            data = source
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        raise ValueError(f"Unsupported tool definition source: {type(source).__name__}")

    @staticmethod
    def _definition_to_tool(definition: dict[str, Any]) -> Tool:
        name = definition["name"]
        description = definition["description"]
        # Accept either "parameters" or "input_schema" (Anthropic tool-use style).
        parameters = definition.get("parameters") or definition.get("input_schema") or {}

        danger_level = definition.get("danger_level")
        if isinstance(danger_level, str):
            danger_level = DangerLevel[danger_level.upper()]

        execution_target = definition.get("execution_target", "local")
        if isinstance(execution_target, str):
            execution_target = ExecutionTarget(execution_target)

        reliability = definition.get("default_reliability", "reference")
        if isinstance(reliability, str):
            reliability = ReliabilityLevel(reliability)

        return Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=None,
            danger_level=danger_level,
            execution_target=execution_target,
            tags=list(definition.get("tags") or []),
            default_reliability=reliability,
            requires_llm=bool(definition.get("requires_llm", False)),
        )
