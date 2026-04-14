"""StateStore ABC."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yagura.session.manager import Session


class StateStore(ABC):
    """Pluggable persistence for Sessions.

    Built-in implementations:
      - InMemoryStateStore (default, development only)
      - SQLiteStateStore (local file persistence)

    Users implement for PostgreSQL, Redis, DynamoDB, etc.
    """

    @abstractmethod
    async def save_session(self, session: Session) -> None:
        """Persist a session (insert or update)."""

    @abstractmethod
    async def load_session(self, session_id: str) -> Session:
        """Load a session by id. Raises SessionNotFoundError if absent."""

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """Remove a session from storage."""

    @abstractmethod
    async def list_sessions(self, user_id: str | None = None) -> list[Session]:
        """List sessions, optionally filtered by user_id."""

    async def create_session_atomic(
        self,
        session: Session,
        max_active_for_user: int,
    ) -> None:
        """Atomically insert a session subject to a per-user active-count cap.

        Default implementation: non-atomic list + save (same behavior as the
        previous SessionManager). Backends with transactional support
        (Postgres, Redis via WATCH/MULTI, DynamoDB conditional writes) should
        override to make this race-free.

        Raises:
            ConcurrentPlanError if inserting would exceed `max_active_for_user`.
        """
        from yagura.errors import ConcurrentPlanError
        from yagura.session.manager import SessionState, _has_live_plan

        existing = await self.list_sessions(session.user_id)
        active = [s for s in existing if s.state is SessionState.ACTIVE and _has_live_plan(s)]
        if len(active) >= max_active_for_user:
            raise ConcurrentPlanError(
                f"User '{session.user_id}' already has {len(active)} active plan(s); "
                f"max_concurrent_sessions={max_active_for_user}"
            )
        await self.save_session(session)
