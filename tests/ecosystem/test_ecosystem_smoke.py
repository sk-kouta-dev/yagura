"""Smoke tests for every ecosystem package.

Each tool package exports `tools: list[Tool]`. This suite verifies:
  1. The package imports successfully.
  2. `tools` is a non-empty list of Tool objects.
  3. Every tool has a name, parameters schema, and a handler.
  4. Tool names match what the ecosystem spec advertises.

State / logger / auth packages are covered via import checks (they
require real network connections to exercise further).
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from yagura.tools.tool import Tool

TOOL_PACKAGES: list[tuple[str, int]] = [
    # (import path, expected minimum tool count)
    ("yagura_tools.common", 13),
    ("yagura_tools.git", 12),
    ("yagura_tools.db", 4),
    ("yagura_tools.browser", 11),
    ("yagura_tools.docker", 10),
    ("yagura_tools.k8s", 14),
    ("yagura_tools.aws", 12),
    ("yagura_tools.gcp", 7),
    ("yagura_tools.azure", 8),
    ("yagura_tools.slack", 7),
    ("yagura_tools.google", 15),
    ("yagura_tools.microsoft", 14),
    ("yagura_tools.notion", 10),
    ("yagura_tools.jira", 10),
    ("yagura_tools.confluence", 8),
    ("yagura_tools.datadog", 8),
    ("yagura_tools.snowflake", 7),
    ("yagura_tools.openapi", 3),
    ("yagura_tools.scraping", 7),
    ("yagura_tools.llm", 8),
]


@pytest.mark.parametrize("package, expected_count", TOOL_PACKAGES)
def test_package_exports_tools(package: str, expected_count: int) -> None:
    """Each tool package must expose a `tools` list matching the spec count."""
    module = importlib.import_module(package)
    assert hasattr(module, "tools"), f"{package} must export `tools`"
    tools = module.tools
    assert isinstance(tools, list)
    assert len(tools) == expected_count, f"{package} should export {expected_count} tools, got {len(tools)}"
    for t in tools:
        assert isinstance(t, Tool)
        assert t.name
        assert isinstance(t.parameters, dict)
        assert "type" in t.parameters
        assert callable(t.handler), f"{package}:{t.name} has no handler"


# ---------------------------------------------------------------------------
# DangerLevel correctness per ecosystem spec
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "package, expectations",
    [
        (
            "yagura_tools.common",
            {
                "file_read": "READ",
                "file_write": "MODIFY",
                "file_delete": "DESTRUCTIVE",
                "directory_list": "READ",
                "directory_delete": "DESTRUCTIVE",
                "process_kill": "DESTRUCTIVE",
            },
        ),
        (
            "yagura_tools.git",
            {
                "git_status": "READ",
                "git_commit": "MODIFY",
                "git_push": "DESTRUCTIVE",
                "git_create_pr": "DESTRUCTIVE",
                "git_merge": "DESTRUCTIVE",
            },
        ),
        (
            "yagura_tools.aws",
            {
                "s3_list": "READ",
                "s3_upload": "MODIFY",
                "s3_delete": "DESTRUCTIVE",
                "lambda_invoke": "MODIFY",
            },
        ),
        (
            "yagura_tools.slack",
            {
                "slack_send": "DESTRUCTIVE",
                "slack_search": "READ",
                "slack_channel_create": "MODIFY",
            },
        ),
        (
            "yagura_tools.google",
            {
                "gmail_send": "DESTRUCTIVE",
                "gmail_draft_create": "MODIFY",
                "gdrive_delete": "DESTRUCTIVE",
                "gcalendar_delete": "DESTRUCTIVE",
            },
        ),
        (
            "yagura_tools.browser",
            {
                "browser_navigate": "READ",
                "browser_click": "MODIFY",
                "browser_submit": "DESTRUCTIVE",
            },
        ),
        (
            "yagura_tools.notion",
            {
                "notion_page_search": "READ",
                "notion_page_create": "MODIFY",
                "notion_page_delete": "DESTRUCTIVE",
                "notion_block_delete": "DESTRUCTIVE",
            },
        ),
    ],
)
def test_danger_levels_match_spec(package: str, expectations: dict[str, str]) -> None:
    module = importlib.import_module(package)
    lookup = {t.name: t for t in module.tools}
    for name, expected in expectations.items():
        assert name in lookup, f"{package}:{name} missing"
        actual = lookup[name].danger_level
        assert actual is not None, f"{package}:{name} has no danger_level"
        assert actual.name == expected, f"{package}:{name} expected {expected}, got {actual.name}"


# ---------------------------------------------------------------------------
# Dynamic tools
# ---------------------------------------------------------------------------


def test_dynamic_tools_marked_correctly() -> None:
    """Dynamic tools (per spec) must have requires_llm=True and no fixed danger_level."""
    from yagura_tools.common import tools as common_tools
    from yagura_tools.db import tools as db_tools
    from yagura_tools.llm import tools as llm_tools

    dyn_names = {"shell_execute", "http_request"}
    for t in common_tools:
        if t.name in dyn_names:
            assert t.requires_llm is True, f"{t.name} must be requires_llm=True"
            assert t.danger_level is None, f"{t.name} must have no fixed danger_level"

    for t in db_tools:
        if t.name in {"db_query", "db_natural_query"}:
            assert t.requires_llm is True
            assert t.danger_level is None

    for t in llm_tools:
        # LLM-as-tool path: the tool IS the LLM call (no handler dispatch).
        assert t.llm_task_template is not None, f"{t.name} must set llm_task_template"
        assert t.danger_level is not None
        assert t.danger_level.name == "READ"


# ---------------------------------------------------------------------------
# Ecosystem-wide: no duplicate tool names across packages (paranoia check)
# ---------------------------------------------------------------------------


def test_no_duplicate_tool_names_across_packages() -> None:
    seen: dict[str, str] = {}
    for pkg, _ in TOOL_PACKAGES:
        module = importlib.import_module(pkg)
        for t in module.tools:
            if t.name in seen:
                pytest.fail(f"Duplicate tool name '{t.name}' in {pkg} (already in {seen[t.name]})")
            seen[t.name] = pkg


# ---------------------------------------------------------------------------
# State / logger / auth: import checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "import_path, symbol",
    [
        ("yagura_state.postgres", "PostgresStateStore"),
        ("yagura_state.redis", "RedisStateStore"),
        ("yagura_state.dynamodb", "DynamoDBStateStore"),
        ("yagura_logger.datadog", "DatadogLogger"),
        ("yagura_logger.cloudwatch", "CloudWatchLogger"),
        ("yagura_auth.oauth2", "OAuth2Provider"),
    ],
)
def test_infrastructure_packages_import(import_path: str, symbol: str) -> None:
    module = importlib.import_module(import_path)
    assert hasattr(module, symbol), f"{import_path} must export {symbol}"
    obj: Any = getattr(module, symbol)
    assert callable(obj), f"{symbol} must be a class/callable"


def test_state_stores_implement_statestore_interface() -> None:
    """Postgres/Redis/Dynamo state stores must subclass StateStore."""
    from yagura_state.dynamodb import DynamoDBStateStore
    from yagura_state.postgres import PostgresStateStore
    from yagura_state.redis import RedisStateStore

    from yagura.session.store import StateStore

    for cls in (PostgresStateStore, RedisStateStore, DynamoDBStateStore):
        assert issubclass(cls, StateStore), f"{cls.__name__} must subclass StateStore"


def test_loggers_implement_auditlogger_interface() -> None:
    from yagura_logger.cloudwatch import CloudWatchLogger
    from yagura_logger.datadog import DatadogLogger

    from yagura.logging.logger import AuditLogger

    for cls in (DatadogLogger, CloudWatchLogger):
        assert issubclass(cls, AuditLogger), f"{cls.__name__} must subclass AuditLogger"


def test_oauth2_implements_authprovider_interface() -> None:
    from yagura_auth.oauth2 import OAuth2Provider

    from yagura.auth.provider import AuthProvider

    assert issubclass(OAuth2Provider, AuthProvider)
