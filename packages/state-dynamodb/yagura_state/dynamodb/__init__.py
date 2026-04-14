"""DynamoDBStateStore — serverless/AWS-native Yagura StateStore.

Features:
  - Pay-per-request billing (no capacity planning).
  - Auto table creation with session_id as the partition key.
  - Optional TTL attribute (`expire_at`) for automatic cleanup.
  - GSI on user_id for list_sessions(user_id).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from yagura.errors import SessionNotFoundError
from yagura.plan import Plan, PlanState, PlanStep, StepStatus
from yagura.safety.reliability import ReliabilityLevel
from yagura.safety.rules import DangerLevel
from yagura.session.manager import Session, SessionState
from yagura.session.store import StateStore
from yagura.tools.tool import ToolResult


class DynamoDBStateStore(StateStore):
    def __init__(
        self,
        table_name: str = "yagura-sessions",
        region: str | None = None,
        ttl_seconds: int | None = 86400 * 7,
    ) -> None:
        try:
            import aioboto3  # type: ignore
        except ImportError as exc:
            raise ImportError("yagura-state-dynamodb requires 'aioboto3'") from exc
        self.table_name = table_name
        self.region = region
        self.ttl_seconds = ttl_seconds
        self._session_boto = aioboto3.Session()
        self._ensured = False

    async def _ensure_table(self) -> None:
        if self._ensured:
            return
        import boto3  # type: ignore

        client = boto3.client("dynamodb", region_name=self.region)
        try:
            client.describe_table(TableName=self.table_name)
        except client.exceptions.ResourceNotFoundException:
            client.create_table(
                TableName=self.table_name,
                AttributeDefinitions=[
                    {"AttributeName": "id", "AttributeType": "S"},
                    {"AttributeName": "user_id", "AttributeType": "S"},
                ],
                KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "user_id-index",
                        "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            waiter = client.get_waiter("table_exists")
            waiter.wait(TableName=self.table_name)
            if self.ttl_seconds is not None:
                client.update_time_to_live(
                    TableName=self.table_name,
                    TimeToLiveSpecification={"AttributeName": "expire_at", "Enabled": True},
                )
        self._ensured = True

    async def save_session(self, session: Session) -> None:
        await self._ensure_table()
        async with self._session_boto.resource("dynamodb", region_name=self.region) as ddb:
            table = await ddb.Table(self.table_name)
            item = {
                "id": session.id,
                "user_id": session.user_id,
                "state": session.state.value,
                "updated_at": session.updated_at.isoformat(),
                "payload": json.dumps(_session_to_dict(session), ensure_ascii=False, default=str),
            }
            if self.ttl_seconds is not None:
                item["expire_at"] = int(time.time()) + self.ttl_seconds
            await table.put_item(Item=item)

    async def load_session(self, session_id: str) -> Session:
        await self._ensure_table()
        async with self._session_boto.resource("dynamodb", region_name=self.region) as ddb:
            table = await ddb.Table(self.table_name)
            response = await table.get_item(Key={"id": session_id})
        item = response.get("Item")
        if item is None:
            raise SessionNotFoundError(f"Session '{session_id}' not found")
        return _dict_to_session(json.loads(item["payload"]))

    async def delete_session(self, session_id: str) -> None:
        await self._ensure_table()
        async with self._session_boto.resource("dynamodb", region_name=self.region) as ddb:
            table = await ddb.Table(self.table_name)
            await table.delete_item(Key={"id": session_id})

    async def list_sessions(self, user_id: str | None = None) -> list[Session]:
        await self._ensure_table()
        async with self._session_boto.resource("dynamodb", region_name=self.region) as ddb:
            table = await ddb.Table(self.table_name)
            if user_id is None:
                response = await table.scan()
            else:
                response = await table.query(
                    IndexName="user_id-index",
                    KeyConditionExpression="user_id = :uid",
                    ExpressionAttributeValues={":uid": user_id},
                )
        return [_dict_to_session(json.loads(item["payload"])) for item in response.get("Items", [])]


# Shared (de)serialization (same shape as other state stores).


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


__all__ = ["DynamoDBStateStore"]
