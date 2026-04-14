"""Config defaults + validation — P1."""

from __future__ import annotations

import pytest

from tests.conftest import MockLLMProvider
from yagura import Config, DangerLevel
from yagura.auth.noauth import NoAuth
from yagura.confirmation.cli import CLIConfirmationHandler
from yagura.llm.provider import DefaultLLMRouter
from yagura.logging.null import NullLogger
from yagura.session.memory import InMemoryStateStore


def test_config_requires_planner_llm() -> None:
    with pytest.raises(ValueError):
        Config()  # type: ignore[call-arg]


def test_config_defaults_are_sane() -> None:
    llm = MockLLMProvider()
    cfg = Config(planner_llm=llm)
    assert isinstance(cfg.confirmation_handler, CLIConfirmationHandler)
    assert isinstance(cfg.auth_provider, NoAuth)
    assert isinstance(cfg.state_store, InMemoryStateStore)
    assert isinstance(cfg.logger, NullLogger)
    assert cfg.auto_execute_threshold is DangerLevel.READ
    assert cfg.max_concurrent_sessions == 1


def test_executor_llm_falls_back_to_planner() -> None:
    planner = MockLLMProvider()
    cfg = Config(planner_llm=planner)
    assert cfg.effective_executor_llm is planner


def test_executor_llm_used_when_set() -> None:
    planner = MockLLMProvider()
    executor = MockLLMProvider()
    cfg = Config(planner_llm=planner, executor_llm=executor)
    assert cfg.effective_executor_llm is executor


def test_default_llm_router_is_default() -> None:
    cfg = Config(planner_llm=MockLLMProvider())
    assert isinstance(cfg.llm_router, DefaultLLMRouter)
