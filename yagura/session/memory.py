"""InMemoryStateStore — default StateStore for development."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import TYPE_CHECKING

from yagura.errors import SessionNotFoundError
from yagura.session.store import StateStore

if TYPE_CHECKING:
    from yagura.session.manager import Session


class InMemoryStateStore(StateStore):
    """Default StateStore.

    Sessions live in a dict, protected by an asyncio lock. State is lost
    on process restart. Intended for development and testing.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def save_session(self, session: Session) -> None:
        async with self._lock:
            # deepcopy so callers can mutate their copy without corrupting store state.
            self._sessions[session.id] = deepcopy(session)

    async def load_session(self, session_id: str) -> Session:
        async with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(f"Session '{session_id}' not found")
            return deepcopy(self._sessions[session_id])

    async def delete_session(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def list_sessions(self, user_id: str | None = None) -> list[Session]:
        async with self._lock:
            sessions = [deepcopy(s) for s in self._sessions.values()]
        if user_id is None:
            return sessions
        return [s for s in sessions if s.user_id == user_id]

    async def create_session_atomic(
        self,
        session: Session,
        max_active_for_user: int,
    ) -> None:
        """Atomic insert: the count check + insert happen under a single lock."""
        from yagura.errors import ConcurrentPlanError
        from yagura.session.manager import SessionState, _has_live_plan

        async with self._lock:
            active = [
                s
                for s in self._sessions.values()
                if s.user_id == session.user_id and s.state is SessionState.ACTIVE and _has_live_plan(s)
            ]
            if len(active) >= max_active_for_user:
                raise ConcurrentPlanError(
                    f"User '{session.user_id}' already has {len(active)} active plan(s); "
                    f"max_concurrent_sessions={max_active_for_user}"
                )
            self._sessions[session.id] = deepcopy(session)
