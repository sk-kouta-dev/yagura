"""Shared Session ↔ dict serialization used by yagura-state-* backends.

All three state store packages (postgres/redis/dynamodb) would otherwise
duplicate the Plan/Session → dict translation. We keep that logic here
and have each package copy it at build time, or import it from
`yagura.session.sqlite` internals. For clean separation we mirror the
conversion here with the same semantics as yagura.session.sqlite.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from yagura.plan import Plan, PlanState, PlanStep, StepStatus
from yagura.safety.reliability import ReliabilityLevel
from yagura.safety.rules import DangerLevel
from yagura.session.manager import Session, SessionState
from yagura.tools.tool import ToolResult


def session_to_json(session: Session) -> str:
    return json.dumps(session_to_dict(session), ensure_ascii=False, default=str)


def json_to_session(data: str | dict[str, Any]) -> Session:
    if isinstance(data, str):
        data = json.loads(data)
    return dict_to_session(data)


def session_to_dict(session: Session) -> dict[str, Any]:
    return {
        "id": session.id,
        "user_id": session.user_id,
        "plan": plan_to_dict(session.plan) if session.plan else None,
        "context": session.context,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "state": session.state.value,
    }


def dict_to_session(data: dict[str, Any]) -> Session:
    return Session(
        id=data["id"],
        user_id=data["user_id"],
        plan=dict_to_plan(data["plan"]) if data.get("plan") else None,
        context=data.get("context") or {},
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        state=SessionState(data["state"]),
    )


def plan_to_dict(plan: Plan) -> dict[str, Any]:
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
                "result": result_to_dict(s.result) if s.result else None,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "error": s.error,
            }
            for s in plan.steps
        ],
    }


def dict_to_plan(data: dict[str, Any]) -> Plan:
    steps = [
        PlanStep(
            step_number=s["step_number"],
            tool_name=s["tool_name"],
            parameters=s.get("parameters") or {},
            description=s.get("description", ""),
            danger_level=DangerLevel[s["danger_level"]] if s.get("danger_level") else None,
            status=StepStatus(s.get("status", "pending")),
            result=dict_to_result(s["result"]) if s.get("result") else None,
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


def result_to_dict(result: ToolResult) -> dict[str, Any]:
    return {
        "success": result.success,
        "data": result.data,
        "reliability": result.reliability.value if result.reliability else None,
        "metadata": result.metadata,
        "error": result.error,
    }


def dict_to_result(data: dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=bool(data.get("success", False)),
        data=data.get("data"),
        reliability=ReliabilityLevel(data["reliability"]) if data.get("reliability") else None,
        metadata=data.get("metadata") or {},
        error=data.get("error"),
    )
