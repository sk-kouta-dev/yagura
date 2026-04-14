"""yagura-tools-snowflake — SQL, stages, Cortex.

Credentials: standard Snowflake environment variables (SNOWFLAKE_ACCOUNT,
SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, etc.) or programmatic keys.
"""

from __future__ import annotations

import os
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _connect(database: str | None = None, schema: str | None = None, warehouse: str | None = None):
    try:
        import snowflake.connector  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-snowflake requires 'snowflake-connector-python'") from exc
    return snowflake.connector.connect(
        account=os.environ.get("SNOWFLAKE_ACCOUNT"),
        user=os.environ.get("SNOWFLAKE_USER"),
        password=os.environ.get("SNOWFLAKE_PASSWORD"),
        database=database or os.environ.get("SNOWFLAKE_DATABASE"),
        schema=schema or os.environ.get("SNOWFLAKE_SCHEMA"),
        warehouse=warehouse or os.environ.get("SNOWFLAKE_WAREHOUSE"),
        role=os.environ.get("SNOWFLAKE_ROLE"),
    )


def _snowflake_query(
    query: str,
    database: str | None = None,
    schema: str | None = None,
    warehouse: str | None = None,
) -> ToolResult:
    conn = _connect(database, schema, warehouse)
    try:
        cur = conn.cursor()
        try:
            cur.execute(query)
            columns = [c[0] for c in cur.description or []]
            rows = cur.fetchall() if columns else []
            data = [dict(zip(columns, row)) for row in rows]
            return ToolResult(
                success=True,
                data={"columns": columns, "rows": data, "rowcount": cur.rowcount},
                reliability=ReliabilityLevel.AUTHORITATIVE,
            )
        finally:
            cur.close()
    finally:
        conn.close()


def _snowflake_list_tables(database: str | None = None, schema: str | None = None) -> ToolResult:
    return _snowflake_query(
        "SHOW TABLES" + (f" IN {database}.{schema}" if database and schema else ""),
        database=database,
        schema=schema,
    )


def _snowflake_describe_table(table: str, database: str | None = None, schema: str | None = None) -> ToolResult:
    return _snowflake_query(f"DESCRIBE TABLE {table}", database=database, schema=schema)


def _snowflake_stage_upload(local_path: str, stage: str, path: str | None = None) -> ToolResult:
    put_target = f"@{stage}/{path}" if path else f"@{stage}"
    return _snowflake_query(f"PUT file://{local_path} {put_target} AUTO_COMPRESS=TRUE OVERWRITE=TRUE")


def _snowflake_stage_list(stage: str, pattern: str | None = None) -> ToolResult:
    q = f"LIST @{stage}"
    if pattern:
        q += f" PATTERN='{pattern}'"
    return _snowflake_query(q)


def _snowflake_cortex_invoke(function: str, params: dict[str, Any]) -> ToolResult:
    placeholders = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in params.values())
    return _snowflake_query(f"SELECT {function}({placeholders}) AS result")


def _snowflake_natural_query(
    question: str,
    database: str | None = None,
    schema: str | None = None,
    query: str | None = None,
) -> ToolResult:
    # `query` is populated by the executor LLM (requires_llm=True).
    effective = query or question
    return _snowflake_query(effective, database=database, schema=schema)


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name, description=description,
        parameters={"type": "object", "properties": props, "required": required},
        handler=handler, danger_level=danger, tags=["snowflake"], **extra,
    )


tools: list[Tool] = [
    _T("snowflake_query", "Execute a SQL query on Snowflake. Layer 2 classifies it.",
        {"query": {"type": "string"}, "database": {"type": "string"}, "schema": {"type": "string"}, "warehouse": {"type": "string"}},
        ["query"], _snowflake_query, None,
        requires_llm=True,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("snowflake_list_tables", "List Snowflake tables.",
        {"database": {"type": "string"}, "schema": {"type": "string"}},
        [], _snowflake_list_tables, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("snowflake_describe_table", "Describe a table's schema.",
        {"table": {"type": "string"}, "database": {"type": "string"}, "schema": {"type": "string"}},
        ["table"], _snowflake_describe_table, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("snowflake_stage_upload", "Upload a file to a stage.",
        {"local_path": {"type": "string"}, "stage": {"type": "string"}, "path": {"type": "string"}},
        ["local_path", "stage"], _snowflake_stage_upload, DangerLevel.MODIFY),
    _T("snowflake_stage_list", "List files in a stage.",
        {"stage": {"type": "string"}, "pattern": {"type": "string"}},
        ["stage"], _snowflake_stage_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("snowflake_cortex_invoke", "Invoke a Cortex function.",
        {"function": {"type": "string"}, "params": {"type": "object"}},
        ["function", "params"], _snowflake_cortex_invoke, DangerLevel.MODIFY),
    _T("snowflake_natural_query", "Translate natural language → SQL → execute on Snowflake.",
        {"question": {"type": "string"}, "database": {"type": "string"}, "schema": {"type": "string"}, "query": {"type": "string", "description": "Populated by executor LLM."}},
        ["question"], _snowflake_natural_query, None,
        requires_llm=True,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
]

__all__ = ["tools"]
