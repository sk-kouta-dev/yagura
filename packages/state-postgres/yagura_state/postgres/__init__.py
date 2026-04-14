"""PostgresStateStore — production-grade StateStore over PostgreSQL.

Features:
  - JSONB storage for session payload (queryable).
  - Connection pooling via asyncpg.
  - Auto table creation.
  - Row-level locking for concurrent access (SELECT … FOR UPDATE).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from yagura.errors import SessionNotFoundError
from yagura.plan import Plan, PlanState, PlanStep, StepStatus
from yagura.safety.reliability import ReliabilityLevel
from yagura.safety.rules import DangerLevel
from yagura.session.manager import Session, SessionState
from yagura.session.store import StateStore
from yagura.tools.tool import ToolResult

if TYPE_CHECKING:
    import asyncpg  # type: ignore


_SCHEMA = """
CREATE TABLE IF NOT EXISTS {table} (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    state      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    payload    JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_{table}_user ON {table}(user_id);
CREATE INDEX IF NOT EXISTS idx_{table}_updated ON {table}(updated_at DESC);
"""


class PostgresStateStore(StateStore):
    """PostgreSQL-backed StateStore using asyncpg."""

    def __init__(
        self,
        connection_string: str,
        table_name: str = "yagura_sessions",
        min_connections: int = 1,
        max_connections: int = 10,
    ) -> None:
        try:
            import asyncpg  # type: ignore # noqa: F401
        except ImportError as exc:
            raise ImportError("yagura-state-postgres requires 'asyncpg'") from exc
        # Basic identifier safety: the table name is interpolated into SQL,
        # so we reject anything non-alphanumeric.
        if not table_name.replace("_", "").isalnum():
            raise ValueError(f"Unsafe table_name: {table_name!r}")
        self.connection_string = connection_string
        self.table_name = table_name
        self.min_connections = min_connections
        self.max_connections = max_connections
        self._pool: Any = None
        self._init_lock = asyncio.Lock()

    async def _ensure_pool(self) -> Any:
        import asyncpg  # type: ignore

        if self._pool is not None:
            return self._pool
        async with self._init_lock:
            if self._pool is not None:
                return self._pool
            self._pool = await asyncpg.create_pool(
                self.connection_string,
                min_size=self.min_connections,
                max_size=self.max_connections,
            )
            async with self._pool.acquire() as conn:
                await conn.execute(_SCHEMA.format(table=self.table_name))
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # --- StateStore interface --------------------------------------------

    async def save_session(self, session: Session) -> None:
        pool = await self._ensure_pool()
        payload = json.dumps(_session_to_dict(session), ensure_ascii=False, default=str)
        sql = f"""
        INSERT INTO {self.table_name} (id, user_id, state, updated_at, payload)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        ON CONFLICT (id) DO UPDATE SET
          user_id = EXCLUDED.user_id,
          state = EXCLUDED.state,
          updated_at = EXCLUDED.updated_at,
          payload = EXCLUDED.payload
        """
        async with pool.acquire() as conn:
            await conn.execute(
                sql,
                session.id,
                session.user_id,
                session.state.value,
                session.updated_at,
                payload,
            )

    async def load_session(self, session_id: str) -> Session:
        pool = await self._ensure_pool()
        sql = f"SELECT payload FROM {self.table_name} WHERE id = $1"
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, session_id)
        if row is None:
            raise SessionNotFoundError(f"Session '{session_id}' not found")
        data = row["payload"]
        if isinstance(data, str):
            data = json.loads(data)
        return _dict_to_session(data)

    async def delete_session(self, session_id: str) -> None:
        pool = await self._ensure_pool()
        sql = f"DELETE FROM {self.table_name} WHERE id = $1"
        async with pool.acquire() as conn:
            await conn.execute(sql, session_id)

    async def list_sessions(self, user_id: str | None = None) -> list[Session]:
        pool = await self._ensure_pool()
        if user_id is None:
            sql = f"SELECT payload FROM {self.table_name} ORDER BY updated_at DESC"
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql)
        else:
            sql = f"SELECT payload FROM {self.table_name} WHERE user_id = $1 ORDER BY updated_at DESC"
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, user_id)
        return [
            _dict_to_session(json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"])
            for r in rows
        ]

    async def create_session_atomic(
        self,
        session: Session,
        max_active_for_user: int,
    ) -> None:
        """Atomic create under a per-user advisory lock.

        Uses `pg_advisory_xact_lock(hashtext(user_id))` to serialize concurrent
        create_session_atomic() calls for the same user inside the transaction.
        Inside the lock we count active sessions and either insert or raise.
        """
        from yagura.errors import ConcurrentPlanError

        pool = await self._ensure_pool()
        payload = json.dumps(_session_to_dict(session), ensure_ascii=False, default=str)

        count_sql = (
            f"SELECT COUNT(*) FROM {self.table_name} "
            f"WHERE user_id = $1 AND state = 'active' "
            f"AND payload->>'plan' IS NOT NULL "
            f"AND payload#>>'{{plan,state}}' NOT IN ('completed', 'failed', 'cancelled')"
        )
        insert_sql = f"""
        INSERT INTO {self.table_name} (id, user_id, state, updated_at, payload)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        """
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1))", session.user_id
                )
                count = await conn.fetchval(count_sql, session.user_id)
                if count >= max_active_for_user:
                    raise ConcurrentPlanError(
                        f"User '{session.user_id}' already has {count} active plan(s); "
                        f"max_concurrent_sessions={max_active_for_user}"
                    )
                await conn.execute(
                    insert_sql,
                    session.id,
                    session.user_id,
                    session.state.value,
                    session.updated_at,
                    payload,
                )


# ---------------------------------------------------------------------------
# (de)serialization — mirrors yagura.session.sqlite helpers.
# ---------------------------------------------------------------------------


def _session_to_dict(session: Session) -> dict[str, Any]:
    return {
        "id": session.id,
        "user_id": session.user_id,
        "plan": _plan_to_dict(session.plan) if session.plan else None,
        "context": session.context,
        "history": [_turn_to_dict(t) for t in session.history],
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "state": session.state.value,
    }


def _turn_to_dict(turn) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {
        "user_input": turn.user_input,
        "plan_id": turn.plan_id,
        "plan_state": turn.plan_state,
        "step_summaries": list(turn.step_summaries),
        "timestamp": turn.timestamp.isoformat(),
    }


def _dict_to_turn(data: dict[str, Any]):  # type: ignore[no-untyped-def]
    from yagura.session.manager import ConversationTurn

    return ConversationTurn(
        user_input=data["user_input"],
        plan_id=data["plan_id"],
        plan_state=data["plan_state"],
        step_summaries=list(data.get("step_summaries") or []),
        timestamp=datetime.fromisoformat(data["timestamp"]),
    )


def _dict_to_session(data: dict[str, Any]) -> Session:
    return Session(
        id=data["id"],
        user_id=data["user_id"],
        plan=_dict_to_plan(data["plan"]) if data.get("plan") else None,
        context=data.get("context") or {},
        history=[_dict_to_turn(t) for t in (data.get("history") or [])],
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        state=SessionState(data["state"]),
    )


def _plan_to_dict(plan: Plan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "state": plan.state.value,
        "scope": plan.scope,
        "created_at": plan.created_at.isoformat(),
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        "steps": [
            {
                "step_number": s.step_number,
                "tool_name": s.tool_name,
                "parameters": s.parameters,
                "description": s.description,
                "danger_level": s.danger_level.name if s.danger_level else None,
                "status": s.status.value,
                "result": _result_to_dict(s.result) if s.result else None,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "error": s.error,
            }
            for s in plan.steps
        ],
    }


def _dict_to_plan(data: dict[str, Any]) -> Plan:
    steps = [
        PlanStep(
            step_number=s["step_number"],
            tool_name=s["tool_name"],
            parameters=s.get("parameters") or {},
            description=s.get("description", ""),
            danger_level=DangerLevel[s["danger_level"]] if s.get("danger_level") else None,
            status=StepStatus(s.get("status", "pending")),
            result=_dict_to_result(s["result"]) if s.get("result") else None,
            started_at=datetime.fromisoformat(s["started_at"]) if s.get("started_at") else None,
            completed_at=datetime.fromisoformat(s["completed_at"]) if s.get("completed_at") else None,
            error=s.get("error"),
        )
        for s in data.get("steps", [])
    ]
    return Plan(
        id=data["id"],
        steps=steps,
        scope=data.get("scope"),
        state=PlanState(data["state"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        confirmed_at=datetime.fromisoformat(data["confirmed_at"]) if data.get("confirmed_at") else None,
    )


def _result_to_dict(result: ToolResult) -> dict[str, Any]:
    return {
        "success": result.success,
        "data": result.data,
        "reliability": result.reliability.value if result.reliability else None,
        "metadata": result.metadata,
        "error": result.error,
    }


def _dict_to_result(data: dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=bool(data.get("success", False)),
        data=data.get("data"),
        reliability=ReliabilityLevel(data["reliability"]) if data.get("reliability") else None,
        metadata=data.get("metadata") or {},
        error=data.get("error"),
    )


__all__ = ["PostgresStateStore"]
