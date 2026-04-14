"""RuleEngine — manages rules, starts triggers, runs pre-approved plans."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from yagura.errors import RuleConflictError, RuleError
from yagura.rules.rule import Rule

if TYPE_CHECKING:
    from yagura.agent import Agent

_logger = logging.getLogger(__name__)


class RuleEngine:
    """Holds Rules, starts their triggers, and runs plans on fire events.

    Rules are pre-approved automation — the ConfirmationHandler the engine
    uses is typically AutoApproveHandler. DangerAssessor still applies,
    so DESTRUCTIVE operations can still halt via the policy chain if the
    user configured one.
    """

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self._rules: dict[str, Rule] = {}
        self._started: set[str] = set()

    # --- Management -------------------------------------------------------

    def add_rule(self, rule: Rule) -> None:
        self._check_conflict(rule)
        self._rules[rule.id] = rule

    def remove_rule(self, rule_id: str) -> None:
        if rule_id not in self._rules:
            raise RuleError(f"Rule '{rule_id}' not found")
        if rule_id in self._started:
            # Best effort: callers should call stop() before remove_rule.
            raise RuleError(f"Rule '{rule_id}' is running; stop it first")
        del self._rules[rule_id]

    def list_rules(self) -> list[Rule]:
        return list(self._rules.values())

    def get_rule(self, rule_id: str) -> Rule:
        if rule_id not in self._rules:
            raise RuleError(f"Rule '{rule_id}' not found")
        return self._rules[rule_id]

    # --- Lifecycle --------------------------------------------------------

    async def start(self) -> None:
        for rule in self._rules.values():
            if rule.enabled and rule.id not in self._started:
                await rule.trigger.start(self._make_callback(rule))
                self._started.add(rule.id)

    async def stop(self) -> None:
        for rule_id in list(self._started):
            rule = self._rules.get(rule_id)
            if rule is not None:
                await rule.trigger.stop()
            self._started.discard(rule_id)

    def _make_callback(self, rule: Rule):
        async def _callback(payload: dict[str, Any]) -> None:
            try:
                await self.agent.run_as_rule(rule, payload)
            except Exception:  # noqa: BLE001
                _logger.exception("Rule %s failed", rule.name)

        return _callback

    # --- Conflict detection -----------------------------------------------

    def _check_conflict(self, new_rule: Rule) -> None:
        """Lightweight conflict check: same id → error; duplicate name → warning.

        Semantic conflict detection (e.g., "delete old files" vs "archive old
        files" on the same trigger) is deferred to a user-supplied hook so we
        don't silently burn planner tokens on every rule registration.
        """
        if new_rule.id in self._rules:
            raise RuleConflictError(f"Rule with id '{new_rule.id}' already registered")
        for existing in self._rules.values():
            if existing.name == new_rule.name:
                _logger.warning(
                    "Rule name '%s' is already used by rule %s",
                    new_rule.name,
                    existing.id,
                )
