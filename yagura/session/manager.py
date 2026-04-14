"""Session and SessionManager.

A Session groups a single user's current plan, intermediate context, and
state metadata. One active plan per user is enforced to prevent self-
conflicting concurrent operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from yagura.errors import SessionNotFoundError
from yagura.plan import Plan, PlanState
from yagura.session.store import StateStore


class SessionState(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    EXPIRED = "expired"


_TERMINAL_PLAN_STATES = {
    PlanState.COMPLETED,
    PlanState.FAILED,
    PlanState.CANCELLED,
}


@dataclass
class ConversationTurn:
    """One round-trip in a session: user prompt + the plan's final state summary."""

    user_input: str
    plan_id: str
    plan_state: str  # Terminal state value: "completed" / "failed" / "cancelled".
    step_summaries: list[str] = field(default_factory=list)  # 1-line per executed step.
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Session:
    id: str
    user_id: str = "default"
    plan: Plan | None = None
    context: dict[str, Any] = field(default_factory=dict)
    # Conversation history across turns (distinct from the current Plan).
    # Consumed by the Planner to give the LLM continuity — "use the file from
    # step 2 above" etc. Older turns are truncated by `history_max_turns` on
    # Agent to keep token usage bounded.
    history: list[ConversationTurn] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: SessionState = SessionState.ACTIVE


class SessionManager:
    """Creates, loads, and persists Sessions via a StateStore.

    Enforces the "single active plan per user" invariant. Delegates all
    persistence to the configured StateStore.
    """

    def __init__(self, state_store: StateStore, max_concurrent_sessions: int = 1) -> None:
        self.state_store = state_store
        self.max_concurrent_sessions = max_concurrent_sessions

    async def create(self, user_id: str = "default") -> Session:
        session = Session(id=str(uuid4()), user_id=user_id)
        # Delegate to the state store so backends with transactional support
        # (Postgres, DynamoDB conditional writes, Redis WATCH/MULTI) can
        # enforce the cap atomically and avoid race conditions.
        await self.state_store.create_session_atomic(session, max_active_for_user=self.max_concurrent_sessions)
        return session

    async def get_or_create(self, session_id: str | None, user_id: str = "default") -> Session:
        if session_id:
            try:
                return await self.state_store.load_session(session_id)
            except SessionNotFoundError:
                pass
        return await self.create(user_id)

    async def save(self, session: Session) -> None:
        session.updated_at = datetime.now(UTC)
        # Auto-advance session state from plan state.
        if session.plan is not None and session.plan.state in _TERMINAL_PLAN_STATES:
            session.state = SessionState.COMPLETED
        await self.state_store.save_session(session)

    async def load(self, session_id: str) -> Session:
        return await self.state_store.load_session(session_id)

    async def delete(self, session_id: str) -> None:
        await self.state_store.delete_session(session_id)

    async def list_for_user(self, user_id: str | None = None) -> list[Session]:
        return await self.state_store.list_sessions(user_id)


def _has_live_plan(session: Session) -> bool:
    if session.plan is None:
        return False
    return session.plan.state not in _TERMINAL_PLAN_STATES
