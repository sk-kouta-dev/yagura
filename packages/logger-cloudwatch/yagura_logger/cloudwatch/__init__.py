"""CloudWatchLogger — forward Yagura audit events to AWS CloudWatch Logs.

Features:
  - Auto log group / log stream creation.
  - JSON-structured log events.
  - Batching within a single invocation (one PutLogEvents per call).
  - Configurable log retention policy.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from time import time
from typing import Any

from yagura.logging.logger import (
    AssessmentLog,
    AuditLogger,
    OperationLog,
    PlanLog,
)


class CloudWatchLogger(AuditLogger):
    def __init__(
        self,
        log_group: str = "/yagura/audit",
        log_stream: str | None = None,
        region: str | None = None,
        retention_days: int | None = 90,
    ) -> None:
        try:
            import boto3  # type: ignore # noqa: F401
        except ImportError as exc:
            raise ImportError("yagura-logger-cloudwatch requires 'boto3'") from exc
        self.log_group = log_group
        self.log_stream = log_stream or f"yagura-{int(time())}"
        self.region = region
        self.retention_days = retention_days
        self._ensured = False
        self._sequence_token: str | None = None
        self._lock = asyncio.Lock()

    def _client(self):
        import boto3  # type: ignore
        return boto3.client("logs", region_name=self.region)

    def _ensure_sync(self) -> None:
        client = self._client()
        try:
            client.create_log_group(logGroupName=self.log_group)
            if self.retention_days:
                client.put_retention_policy(
                    logGroupName=self.log_group,
                    retentionInDays=self.retention_days,
                )
        except client.exceptions.ResourceAlreadyExistsException:
            pass
        try:
            client.create_log_stream(logGroupName=self.log_group, logStreamName=self.log_stream)
        except client.exceptions.ResourceAlreadyExistsException:
            pass

    async def _ensure(self) -> None:
        if self._ensured:
            return
        async with self._lock:
            if self._ensured:
                return
            await asyncio.to_thread(self._ensure_sync)
            self._ensured = True

    async def _put(self, kind: str, entry_dict: dict[str, Any]) -> None:
        await self._ensure()
        message = json.dumps({"kind": kind, **entry_dict}, default=_default)
        event = {"timestamp": int(time() * 1000), "message": message}

        def _send() -> None:
            client = self._client()
            kwargs: dict[str, Any] = {
                "logGroupName": self.log_group,
                "logStreamName": self.log_stream,
                "logEvents": [event],
            }
            if self._sequence_token:
                kwargs["sequenceToken"] = self._sequence_token
            try:
                response = client.put_log_events(**kwargs)
                self._sequence_token = response.get("nextSequenceToken")
            except client.exceptions.InvalidSequenceTokenException as exc:
                # Recover the expected token from the exception and retry once.
                expected = getattr(exc, "response", {}).get("expectedSequenceToken")
                if expected:
                    kwargs["sequenceToken"] = expected
                    response = client.put_log_events(**kwargs)
                    self._sequence_token = response.get("nextSequenceToken")

        await asyncio.to_thread(_send)

    async def log_operation(self, entry: OperationLog) -> None:
        await self._put("operation", _asdict(entry))

    async def log_assessment(self, entry: AssessmentLog) -> None:
        await self._put("assessment", _asdict(entry))

    async def log_plan(self, entry: PlanLog) -> None:
        await self._put("plan", _asdict(entry))


def _asdict(obj: Any) -> dict[str, Any]:
    if is_dataclass(obj):
        return json.loads(json.dumps(asdict(obj), default=_default))
    return json.loads(json.dumps(obj, default=_default))


def _default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value if isinstance(obj.value, (str, int, float, bool)) else obj.name
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


__all__ = ["CloudWatchLogger"]
