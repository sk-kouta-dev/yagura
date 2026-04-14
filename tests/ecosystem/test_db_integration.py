"""Real-execution tests for yagura-tools-db against SQLite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from yagura.safety.reliability import ReliabilityLevel
from yagura.tools.executor import ToolExecutor

_executor = ToolExecutor()


async def _call(tool, **params):
    return await _executor.execute(tool, params)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    p = tmp_path / "test.db"
    with sqlite3.connect(p) as conn:
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, active INTEGER);
            INSERT INTO users (name, active) VALUES ('alice', 1), ('bob', 0), ('carol', 1);
            """
        )
        conn.commit()
    return f"sqlite:///{p.as_posix()}"


@pytest.mark.asyncio
async def test_db_list_tables(db_path: str) -> None:
    from yagura_tools.db import db_list_tables

    result = await _call(db_list_tables, connection_string=db_path, schema=None)
    assert result.success
    assert "users" in result.data["tables"]


@pytest.mark.asyncio
async def test_db_describe_table(db_path: str) -> None:
    from yagura_tools.db import db_describe_table

    result = await _call(db_describe_table, connection_string=db_path, table="users")
    assert result.success
    column_names = {c["name"] for c in result.data["columns"]}
    assert column_names == {"id", "name", "active"}


@pytest.mark.asyncio
async def test_db_query_select_is_authoritative(db_path: str) -> None:
    from yagura_tools.db import db_query

    result = await _call(
        db_query,
        connection_string=db_path,
        query="SELECT name FROM users WHERE active = ? ORDER BY name",
        params=[1],
    )
    assert result.success
    names = [row["name"] for row in result.data["rows"]]
    assert names == ["alice", "carol"]
    # SELECT results should be AUTHORITATIVE (spec).
    assert result.reliability is ReliabilityLevel.AUTHORITATIVE


@pytest.mark.asyncio
async def test_db_query_insert(db_path: str) -> None:
    from yagura_tools.db import db_query

    result = await _call(
        db_query,
        connection_string=db_path,
        query="INSERT INTO users (name, active) VALUES (?, ?)",
        params=["dave", 1],
    )
    assert result.success
    # Verify the insert landed.
    check = await _call(
        db_query,
        connection_string=db_path,
        query="SELECT name FROM users WHERE name = 'dave'",
        params=[],
    )
    assert check.data["rows"][0]["name"] == "dave"


@pytest.mark.asyncio
async def test_db_query_rejects_bad_connection_string() -> None:
    from yagura_tools.db import db_query

    from yagura.errors import ToolExecutionError

    # ToolExecutor wraps the ValueError into a ToolExecutionError.
    with pytest.raises(ToolExecutionError):
        await _call(
            db_query,
            connection_string="unsupported://whatever",
            query="SELECT 1",
        )


@pytest.mark.asyncio
async def test_db_list_tables_via_agent_plan(tmp_path: Path, db_path: str) -> None:
    """End-to-end: a full Agent plan that calls db_list_tables."""
    from yagura_tools.db import db_list_tables

    from tests.conftest import MockLLMProvider, plan_tool_response
    from yagura import Agent, Config, DangerLevel
    from yagura.confirmation.handler import AutoApproveHandler

    llm = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "db_list_tables",
                        "parameters": {"connection_string": db_path},
                        "description": "list tables",
                    }
                ]
            )
        ]
    )
    agent = Agent(
        Config(
            planner_llm=llm,
            auto_execute_threshold=DangerLevel.READ,
            confirmation_handler=AutoApproveHandler(),
        )
    )
    agent.register_tool(db_list_tables)

    response = await agent.run("list tables please")
    assert response.plan.state.value == "completed"
    assert "users" in response.plan.steps[0].result.data["tables"]
