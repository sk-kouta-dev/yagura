"""Layer 1 (rule-based) DangerAssessor coverage — P0 test target."""

from __future__ import annotations

import pytest

from yagura.safety.assessor import DangerAssessor
from yagura.safety.rules import DangerLevel, DangerRules, ExecutionEnvironment
from yagura.tools.tool import Tool


def _tool(name: str, *, danger: DangerLevel | None = None) -> Tool:
    return Tool(
        name=name,
        description=f"{name} tool",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda: None,
        danger_level=danger,
    )


# ---------------------------------------------------------------------------
# Prefix classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("search_files", DangerLevel.READ),
        ("list_all", DangerLevel.READ),
        ("get_user", DangerLevel.READ),
        ("read_file", DangerLevel.READ),
        ("grep_logs", DangerLevel.READ),
        ("find_user", DangerLevel.READ),
        ("copy_file", DangerLevel.MODIFY),
        ("rename_doc", DangerLevel.MODIFY),
        ("create_draft_email", DangerLevel.MODIFY),
        ("create_folder_reports", DangerLevel.MODIFY),
        ("delete_user", DangerLevel.DESTRUCTIVE),
        ("send_email", DangerLevel.DESTRUCTIVE),
        ("move_to_external_drive", DangerLevel.DESTRUCTIVE),
        ("push_commit", DangerLevel.DESTRUCTIVE),
        ("install_package", DangerLevel.INSTALL),
        ("system_config_set", DangerLevel.INSTALL),
        ("package_upgrade", DangerLevel.INSTALL),
    ],
)
def test_rules_classify_all_prefixes(name: str, expected: DangerLevel) -> None:
    assert DangerRules.default().classify(name) == expected


def test_unknown_tool_name_returns_none() -> None:
    assert DangerRules.default().classify("wibble_whatever") is None


# ---------------------------------------------------------------------------
# Override behavior
# ---------------------------------------------------------------------------


def test_explicit_override_wins_over_prefix() -> None:
    rules = DangerRules(overrides={"delete_temp": DangerLevel.MODIFY})
    # Without override it would be DESTRUCTIVE.
    assert rules.classify("delete_temp") is DangerLevel.MODIFY


def test_tool_level_danger_overrides_rule_match() -> None:
    assessor = DangerAssessor(rules=DangerRules.default())
    tool = _tool("search_secret", danger=DangerLevel.DESTRUCTIVE)
    import asyncio

    result = asyncio.run(assessor.assess(tool, {}))
    assert result.level is DangerLevel.DESTRUCTIVE
    assert result.layer == 1
    assert result.confidence == 1.0
    assert "Explicit Tool.danger_level" in result.reason


# ---------------------------------------------------------------------------
# Environment adjustments
# ---------------------------------------------------------------------------


def test_sandbox_caps_at_modify() -> None:
    rules = DangerRules.from_env(ExecutionEnvironment.SANDBOX)
    # Originally DESTRUCTIVE in default rules.
    assert rules.classify("delete_file") is DangerLevel.MODIFY
    # Originally INSTALL.
    assert rules.classify("install_pkg") is DangerLevel.MODIFY


def test_docker_downgrades_delete() -> None:
    rules = DangerRules.from_env(ExecutionEnvironment.DOCKER)
    assert rules.classify("delete_thing") is DangerLevel.MODIFY
    assert rules.classify("remove_thing") is DangerLevel.MODIFY
    # Send_ is still DESTRUCTIVE though.
    assert rules.classify("send_email") is DangerLevel.DESTRUCTIVE


def test_server_escalates_write() -> None:
    rules = DangerRules.from_env(ExecutionEnvironment.SERVER)
    assert rules.classify("write_file") is DangerLevel.DESTRUCTIVE


def test_local_defaults_are_unchanged() -> None:
    defaults = DangerRules.default()
    local = DangerRules.from_env(ExecutionEnvironment.LOCAL)
    assert defaults.read_prefixes == local.read_prefixes
    assert defaults.modify_prefixes == local.modify_prefixes
    assert defaults.destructive_prefixes == local.destructive_prefixes
    assert defaults.install_prefixes == local.install_prefixes


# ---------------------------------------------------------------------------
# Assessor async flow (layer 1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assessor_returns_layer1_for_known_prefix() -> None:
    assessor = DangerAssessor(rules=DangerRules.default())
    tool = _tool("list_files")
    assessment = await assessor.assess(tool, {})
    assert assessment.level is DangerLevel.READ
    assert assessment.layer == 1
    assert assessment.confidence == 1.0


@pytest.mark.asyncio
async def test_requires_confirmation_respects_threshold() -> None:
    assessor = DangerAssessor(
        rules=DangerRules.default(),
        auto_execute_threshold=DangerLevel.READ,
    )
    read_tool = _tool("list_files")
    write_tool = _tool("create_draft_email")
    destroy_tool = _tool("delete_user")

    read = await assessor.assess(read_tool, {})
    modify = await assessor.assess(write_tool, {})
    destroy = await assessor.assess(destroy_tool, {})

    assert read.requires_confirmation is False
    assert modify.requires_confirmation is True  # MODIFY > READ
    assert destroy.requires_confirmation is True


@pytest.mark.asyncio
async def test_none_threshold_always_requires_confirmation() -> None:
    assessor = DangerAssessor(rules=DangerRules.default(), auto_execute_threshold=None)
    read = await assessor.assess(_tool("list_files"), {})
    assert read.requires_confirmation is True
