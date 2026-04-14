"""StreamLogger — writes JSON lines to any text stream (stdout, stderr, etc.)."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import IO, Any

from yagura.logging.logger import (
    AssessmentLog,
    AuditLogger,
    OperationLog,
    PlanLog,
)


class StreamLogger(AuditLogger):
    """Writes audit records as JSON lines to an arbitrary text stream."""

    def __init__(self, stream: IO[str] | None = None) -> None:
        self.stream = stream or sys.stdout
        self._lock = asyncio.Lock()

    async def log_operation(self, entry: OperationLog) -> None:
        await self._write("operation", entry)

    async def log_assessment(self, entry: AssessmentLog) -> None:
        await self._write("assessment", entry)

    async def log_plan(self, entry: PlanLog) -> None:
        await self._write("plan", entry)

    async def _write(self, kind: str, entry: object) -> None:
        record = {"kind": kind, **_serialize(entry)}
        line = json.dumps(record, ensure_ascii=False, default=_default_encoder) + "\n"
        async with self._lock:
            self.stream.write(line)
            self.stream.flush()


def _serialize(obj: Any) -> dict[str, Any]:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return obj
    return {"value": obj}


def _default_encoder(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value if isinstance(obj.value, (str, int, float, bool)) else obj.name
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
