"""yagura-starter-enterprise — FastAPI server with WebSocket chat + health checks.

Routes:
    POST /v1/run                      — submit a user prompt, get either a plan
                                        (for confirmation) or a final result.
    POST /v1/confirm/{session_id}     — approve/cancel a pending plan.
    GET  /v1/sessions/{session_id}    — fetch current session state.
    GET  /v1/healthz                  — liveness probe.
    GET  /v1/readyz                   — readiness probe (checks StateStore).
    WS   /v1/ws/{session_id}          — streaming chat channel (reuses /v1/run).

Authentication:
    All routes except /v1/healthz and /v1/readyz require a bearer token
    that the configured `AuthProvider` (OAuth2Provider by default) validates.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

# Monorepo-mode sys.path setup: ensure yagura_tools.* / yagura_state.* /
# yagura_logger.* / yagura_auth.* are importable when running from inside
# the monorepo. No-op when the packages are already pip-installed.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_shared"))
import bootstrap  # noqa: E402 F401

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from yagura import Agent, PlanConfirmation  # noqa: E402
from yagura.auth.provider import AuthRequest  # noqa: E402

from config import build_agent  # noqa: E402

_logger = logging.getLogger("yagura.enterprise")


# ---------------------------------------------------------------------------
# App / lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.agent = build_agent()
    _logger.info("Yagura agent started")
    try:
        yield
    finally:
        # Clean up state store connections, rule engine, etc.
        store = getattr(app.state.agent.config, "state_store", None)
        if hasattr(store, "close"):
            await store.close()


app = FastAPI(title="Yagura Enterprise API", version="0.1.0", lifespan=_lifespan)

_cors_origins = [
    origin.strip()
    for origin in os.environ.get(
        "YAGURA_CORS_ORIGINS",
        "http://localhost:3000,http://localhost:8080",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


_bearer = HTTPBearer(auto_error=True)


async def _current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    agent: Agent = request.app.state.agent
    result = await agent.auth_provider.authenticate(AuthRequest(token=creds.credentials))
    if not result.authenticated or not result.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result.error or "authentication_failed",
        )
    return result.user_id


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    prompt: str
    session_id: str | None = None


class ConfirmRequest(BaseModel):
    approved: bool
    scope: int | None = None


class RunResponse(BaseModel):
    session_id: str
    plan_state: str
    needs_confirmation: bool
    steps: list[dict[str, Any]]
    message: str | None = None


def _serialize_plan(plan) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    return [
        {
            "step_number": s.step_number,
            "description": s.description,
            "tool_name": s.tool_name,
            "danger_level": s.danger_level.name if s.danger_level else None,
            "status": s.status.value,
            "result": _summarize_result(s.result) if s.result else None,
            "error": s.error,
        }
        for s in plan.steps
    ]


def _summarize_result(result) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {
        "success": result.success,
        "data": result.data,
        "reliability": result.reliability.value if result.reliability else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/v1/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/readyz")
async def readyz(request: Request) -> dict[str, Any]:
    agent: Agent = request.app.state.agent
    # Probe the state store with a lightweight list().
    try:
        await agent.session_manager.list_for_user(None)
        return {"status": "ready", "agent": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"state_store_unavailable: {exc!s}",
        )


@app.post("/v1/run", response_model=RunResponse)
async def run(
    request: Request,
    payload: RunRequest,
    user_id: str = Depends(_current_user),
) -> RunResponse:
    agent: Agent = request.app.state.agent
    response = await agent.run(payload.prompt, session_id=payload.session_id, user_id=user_id)
    return RunResponse(
        session_id=response.session.id,
        plan_state=response.plan.state.value,
        needs_confirmation=response.needs_confirmation,
        steps=_serialize_plan(response.plan),
        message=response.message,
    )


@app.post("/v1/confirm/{session_id}", response_model=RunResponse)
async def confirm(
    session_id: str,
    request: Request,
    payload: ConfirmRequest,
    user_id: str = Depends(_current_user),
) -> RunResponse:
    agent: Agent = request.app.state.agent
    response = await agent.confirm(
        session_id=session_id,
        confirmation=PlanConfirmation(approved=payload.approved, scope=payload.scope),
    )
    if response.session.user_id not in (user_id, "default"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="session_owned_by_another_user")
    return RunResponse(
        session_id=response.session.id,
        plan_state=response.plan.state.value,
        needs_confirmation=response.needs_confirmation,
        steps=_serialize_plan(response.plan),
        message=response.message,
    )


@app.get("/v1/sessions/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    user_id: str = Depends(_current_user),
) -> dict[str, Any]:
    agent: Agent = request.app.state.agent
    session = await agent.session_manager.load(session_id)
    if session.user_id not in (user_id, "default"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="session_owned_by_another_user")
    return {
        "id": session.id,
        "user_id": session.user_id,
        "state": session.state.value,
        "plan": _serialize_plan(session.plan) if session.plan else None,
    }


@app.websocket("/v1/ws/{session_id}")
async def websocket(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    token = websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
    agent: Agent = websocket.app.state.agent
    auth_result = await agent.auth_provider.authenticate(AuthRequest(token=token))
    if not auth_result.authenticated or not auth_result.user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id = auth_result.user_id

    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("kind", "run")
            if kind == "run":
                response = await agent.run(
                    message["prompt"], session_id=session_id, user_id=user_id
                )
                session_id = response.session.id
                await websocket.send_json({
                    "kind": "plan_update",
                    "session_id": session_id,
                    "needs_confirmation": response.needs_confirmation,
                    "plan_state": response.plan.state.value,
                    "steps": _serialize_plan(response.plan),
                })
            elif kind == "confirm":
                response = await agent.confirm(
                    session_id=session_id,
                    confirmation=PlanConfirmation(
                        approved=bool(message.get("approved", True)),
                        scope=message.get("scope"),
                    ),
                )
                await websocket.send_json({
                    "kind": "plan_update",
                    "session_id": session_id,
                    "needs_confirmation": response.needs_confirmation,
                    "plan_state": response.plan.state.value,
                    "steps": _serialize_plan(response.plan),
                })
            else:
                await websocket.send_json({"kind": "error", "message": f"unknown kind: {kind!r}"})
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
