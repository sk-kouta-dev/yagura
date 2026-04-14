"""SessionManager + StateStore tests — P1."""

from __future__ import annotations

import pytest

from yagura.errors import ConcurrentPlanError, SessionNotFoundError
from yagura.plan import Plan, PlanState
from yagura.session.manager import SessionManager
from yagura.session.memory import InMemoryStateStore
from yagura.session.sqlite import SQLiteStateStore


@pytest.mark.asyncio
async def test_create_and_load_session_memory() -> None:
    mgr = SessionManager(InMemoryStateStore())
    session = await mgr.create(user_id="alice")
    loaded = await mgr.load(session.id)
    assert loaded.user_id == "alice"
    assert loaded.id == session.id


@pytest.mark.asyncio
async def test_missing_session_raises() -> None:
    mgr = SessionManager(InMemoryStateStore())
    with pytest.raises(SessionNotFoundError):
        await mgr.load("nope")


@pytest.mark.asyncio
async def test_list_by_user() -> None:
    mgr = SessionManager(InMemoryStateStore(), max_concurrent_sessions=5)
    await mgr.create(user_id="alice")
    await mgr.create(user_id="bob")
    await mgr.create(user_id="alice")
    alice = await mgr.list_for_user("alice")
    bob = await mgr.list_for_user("bob")
    assert len(alice) == 2
    assert len(bob) == 1


@pytest.mark.asyncio
async def test_single_active_plan_enforcement() -> None:
    mgr = SessionManager(InMemoryStateStore(), max_concurrent_sessions=1)
    s1 = await mgr.create(user_id="alice")
    # Attach an active plan so s1 is counted as active.
    s1.plan = Plan(id="p1", steps=[], state=PlanState.RUNNING)
    await mgr.save(s1)
    with pytest.raises(ConcurrentPlanError):
        await mgr.create(user_id="alice")


@pytest.mark.asyncio
async def test_terminal_plan_does_not_block_new_session() -> None:
    mgr = SessionManager(InMemoryStateStore(), max_concurrent_sessions=1)
    s1 = await mgr.create(user_id="alice")
    s1.plan = Plan(id="p1", steps=[], state=PlanState.COMPLETED)
    await mgr.save(s1)
    # Should succeed: completed plan is no longer "active".
    s2 = await mgr.create(user_id="alice")
    assert s2.id != s1.id


@pytest.mark.asyncio
async def test_sqlite_roundtrip(tmp_path) -> None:
    path = tmp_path / "state.db"
    store = SQLiteStateStore(path=path)
    mgr = SessionManager(store, max_concurrent_sessions=5)
    session = await mgr.create(user_id="alice")
    session.plan = Plan(
        id="p1",
        steps=[],
        state=PlanState.DRAFT,
    )
    await mgr.save(session)

    reloaded = await mgr.load(session.id)
    assert reloaded.user_id == "alice"
    assert reloaded.plan is not None
    assert reloaded.plan.id == "p1"
    assert reloaded.plan.state is PlanState.DRAFT
