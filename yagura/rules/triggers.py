"""Built-in RuleTrigger implementations.

Triggers are async iterables of "fire events". The RuleEngine calls
`start(callback)` to begin delivering events; each event invokes the
callback which generates and executes a plan from the rule's template.
"""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CronCallback = Callable[[dict[str, Any]], Awaitable[None]]


class RuleTrigger(ABC):
    """Abstract event source that fires a rule's plan template."""

    @abstractmethod
    async def start(self, callback: CronCallback) -> None:
        """Begin delivering events. Returns immediately; events arrive via callback."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop delivering events and clean up any background tasks."""


# ---------------------------------------------------------------------------
# CronTrigger — minimal in-process cron implementation.
# ---------------------------------------------------------------------------


class CronTrigger(RuleTrigger):
    """Fires at a cron-scheduled cadence.

    Supports the common 5-field cron expression (minute hour dom month dow)
    with ranges, lists, and steps. Not a full cron substitute — for complex
    schedules, plug in a dedicated scheduler via a custom RuleTrigger.
    """

    def __init__(self, schedule: str, check_interval: float = 30.0) -> None:
        self.schedule = schedule
        self.check_interval = check_interval
        self._task: asyncio.Task[Any] | None = None
        self._stop_event: asyncio.Event | None = None
        self._parsed = _parse_cron(schedule)

    async def start(self, callback: CronCallback) -> None:
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._loop(callback))

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self, callback: CronCallback) -> None:
        assert self._stop_event is not None
        last_minute: tuple[int, int, int, int, int] | None = None
        while not self._stop_event.is_set():
            now = datetime.now(UTC)
            minute_key = (now.year, now.month, now.day, now.hour, now.minute)
            if minute_key != last_minute and _cron_matches(self._parsed, now):
                last_minute = minute_key
                try:
                    await callback({"fired_at": now.isoformat(), "schedule": self.schedule})
                except Exception:  # noqa: BLE001 — trigger loop must not die on callback errors.
                    pass
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.check_interval)
            except TimeoutError:
                continue


_CRON_FIELD = re.compile(r"^(\*|\d+(-\d+)?)(,(\*|\d+(-\d+)?))*(/\d+)?$")


def _parse_cron(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"Cron expression must have 5 fields: {expr!r}")
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    return tuple(_expand(f, lo, hi) for f, (lo, hi) in zip(fields, ranges))  # type: ignore[return-value]


def _expand(field: str, lo: int, hi: int) -> set[int]:
    if field == "*":
        return set(range(lo, hi + 1))
    # Support comma-separated lists, ranges, and /step.
    step = 1
    if "/" in field:
        field, step_str = field.split("/", 1)
        step = int(step_str)
        if field == "*":
            field = f"{lo}-{hi}"
    result: set[int] = set()
    for part in field.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            # Map Sunday=7 → 0 for cron convention when field is the DoW slot.
            start = end = int(part)
            if lo == 0 and hi == 6 and start == 7:
                start = end = 0
        for i in range(start, end + 1, step):
            if lo <= i <= hi:
                result.add(i)
    return result


def _cron_matches(
    parsed: tuple[set[int], set[int], set[int], set[int], set[int]],
    moment: datetime,
) -> bool:
    minute, hour, dom, month, dow = parsed
    return (
        moment.minute in minute
        and moment.hour in hour
        and moment.day in dom
        and moment.month in month
        and (moment.weekday() + 1) % 7 in dow  # Python Monday=0; cron Sunday=0.
    )


# ---------------------------------------------------------------------------
# FileWatchTrigger — polling watcher for create/modify/delete events.
# ---------------------------------------------------------------------------


class FileWatchTrigger(RuleTrigger):
    """Polls a set of paths and fires on create/modify/delete.

    Uses mtime-based polling so it works without OS-specific dependencies.
    Users needing push-based filesystem events should implement a custom
    trigger around watchdog/inotify.
    """

    def __init__(
        self,
        paths: list[str | Path],
        events: list[str] | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.paths = [Path(p) for p in paths]
        self.events = set(events or ["create", "modify", "delete"])
        self.poll_interval = poll_interval
        self._task: asyncio.Task[Any] | None = None
        self._stop_event: asyncio.Event | None = None

    async def start(self, callback: CronCallback) -> None:
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._loop(callback))

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self, callback: CronCallback) -> None:
        assert self._stop_event is not None
        snapshot = self._snapshot()
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
                return
            except TimeoutError:
                pass
            new_snapshot = self._snapshot()
            for path, new_mtime in new_snapshot.items():
                old_mtime = snapshot.get(path)
                if old_mtime is None and "create" in self.events:
                    await self._fire(callback, "create", path)
                elif old_mtime is not None and new_mtime != old_mtime and "modify" in self.events:
                    await self._fire(callback, "modify", path)
            for path in snapshot:
                if path not in new_snapshot and "delete" in self.events:
                    await self._fire(callback, "delete", path)
            snapshot = new_snapshot

    def _snapshot(self) -> dict[Path, float]:
        out: dict[Path, float] = {}
        for root in self.paths:
            if not root.exists():
                continue
            if root.is_file():
                out[root] = root.stat().st_mtime
            else:
                for p in root.rglob("*"):
                    if p.is_file():
                        out[p] = p.stat().st_mtime
        return out

    @staticmethod
    async def _fire(callback: CronCallback, event: str, path: Path) -> None:
        try:
            await callback({"event": event, "path": str(path)})
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# WebhookTrigger — interface-only. Users wire it up to an HTTP server.
# ---------------------------------------------------------------------------


class WebhookTrigger(RuleTrigger):
    """Declares a webhook path + method the rule listens on.

    The framework doesn't ship an HTTP server; integrators wire this
    trigger into their server of choice (FastAPI, Starlette, etc.) and
    call `fire(payload)` when the endpoint is hit.
    """

    def __init__(self, path: str, method: str = "POST") -> None:
        self.path = path
        self.method = method.upper()
        self._callback: CronCallback | None = None

    async def start(self, callback: CronCallback) -> None:
        self._callback = callback

    async def stop(self) -> None:
        self._callback = None

    async def fire(self, payload: dict[str, Any]) -> None:
        """Invoked by the HTTP handler on a real request."""
        if self._callback is not None:
            await self._callback(payload)
