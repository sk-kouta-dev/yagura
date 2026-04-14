"""Optimistic resource locking for multi-session concurrency.

When multiple sessions can run concurrently, shared resources (files,
DB rows, documents) are guarded by content hashes. On write, the hash
is compared to what was recorded at read time; a mismatch halts the
plan and notifies the user.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from yagura.errors import ResourceConflictError


@dataclass
class ResourceLock:
    resource_id: str
    session_id: str
    hash: str
    timestamp: datetime


class ConflictDetector:
    """In-memory tracker of resource read-hashes per session."""

    def __init__(self) -> None:
        self._reads: dict[str, ResourceLock] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def hash_content(content: Any) -> str:
        if isinstance(content, bytes):
            data = content
        elif isinstance(content, str):
            data = content.encode("utf-8")
        else:
            import json

            data = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    async def record_read(self, session_id: str, resource_id: str, content: Any) -> ResourceLock:
        lock = ResourceLock(
            resource_id=resource_id,
            session_id=session_id,
            hash=self.hash_content(content),
            timestamp=datetime.now(UTC),
        )
        async with self._lock:
            self._reads[resource_id] = lock
        return lock

    async def check_write(
        self,
        session_id: str,
        resource_id: str,
        current_content: Any,
    ) -> None:
        """Raise ResourceConflictError if the resource changed since the last read."""
        async with self._lock:
            prior = self._reads.get(resource_id)
        if prior is None:
            return  # No prior read; nothing to check.
        current_hash = self.hash_content(current_content)
        if current_hash != prior.hash:
            raise ResourceConflictError(
                f"Resource '{resource_id}' was modified by another session "
                f"(prior_session={prior.session_id}, recorded_at={prior.timestamp.isoformat()})"
            )
