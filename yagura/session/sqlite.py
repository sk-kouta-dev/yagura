"""SQLiteStateStore — file-backed persistence for single-user production.

Sessions are serialized as JSON blobs keyed by session id. This is
intentionally simple — users wanting richer queries should implement
their own StateStore against Postgres, DynamoDB, etc.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yagura.errors import SessionNotFoundError
from yagura.plan import (
    Plan,
    PlanState,
    PlanStep,
    StepStatus,
)
from yagura.safety.rules import DangerLevel
from yagura.session.store import StateStore
from yagura.tools.tool import ToolResult

if TYPE_CHECKING:
    from yagura.session.manager import Session


class SQLiteStateStore(StateStore):
    """Local SQLite persistence. Thread-safe via a single asyncio lock.

    The store serializes Sessions to JSON; nothing is stored in typed
    columns beyond id, user_id, updated_at, and state for indexing.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS sessions (
        id         TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL,
        state      TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        payload    TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(self._SCHEMA)

    async def save_session(self, session: Session) -> None:
        payload = json.dumps(_session_to_dict(session), ensure_ascii=False, default=str)
        async with self._lock:
            await asyncio.to_thread(self._upsert, session, payload)

    async def load_session(self, session_id: str) -> Session:
        async with self._lock:
            row = await asyncio.to_thread(self._select_one, session_id)
        if row is None:
            raise SessionNotFoundError(f"Session '{session_id}' not found")
        return _dict_to_session(json.loads(row))

    async def delete_session(self, session_id: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._delete, session_id)

    async def list_sessions(self, user_id: str | None = None) -> list[Session]:
        async with self._lock:
            rows = await asyncio.to_thread(self._select_all, user_id)
        return [_dict_to_session(json.loads(r)) for r in rows]

    # --- Synchronous DB ops (run in thread pool) --------------------------

    def _upsert(self, session: Session, payload: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, state, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  user_id=excluded.user_id,
                  state=excluded.state,
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (
                    session.id,
                    session.user_id,
                    session.state.value,
                    session.updated_at.isoformat(),
                    payload,
                ),
            )
            conn.commit()

    def _select_one(self, session_id: str) -> str | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT payload FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row[0] if row else None

    def _delete(self, session_id: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()

    def _select_all(self, user_id: str | None) -> list[str]:
        with sqlite3.connect(self.path) as conn:
            if user_id is None:
                rows = conn.execute("SELECT payload FROM sessions").fetchall()
            else:
                rows = conn.execute("SELECT payload FROM sessions WHERE user_id = ?", (user_id,)).fetchall()
        return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Session / Plan (de)serialization
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
    from yagura.session.manager import Session, SessionState

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
    from yagura.safety.reliability import ReliabilityLevel

    return ToolResult(
        success=bool(data.get("success", False)),
        data=data.get("data"),
        reliability=ReliabilityLevel(data["reliability"]) if data.get("reliability") else None,
        metadata=data.get("metadata") or {},
        error=data.get("error"),
    )
