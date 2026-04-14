"""Config — the single entry point for wiring the framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from yagura.auth.noauth import NoAuth
from yagura.auth.provider import AuthProvider
from yagura.confirmation.cli import CLIConfirmationHandler
from yagura.confirmation.handler import ConfirmationHandler
from yagura.llm.provider import DefaultLLMRouter, LLMProvider, LLMRouter
from yagura.logging.logger import AuditLogger
from yagura.logging.null import NullLogger
from yagura.safety.policy import SecurityPolicyProvider
from yagura.safety.rules import DangerLevel, DangerRules, ExecutionEnvironment
from yagura.session.memory import InMemoryStateStore
from yagura.session.store import StateStore
from yagura.tools.executor import ClientExecutor, RemoteExecutor

if TYPE_CHECKING:
    from yagura.rules.rule import Rule


@dataclass
class Config:
    """All environment-dependent configuration in one place.

    Only `planner_llm` is required. Every other field has a sensible
    default so minimal-setup usage fits in ~10 lines (see README example).
    """

    # --- LLM providers ----------------------------------------------------
    planner_llm: LLMProvider | None = None
    executor_llm: LLMProvider | None = None
    fallback_llm: LLMProvider | None = None
    llm_router: LLMRouter | None = None

    # --- Safety -----------------------------------------------------------
    danger_rules: DangerRules = field(default_factory=DangerRules.default)
    security_policy_provider: SecurityPolicyProvider | None = None
    confirmation_handler: ConfirmationHandler = field(default_factory=CLIConfirmationHandler)
    auto_execute_threshold: DangerLevel | None = DangerLevel.READ

    # --- Execution environment -------------------------------------------
    execution_env: ExecutionEnvironment = ExecutionEnvironment.LOCAL
    remote_executor: RemoteExecutor | None = None
    client_executor: ClientExecutor | None = None

    # --- Auth -------------------------------------------------------------
    auth_provider: AuthProvider = field(default_factory=NoAuth)

    # --- Persistence ------------------------------------------------------
    state_store: StateStore = field(default_factory=InMemoryStateStore)

    # --- Logging / audit --------------------------------------------------
    logger: AuditLogger = field(default_factory=NullLogger)

    # --- Rules ------------------------------------------------------------
    rules: list[Rule] = field(default_factory=list)

    # --- Concurrency ------------------------------------------------------
    max_concurrent_sessions: int = 1

    # --- Safety assessment knobs -----------------------------------------
    assessment_confidence_threshold: float = 0.8

    def __post_init__(self) -> None:
        if self.planner_llm is None:
            raise ValueError(
                "Config.planner_llm is required. "
                "Supply an LLMProvider (AnthropicProvider, OpenAIProvider, OllamaProvider, or custom)."
            )
        # Default router: uses executor_llm with planner_llm fallback.
        if self.llm_router is None:
            self.llm_router = DefaultLLMRouter(
                executor_llm=self.executor_llm,
                planner_llm=self.planner_llm,
            )

    # --- Helpers ----------------------------------------------------------

    @property
    def effective_executor_llm(self) -> LLMProvider:
        """Executor LLM with planner_llm as fallback."""
        return self.executor_llm or self.planner_llm  # type: ignore[return-value]
