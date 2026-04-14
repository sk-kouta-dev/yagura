"""RedisStateStore — high-throughput, TTL-aware Yagura StateStore."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from yagura.errors import SessionNotFoundError
from yagura.plan import Plan, PlanState, PlanStep, StepStatus
from yagura.safety.reliability import ReliabilityLevel
from yagura.safety.rules import DangerLevel
from yagura.session.manager import Session, SessionState
from yagura.session.store import StateStore
from yagura.tools.tool import ToolResult


class RedisStateStore(StateStore):
    """Redis-backed StateStore.

    Sessions are stored as JSON strings under `{key_prefix}{session_id}`.
    A per-user set at `{key_prefix}users:{user_id}` lets us support
    list_sessions(user_id) without scanning keyspace.
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        key_prefix: str = "yagura:session:",
        ttl_seconds: int | None = 86400,
    ) -> None:
        try:
            import redis.asyncio as aioredis  # type: ignore
        except ImportError as exc:
            raise ImportError("yagura-state-redis requires 'redis>=5.0'") from exc
        self._url = url
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self._client = aioredis.from_url(url, decode_responses=True)

    def _session_key(self, session_id: str) -> str:
        return f"{self.key_prefix}{session_id}"

    def _user_index_key(self, user_id: str) -> str:
        return f"{self.key_prefix}users:{user_id}"

    async def close(self) -> None:
        await self._client.aclose()

    async def save_session(self, session: Session) -> None:
        payload = json.dumps(_session_to_dict(session), ensure_ascii=False, default=str)
        pipe = self._client.pipeline()
        key = self._session_key(session.id)
        if self.ttl_seconds is not None:
            pipe.set(key, payload, ex=self.ttl_seconds)
        else:
            pipe.set(key, payload)
        pipe.sadd(self._user_index_key(session.user_id), session.id)
        await pipe.execute()

    async def load_session(self, session_id: str) -> Session:
        raw = await self._client.get(self._session_key(session_id))
        if raw is None:
            raise SessionNotFoundError(f"Session '{session_id}' not found")
        return _dict_to_session(json.loads(raw))

    async def delete_session(self, session_id: str) -> None:
        raw = await self._client.get(self._session_key(session_id))
        if raw is not None:
            data = json.loads(raw)
            user_id = data.get("user_id")
            if user_id:
                await self._client.srem(self._user_index_key(user_id), session_id)
        await self._client.delete(self._session_key(session_id))

    async def list_sessions(self, user_id: str | None = None) -> list[Session]:
        if user_id is not None:
            session_ids = await self._client.smembers(self._user_index_key(user_id))
        else:
            # Scan by prefix; expensive but acceptable for admin tooling.
            pattern = f"{self.key_prefix}*"
            session_ids = []
            async for key in self._client.scan_iter(pattern):
                if key.startswith(f"{self.key_prefix}users:"):
                    continue
                session_ids.append(key.removeprefix(self.key_prefix))
        sessions: list[Session] = []
        for sid in session_ids:
            raw = await self._client.get(self._session_key(sid))
            if raw:
                sessions.append(_dict_to_session(json.loads(raw)))
        return sessions


# Shared (de)serialization (same shape as PostgresStateStore).


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


def _turn_to_dict(turn) -> dict[str, Any]:
    return {
        "user_input": turn.user_input,
        "plan_id": turn.plan_id,
        "plan_state": turn.plan_state,
        "step_summaries": list(turn.step_summaries),
        "timestamp": turn.timestamp.isoformat(),
    }


def _dict_to_turn(data: dict[str, Any]):
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


__all__ = ["RedisStateStore"]
