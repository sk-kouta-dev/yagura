"""Directory operations: list, create, delete."""

from __future__ import annotations

import shutil
from pathlib import Path

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _directory_list(path: str, recursive: bool = False) -> ToolResult:
    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, error=f"Directory not found: {path}")
    if not p.is_dir():
        return ToolResult(success=False, error=f"Not a directory: {path}")
    if recursive:
        entries = [
            {"path": str(e), "type": "file" if e.is_file() else "dir", "size": e.stat().st_size if e.is_file() else None}
            for e in p.rglob("*")
        ]
    else:
        entries = [
            {"path": str(e), "type": "file" if e.is_file() else "dir", "size": e.stat().st_size if e.is_file() else None}
            for e in p.iterdir()
        ]
    return ToolResult(success=True, data={"path": str(p), "entries": entries, "count": len(entries)})


def _directory_create(path: str, parents: bool = True) -> ToolResult:
    p = Path(path)
    if p.exists():
        if p.is_dir():
            return ToolResult(success=True, data={"path": str(p), "created": False, "reason": "already_exists"})
        return ToolResult(success=False, error=f"Path exists and is not a directory: {path}")
    p.mkdir(parents=parents, exist_ok=True)
    return ToolResult(success=True, data={"path": str(p), "created": True})


def _directory_delete(path: str, recursive: bool = False) -> ToolResult:
    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, error=f"Directory not found: {path}")
    if not p.is_dir():
        return ToolResult(success=False, error=f"Not a directory: {path}")
    try:
        if recursive:
            shutil.rmtree(p)
        else:
            p.rmdir()
    except OSError as exc:
        return ToolResult(success=False, error=f"Delete failed: {exc}")
    return ToolResult(success=True, data={"path": str(p), "recursive": recursive, "deleted": True})


directory_list = Tool(
    name="directory_list",
    description="List the contents of a directory.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "recursive": {"type": "boolean", "default": False},
        },
        "required": ["path"],
    },
    handler=_directory_list,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["common", "directory"],
)

directory_create = Tool(
    name="directory_create",
    description="Create a directory (and parents, by default).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "parents": {"type": "boolean", "default": True},
        },
        "required": ["path"],
    },
    handler=_directory_create,
    danger_level=DangerLevel.MODIFY,
    tags=["common", "directory"],
)

directory_delete = Tool(
    name="directory_delete",
    description="Delete a directory. Set recursive=True to remove non-empty directories.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "recursive": {"type": "boolean", "default": False},
        },
        "required": ["path"],
    },
    handler=_directory_delete,
    danger_level=DangerLevel.DESTRUCTIVE,
    tags=["common", "directory"],
)


tools: list[Tool] = [directory_list, directory_create, directory_delete]
