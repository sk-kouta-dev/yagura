"""ToolRegistry tests — P0."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yagura.errors import (
    DuplicateToolError,
    HandlerAlreadyBoundError,
    ToolNotFoundError,
)
from yagura.safety.rules import DangerLevel
from yagura.tools.registry import ToolRegistry
from yagura.tools.tool import Tool


def _tool(name: str, *, tags: list[str] | None = None) -> Tool:
    return Tool(
        name=name,
        description=f"{name} tool",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: None,
        tags=tags or [],
    )


# --- Basic registration ----------------------------------------------------


def test_register_and_get() -> None:
    reg = ToolRegistry()
    t = _tool("list_files")
    reg.register(t)
    assert reg.get("list_files") is t
    assert reg.has("list_files")


def test_register_duplicate_raises() -> None:
    reg = ToolRegistry()
    reg.register(_tool("list_files"))
    with pytest.raises(DuplicateToolError):
        reg.register(_tool("list_files"))


def test_get_missing_raises() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        reg.get("nope")


def test_unregister_removes_tool() -> None:
    reg = ToolRegistry()
    reg.register(_tool("list_files"))
    reg.unregister("list_files")
    assert not reg.has("list_files")


def test_unregister_missing_raises() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        reg.unregister("missing")


def test_list_by_tag() -> None:
    reg = ToolRegistry()
    reg.register(_tool("a", tags=["fs", "read"]))
    reg.register(_tool("b", tags=["fs"]))
    reg.register(_tool("c", tags=["email"]))
    names = {t.name for t in reg.list_by_tag("fs")}
    assert names == {"a", "b"}


def test_get_schemas() -> None:
    reg = ToolRegistry()
    reg.register(_tool("list_files"))
    schemas = reg.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "list_files"
    assert "input_schema" in schemas[0]


# --- Schema loading --------------------------------------------------------


def test_load_from_schema_dict() -> None:
    reg = ToolRegistry()
    reg.load_from_schema(
        {
            "name": "list_files",
            "description": "list them",
            "parameters": {"type": "object", "properties": {}, "required": []},
            "danger_level": "read",
        }
    )
    t = reg.get("list_files")
    assert t.danger_level is DangerLevel.READ
    assert t.handler is None


def test_load_from_schema_file(tmp_path: Path) -> None:
    payload = [
        {
            "name": "list_files",
            "description": "list",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "copy_file",
            "description": "copy",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    ]
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    reg = ToolRegistry()
    reg.load_from_schema(path)
    assert reg.has("list_files")
    assert reg.has("copy_file")


def test_register_handler_binds() -> None:
    reg = ToolRegistry()
    reg.load_from_schema(
        {
            "name": "list_files",
            "description": "list",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    )

    def handler() -> list[str]:
        return ["a"]

    reg.register_handler("list_files", handler)
    assert reg.get("list_files").handler is handler


def test_register_handler_rejects_double_bind() -> None:
    reg = ToolRegistry()
    reg.register(_tool("list_files"))
    with pytest.raises(HandlerAlreadyBoundError):
        reg.register_handler("list_files", lambda: None)
