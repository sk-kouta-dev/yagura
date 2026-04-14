"""Safety preset tests."""

from __future__ import annotations

import sys

import pytest

from tests.conftest import MockLLMProvider
from yagura import Config, DangerLevel, ExecutionEnvironment, safety_presets
from yagura.auth.apikey import APIKeyAuth
from yagura.auth.noauth import NoAuth
from yagura.confirmation.cli import CLIConfirmationHandler
from yagura.confirmation.handler import AutoApproveHandler
from yagura.llm.provider import DefaultLLMRouter, LLMRouter
from yagura.logging.file import FileLogger
from yagura.logging.null import NullLogger
from yagura.logging.stream import StreamLogger
from yagura.presets.safety import validate_maximum_security
from yagura.safety.policy import PolicyCheckResult, SecurityPolicyProvider

# ---------------------------------------------------------------------------
# development
# ---------------------------------------------------------------------------


def test_development_preset_fields() -> None:
    preset = safety_presets.development()
    assert preset["auto_execute_threshold"] is DangerLevel.MODIFY
    assert preset["execution_env"] is ExecutionEnvironment.LOCAL
    assert isinstance(preset["confirmation_handler"], CLIConfirmationHandler)
    assert isinstance(preset["logger"], StreamLogger)
    assert preset["logger"].stream is sys.stdout


def test_development_spreads_into_config() -> None:
    cfg = Config(planner_llm=MockLLMProvider(), **safety_presets.development())
    assert cfg.auto_execute_threshold is DangerLevel.MODIFY
    assert cfg.execution_env is ExecutionEnvironment.LOCAL


# ---------------------------------------------------------------------------
# sandbox
# ---------------------------------------------------------------------------


def test_sandbox_preset_fields() -> None:
    preset = safety_presets.sandbox()
    assert preset["auto_execute_threshold"] is DangerLevel.DESTRUCTIVE
    assert preset["execution_env"] is ExecutionEnvironment.SANDBOX
    assert isinstance(preset["confirmation_handler"], AutoApproveHandler)
    assert isinstance(preset["logger"], NullLogger)


def test_sandbox_danger_rules_cap_destructive_at_modify() -> None:
    preset = safety_presets.sandbox()
    rules = preset["danger_rules"]
    # SANDBOX environment: delete_file should be MODIFY (capped), not DESTRUCTIVE.
    assert rules.classify("delete_file") is DangerLevel.MODIFY
    assert rules.classify("install_pkg") is DangerLevel.MODIFY


# ---------------------------------------------------------------------------
# internal_tool
# ---------------------------------------------------------------------------


def test_internal_tool_preset_fields(tmp_path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    preset = safety_presets.internal_tool(audit_path=str(audit_file))
    assert preset["auto_execute_threshold"] is DangerLevel.READ
    assert preset["execution_env"] is ExecutionEnvironment.LOCAL
    assert isinstance(preset["logger"], FileLogger)
    assert preset["logger"].path == audit_file


def test_internal_tool_default_audit_path() -> None:
    preset = safety_presets.internal_tool()
    assert preset["logger"].path.name == "yagura_audit.jsonl"


# ---------------------------------------------------------------------------
# enterprise
# ---------------------------------------------------------------------------


def test_enterprise_preset_fields(tmp_path) -> None:
    audit_file = tmp_path / "enterprise-audit.jsonl"
    preset = safety_presets.enterprise(
        audit_path=str(audit_file),
        api_keys={"k1": "alice"},
        max_concurrent_sessions=25,
    )
    assert preset["auto_execute_threshold"] is None  # All plans confirm.
    assert preset["execution_env"] is ExecutionEnvironment.SERVER
    assert isinstance(preset["auth_provider"], APIKeyAuth)
    assert preset["max_concurrent_sessions"] == 25


def test_enterprise_server_escalates_write() -> None:
    rules = safety_presets.enterprise()["danger_rules"]
    # In SERVER env, write_file escalates from MODIFY → DESTRUCTIVE.
    assert rules.classify("write_file") is DangerLevel.DESTRUCTIVE


def test_enterprise_all_plans_confirm() -> None:
    cfg = Config(planner_llm=MockLLMProvider(), **safety_presets.enterprise())
    assert cfg.auto_execute_threshold is None


# ---------------------------------------------------------------------------
# maximum_security
# ---------------------------------------------------------------------------


def test_maximum_security_preset_has_none_for_required_fields() -> None:
    preset = safety_presets.maximum_security()
    # These two are placeholders the user MUST override.
    assert preset["security_policy_provider"] is None
    assert preset["llm_router"] is None
    # Baseline constraints are still set.
    assert preset["auto_execute_threshold"] is None
    assert preset["max_concurrent_sessions"] == 1
    assert preset["execution_env"] is ExecutionEnvironment.SERVER


def test_validate_maximum_security_rejects_missing_policy() -> None:
    cfg = Config(planner_llm=MockLLMProvider(), **safety_presets.maximum_security())
    with pytest.raises(ValueError) as excinfo:
        validate_maximum_security(cfg)
    msg = str(excinfo.value)
    assert "security_policy_provider" in msg
    assert "llm_router" in msg


def test_validate_maximum_security_rejects_default_router() -> None:
    class _StubPolicy(SecurityPolicyProvider):
        async def check(self, *a, **k):
            return PolicyCheckResult(allowed=True)

    cfg = Config(
        planner_llm=MockLLMProvider(),
        **{
            **safety_presets.maximum_security(),
            "security_policy_provider": _StubPolicy(),
            # llm_router left at default (DefaultLLMRouter) via Config.__post_init__
        },
    )
    # DefaultLLMRouter is insufficient for maximum_security.
    assert isinstance(cfg.llm_router, DefaultLLMRouter)
    with pytest.raises(ValueError) as excinfo:
        validate_maximum_security(cfg)
    assert "llm_router" in str(excinfo.value)


def test_validate_maximum_security_passes_with_overrides() -> None:
    class _StubPolicy(SecurityPolicyProvider):
        async def check(self, *a, **k):
            return PolicyCheckResult(allowed=True)

    class _CustomRouter(LLMRouter):
        async def select(self, tool, params, context):
            return MockLLMProvider()

    cfg = Config(
        planner_llm=MockLLMProvider(),
        **{
            **safety_presets.maximum_security(),
            "security_policy_provider": _StubPolicy(),
            "llm_router": _CustomRouter(),
        },
    )
    # Should not raise.
    validate_maximum_security(cfg)


# ---------------------------------------------------------------------------
# Override behavior
# ---------------------------------------------------------------------------


def test_preset_fields_are_overridable_via_spread() -> None:
    cfg = Config(
        planner_llm=MockLLMProvider(),
        **{
            **safety_presets.enterprise(),
            "auto_execute_threshold": DangerLevel.READ,
            "max_concurrent_sessions": 50,
        },
    )
    assert cfg.auto_execute_threshold is DangerLevel.READ
    assert cfg.max_concurrent_sessions == 50


def test_development_preset_keeps_defaults_for_unspecified_fields() -> None:
    cfg = Config(planner_llm=MockLLMProvider(), **safety_presets.development())
    # development doesn't set auth_provider; Config should keep its NoAuth default.
    assert isinstance(cfg.auth_provider, NoAuth)


# ---------------------------------------------------------------------------
# All presets smoke
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "preset_fn",
    [
        safety_presets.development,
        safety_presets.sandbox,
        safety_presets.internal_tool,
        safety_presets.enterprise,
        safety_presets.maximum_security,
    ],
)
def test_every_preset_spreads_into_a_valid_config(preset_fn) -> None:
    cfg = Config(planner_llm=MockLLMProvider(), **preset_fn())
    # Basic invariants.
    assert cfg.planner_llm is not None
    assert cfg.danger_rules is not None
    assert cfg.confirmation_handler is not None
