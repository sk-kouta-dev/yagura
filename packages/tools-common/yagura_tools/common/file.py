"""File operations: read, write, delete, copy, move."""

from __future__ import annotations

import shutil
from pathlib import Path

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _file_read(path: str, encoding: str = "utf-8") -> ToolResult:
    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, error=f"File not found: {path}")
    if not p.is_file():
        return ToolResult(success=False, error=f"Not a file: {path}")
    try:
        return ToolResult(
            success=True,
            data={"path": str(p), "content": p.read_text(encoding=encoding)},
            reliability=ReliabilityLevel.AUTHORITATIVE,
        )
    except UnicodeDecodeError as exc:
        return ToolResult(success=False, error=f"Decode failed: {exc}")


def _file_write(path: str, content: str, overwrite: bool = True, encoding: str = "utf-8") -> ToolResult:
    p = Path(path)
    if p.exists() and not overwrite:
        return ToolResult(success=False, error=f"File already exists and overwrite=False: {path}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding)
    return ToolResult(success=True, data={"path": str(p), "bytes_written": len(content.encode(encoding))})


def _file_delete(path: str) -> ToolResult:
    p = Path(path)
    if not p.exists():
        return ToolResult(success=False, error=f"File not found: {path}")
    if not p.is_file():
        return ToolResult(success=False, error=f"Not a file (use directory_delete): {path}")
    p.unlink()
    return ToolResult(success=True, data={"path": str(p), "deleted": True})


def _file_copy(source: str, destination: str) -> ToolResult:
    src, dst = Path(source), Path(destination)
    if not src.exists():
        return ToolResult(success=False, error=f"Source not found: {source}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return ToolResult(success=True, data={"source": str(src), "destination": str(dst)})


def _file_move(source: str, destination: str) -> ToolResult:
    src, dst = Path(source), Path(destination)
    if not src.exists():
        return ToolResult(success=False, error=f"Source not found: {source}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return ToolResult(success=True, data={"source": str(src), "destination": str(dst)})


file_read = Tool(
    name="file_read",
    description="Read a file's contents as text.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file."},
            "encoding": {"type": "string", "description": "Text encoding.", "default": "utf-8"},
        },
        "required": ["path"],
    },
    handler=_file_read,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["common", "file"],
)

file_write = Tool(
    name="file_write",
    description="Write text content to a file. Creates parent directories if needed.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file."},
            "content": {"type": "string", "description": "Text content to write."},
            "overwrite": {"type": "boolean", "description": "Overwrite existing file.", "default": True},
            "encoding": {"type": "string", "description": "Text encoding.", "default": "utf-8"},
        },
        "required": ["path", "content"],
    },
    handler=_file_write,
    danger_level=DangerLevel.MODIFY,
    tags=["common", "file"],
)

file_delete = Tool(
    name="file_delete",
    description="Delete a file permanently.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file."},
        },
        "required": ["path"],
    },
    handler=_file_delete,
    danger_level=DangerLevel.DESTRUCTIVE,
    tags=["common", "file"],
)

file_copy = Tool(
    name="file_copy",
    description="Copy a file to a new location.",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "destination"],
    },
    handler=_file_copy,
    danger_level=DangerLevel.MODIFY,
    tags=["common", "file"],
)

file_move = Tool(
    name="file_move",
    description="Move or rename a file.",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "destination"],
    },
    handler=_file_move,
    danger_level=DangerLevel.MODIFY,
    tags=["common", "file"],
)


tools: list[Tool] = [file_read, file_write, file_delete, file_copy, file_move]
