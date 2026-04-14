"""yagura-tools-db — SQL database tools.

Supports sqlite:// URLs out of the box. postgresql:// requires the [postgres] extra
(psycopg2-binary); mysql:// requires [mysql] (pymysql).

db_query and db_natural_query are Dynamic Tools: DangerAssessor Layer 2
(or the executor LLM for db_natural_query) classifies the generated SQL.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


_READ_KEYWORDS = re.compile(r"^\s*(select|with|show|describe|explain|pragma)\b", re.IGNORECASE)
_DESTRUCTIVE_KEYWORDS = re.compile(r"^\s*(drop|truncate|alter|delete)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Connection plumbing
# ---------------------------------------------------------------------------


@contextmanager
def _connect(connection_string: str):
    scheme = urlparse(connection_string).scheme.lower()
    if scheme in ("sqlite", "sqlite3", ""):
        path = connection_string.removeprefix("sqlite:///").removeprefix("sqlite://")
        conn = sqlite3.connect(path or ":memory:")
        try:
            yield conn, "sqlite"
        finally:
            conn.close()
    elif scheme in ("postgres", "postgresql"):
        try:
            import psycopg2  # type: ignore
            import psycopg2.extras  # type: ignore
        except ImportError as exc:
            raise ImportError("postgresql requires the [postgres] extra: pip install yagura-tools-db[postgres]") from exc
        conn = psycopg2.connect(connection_string)
        try:
            yield conn, "postgres"
        finally:
            conn.close()
    elif scheme in ("mysql", "mysql+pymysql"):
        try:
            import pymysql  # type: ignore
        except ImportError as exc:
            raise ImportError("mysql requires the [mysql] extra: pip install yagura-tools-db[mysql]") from exc
        parsed = urlparse(connection_string)
        conn = pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=(parsed.path or "/").lstrip("/"),
        )
        try:
            yield conn, "mysql"
        finally:
            conn.close()
    else:
        raise ValueError(f"Unsupported connection string scheme: {scheme!r}")


def _execute_query(conn, dialect: str, query: str, params: list[Any] | None = None):
    cur = conn.cursor()
    try:
        cur.execute(query, params or ())
        columns = [d[0] for d in cur.description] if cur.description else []
        try:
            rows = cur.fetchall()
        except Exception:
            rows = []
        conn.commit()
        return columns, rows, cur.rowcount
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _db_query(connection_string: str, query: str, params: list[Any] | None = None) -> ToolResult:
    with _connect(connection_string) as (conn, dialect):
        columns, rows, rowcount = _execute_query(conn, dialect, query, params)
    data = [dict(zip(columns, row)) for row in rows] if columns else []
    reliability = (
        ReliabilityLevel.AUTHORITATIVE if _READ_KEYWORDS.match(query) else ReliabilityLevel.VERIFIED
    )
    return ToolResult(
        success=True,
        data={"columns": columns, "rows": data, "rowcount": rowcount},
        reliability=reliability,
    )


def _db_list_tables(connection_string: str, schema: str | None = None) -> ToolResult:
    with _connect(connection_string) as (conn, dialect):
        if dialect == "sqlite":
            columns, rows, _ = _execute_query(
                conn, dialect, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        elif dialect == "postgres":
            columns, rows, _ = _execute_query(
                conn,
                dialect,
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s ORDER BY table_name",
                [schema or "public"],
            )
        else:  # mysql
            columns, rows, _ = _execute_query(conn, dialect, "SHOW TABLES")
    return ToolResult(
        success=True,
        data={"tables": [r[0] for r in rows], "schema": schema},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _db_describe_table(connection_string: str, table: str) -> ToolResult:
    with _connect(connection_string) as (conn, dialect):
        if dialect == "sqlite":
            cols, rows, _ = _execute_query(conn, dialect, f"PRAGMA table_info({table})")
            schema = [
                {"name": r[1], "type": r[2], "notnull": bool(r[3]), "pk": bool(r[5])} for r in rows
            ]
        elif dialect == "postgres":
            _, rows, _ = _execute_query(
                conn,
                dialect,
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns WHERE table_name = %s",
                [table],
            )
            schema = [{"name": r[0], "type": r[1], "nullable": r[2] == "YES"} for r in rows]
        else:  # mysql
            _, rows, _ = _execute_query(conn, dialect, f"DESCRIBE `{table}`")
            schema = [{"name": r[0], "type": r[1], "nullable": r[2] == "YES"} for r in rows]
    return ToolResult(success=True, data={"table": table, "columns": schema})


def _db_natural_query(connection_string: str, question: str) -> ToolResult:
    """Placeholder — actual LLM invocation is performed by Yagura's PlanExecutor
    because the tool is declared `requires_llm=True`. The executor LLM translates
    `question` into a concrete SQL query and substitutes it into the parameters
    before this handler runs.
    """
    # When requires_llm=True, the PlanExecutor's _transform_params_via_llm step
    # replaces `question` with `{query, connection_string}` — so by the time we
    # get here, params should already contain a `query`. If they don't (because
    # the LLM declined), fall back to treating `question` as a raw query.
    return _db_query(connection_string=connection_string, query=question)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


db_query = Tool(
    name="db_query",
    description=(
        "Execute a SQL query. The DangerAssessor inspects the query to classify it "
        "(SELECT=READ, INSERT/UPDATE=MODIFY, DROP/DELETE=DESTRUCTIVE)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "connection_string": {"type": "string"},
            "query": {"type": "string"},
            "params": {"type": "array", "items": {}, "default": []},
        },
        "required": ["connection_string", "query"],
    },
    handler=_db_query,
    # No danger_level: Dynamic Tool, Layer 2 assesses the query.
    requires_llm=True,
    default_reliability=ReliabilityLevel.VERIFIED,
    tags=["db", "sql"],
)

db_list_tables = Tool(
    name="db_list_tables",
    description="List all tables in a database (or a specific schema for Postgres).",
    parameters={
        "type": "object",
        "properties": {
            "connection_string": {"type": "string"},
            "schema": {"type": "string"},
        },
        "required": ["connection_string"],
    },
    handler=_db_list_tables,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["db", "sql"],
)

db_describe_table = Tool(
    name="db_describe_table",
    description="Get a table's column schema.",
    parameters={
        "type": "object",
        "properties": {
            "connection_string": {"type": "string"},
            "table": {"type": "string"},
        },
        "required": ["connection_string", "table"],
    },
    handler=_db_describe_table,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["db", "sql"],
)

db_natural_query = Tool(
    name="db_natural_query",
    description=(
        "Translate a natural-language question into SQL and execute it. "
        "The executor LLM generates the SQL; DangerAssessor classifies it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "connection_string": {"type": "string"},
            "question": {"type": "string"},
            "query": {"type": "string", "description": "Populated by the executor LLM."},
        },
        "required": ["connection_string", "question"],
    },
    handler=_db_natural_query,
    requires_llm=True,
    default_reliability=ReliabilityLevel.VERIFIED,
    tags=["db", "sql", "llm"],
)


tools: list[Tool] = [db_query, db_list_tables, db_describe_table, db_natural_query]

__all__ = ["tools"]
