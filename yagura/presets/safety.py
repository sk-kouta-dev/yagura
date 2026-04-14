"""Pre-configured safety settings for common deployment scenarios.

Each function returns a dict suitable for spreading into `Config(**preset, ...)`.
Callers can override any field:

    Config(
        planner_llm=AnthropicProvider(...),
        **{**safety_presets.enterprise(), "auto_execute_threshold": DangerLevel.READ},
    )

Preset layering, from least to most restrictive:
  sandbox      → everything auto-executes, logging off
  development  → READ + MODIFY auto-execute, stdout logs
  internal_tool→ READ auto-executes, file audit log
  enterprise   → all plans require confirmation, multi-user, full audit
  maximum_security → enterprise + mandatory policy + mandatory LLM router
"""

from __future__ import annotations

import sys
from typing import Any

from yagura.auth.apikey import APIKeyAuth
from yagura.confirmation.cli import CLIConfirmationHandler
from yagura.confirmation.handler import AutoApproveHandler
from yagura.logging.file import FileLogger
from yagura.logging.null import NullLogger
from yagura.logging.stream import StreamLogger
from yagura.safety.rules import DangerLevel, DangerRules, ExecutionEnvironment

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


def development() -> dict[str, Any]:
    """Local development. Lenient safety, minimal friction.

    - READ and MODIFY auto-execute.
    - DESTRUCTIVE and INSTALL require confirmation.
    - Stdout audit logs.
    - No auth, no policy check.
    """
    return {
        "auto_execute_threshold": DangerLevel.MODIFY,
        "execution_env": ExecutionEnvironment.LOCAL,
        "danger_rules": DangerRules.default(),
        "confirmation_handler": CLIConfirmationHandler(),
        "logger": StreamLogger(sys.stdout),
    }


def sandbox() -> dict[str, Any]:
    """Demo / workshop sandbox. Everything auto-executes.

    - SANDBOX environment caps all operations at MODIFY.
    - No confirmation prompts (AutoApproveHandler).
    - No logging, no auth.

    Use for onboarding, interactive demos, and disposable VMs only.
    """
    return {
        "auto_execute_threshold": DangerLevel.DESTRUCTIVE,
        "execution_env": ExecutionEnvironment.SANDBOX,
        "danger_rules": DangerRules.from_env(ExecutionEnvironment.SANDBOX),
        "confirmation_handler": AutoApproveHandler(),
        "logger": NullLogger(),
    }


def internal_tool(audit_path: str = "./yagura_audit.jsonl") -> dict[str, Any]:
    """Internal company tool. Balanced safety + usability.

    - Only READ auto-executes.
    - MODIFY / DESTRUCTIVE / INSTALL require confirmation.
    - File-based audit log (override `audit_path` for custom location).
    - Single user (NoAuth by default).
    """
    return {
        "auto_execute_threshold": DangerLevel.READ,
        "execution_env": ExecutionEnvironment.LOCAL,
        "danger_rules": DangerRules.default(),
        "confirmation_handler": CLIConfirmationHandler(),
        "logger": FileLogger(path=audit_path),
    }


def enterprise(
    audit_path: str = "./yagura_audit.jsonl",
    api_keys: dict[str, str] | None = None,
    max_concurrent_sessions: int = 10,
) -> dict[str, Any]:
    """Production enterprise deployment. Full safety, full audit.

    - auto_execute_threshold=None → every plan requires explicit confirmation.
    - SERVER environment escalates write_file → DESTRUCTIVE.
    - File-based audit log (override with Datadog/CloudWatch for centralized).
    - APIKey auth enabled (pass `api_keys={"key": "user_id"}` or override).
    - Multi-user (max_concurrent_sessions=10 by default).

    Override the confirmation_handler with a WebUIConfirmationHandler
    implementation in production to avoid stdin blocking.
    """
    return {
        "auto_execute_threshold": None,
        "execution_env": ExecutionEnvironment.SERVER,
        "danger_rules": DangerRules.from_env(ExecutionEnvironment.SERVER),
        "confirmation_handler": CLIConfirmationHandler(),
        "logger": FileLogger(path=audit_path),
        "auth_provider": APIKeyAuth(keys=api_keys or {}),
        "max_concurrent_sessions": max_concurrent_sessions,
    }


def maximum_security(
    audit_path: str = "./yagura_audit.jsonl",
    api_keys: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Regulated industries (finance, healthcare, government). Maximum restrictions.

    - Every plan requires confirmation.
    - SERVER environment.
    - security_policy_provider MUST be set by the caller (this preset leaves it None
      so the user is forced to override; use `validate_maximum_security(config)` to
      verify at startup).
    - llm_router MUST be set by the caller for confidential-data routing.
    - Single concurrent session (no cross-user sharing).
    - Full audit logging.

    Example:

        config = Config(
            planner_llm=...,
            **{
                **safety_presets.maximum_security(),
                "security_policy_provider": MyPolicyProvider(),
                "llm_router": MyConfidentialRouter(),
            },
        )
        safety_presets.validate_maximum_security(config)
    """
    return {
        "auto_execute_threshold": None,
        "execution_env": ExecutionEnvironment.SERVER,
        "danger_rules": DangerRules.from_env(ExecutionEnvironment.SERVER),
        "security_policy_provider": None,
        "llm_router": None,
        "confirmation_handler": CLIConfirmationHandler(),
        "logger": FileLogger(path=audit_path),
        "auth_provider": APIKeyAuth(keys=api_keys or {}),
        "max_concurrent_sessions": 1,
    }


# ---------------------------------------------------------------------------
# Runtime validation
# ---------------------------------------------------------------------------


def validate_maximum_security(config: Any) -> None:
    """Assert that a Config carrying the maximum_security preset has the required overrides.

    Raises ValueError if `security_policy_provider` or a non-default `llm_router` is missing.
    Call once at startup, before Agent(config=config).
    """
    missing: list[str] = []
    if getattr(config, "security_policy_provider", None) is None:
        missing.append("security_policy_provider")

    router = getattr(config, "llm_router", None)
    # The default router is DefaultLLMRouter — insufficient for maximum_security,
    # because it doesn't route confidential data anywhere distinct.
    from yagura.llm.provider import DefaultLLMRouter

    if router is None or isinstance(router, DefaultLLMRouter):
        missing.append("llm_router (a custom LLMRouter is required; DefaultLLMRouter is not sufficient)")

    if missing:
        raise ValueError(
            "maximum_security preset requires user-supplied overrides:\n  - "
            + "\n  - ".join(missing)
            + "\nSee yagura.presets.safety.maximum_security for the required shape."
        )
