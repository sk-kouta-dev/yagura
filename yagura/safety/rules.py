"""DangerLevel, DangerRules, and ExecutionEnvironment.

Layer 1 of the 3-layer DangerAssessor: rule-based pattern matching
against tool name prefixes. Deterministic, zero-cost, instant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DangerLevel(Enum):
    """Ordered severity of an operation.

    The integer values establish ordering for threshold comparisons
    (see Config.auto_execute_threshold).
    """

    READ = 1
    MODIFY = 2
    DESTRUCTIVE = 3
    INSTALL = 4

    def __lt__(self, other: DangerLevel) -> bool:
        if not isinstance(other, DangerLevel):
            return NotImplemented
        return self.value < other.value

    def __le__(self, other: DangerLevel) -> bool:
        if not isinstance(other, DangerLevel):
            return NotImplemented
        return self.value <= other.value

    def __gt__(self, other: DangerLevel) -> bool:
        if not isinstance(other, DangerLevel):
            return NotImplemented
        return self.value > other.value

    def __ge__(self, other: DangerLevel) -> bool:
        if not isinstance(other, DangerLevel):
            return NotImplemented
        return self.value >= other.value


class ExecutionEnvironment(Enum):
    """Where the agent runs. Affects default DangerRules."""

    LOCAL = "local"
    DOCKER = "docker"
    SANDBOX = "sandbox"
    SERVER = "server"
    REMOTE_BACKEND = "remote"


@dataclass
class DangerRules:
    """Rule-based danger classification by tool name prefix.

    Longer prefixes take precedence. Explicit overrides beat prefix matching.
    """

    read_prefixes: list[str] = field(default_factory=lambda: ["search_", "list_", "get_", "read_", "grep_", "find_"])
    modify_prefixes: list[str] = field(default_factory=lambda: ["copy_", "rename_", "create_draft_", "create_folder_"])
    destructive_prefixes: list[str] = field(default_factory=lambda: ["delete_", "send_", "move_to_external_", "push_"])
    install_prefixes: list[str] = field(default_factory=lambda: ["install_", "system_config_", "package_"])
    overrides: dict[str, DangerLevel] = field(default_factory=dict)

    def classify(self, tool_name: str) -> DangerLevel | None:
        """Return the DangerLevel for a tool name, or None if no rule matches.

        Explicit overrides always win. Among prefix rules, the longest
        matching prefix wins (so "delete_folder_" > "delete_").
        """
        if tool_name in self.overrides:
            return self.overrides[tool_name]

        candidates: list[tuple[int, DangerLevel]] = []
        for prefix in self.read_prefixes:
            if tool_name.startswith(prefix):
                candidates.append((len(prefix), DangerLevel.READ))
        for prefix in self.modify_prefixes:
            if tool_name.startswith(prefix):
                candidates.append((len(prefix), DangerLevel.MODIFY))
        for prefix in self.destructive_prefixes:
            if tool_name.startswith(prefix):
                candidates.append((len(prefix), DangerLevel.DESTRUCTIVE))
        for prefix in self.install_prefixes:
            if tool_name.startswith(prefix):
                candidates.append((len(prefix), DangerLevel.INSTALL))

        if not candidates:
            return None
        # Longest prefix wins; ties prefer higher severity.
        candidates.sort(key=lambda c: (c[0], c[1].value))
        return candidates[-1][1]

    @classmethod
    def default(cls) -> DangerRules:
        """Standard defaults (LOCAL environment)."""
        return cls()

    @classmethod
    def from_env(cls, env: ExecutionEnvironment | str) -> DangerRules:
        """Return DangerRules adjusted for the execution environment.

        - SANDBOX: all operations capped at MODIFY
        - DOCKER: delete_/remove_ downgraded to MODIFY
        - SERVER: write_ escalated to DESTRUCTIVE
        - LOCAL / REMOTE_BACKEND: standard defaults
        """
        if isinstance(env, str):
            env = ExecutionEnvironment(env)
        rules = cls()
        if env is ExecutionEnvironment.SANDBOX:
            # Cap everything at MODIFY. Merge destructive + install prefixes into modify.
            rules.modify_prefixes = rules.modify_prefixes + rules.destructive_prefixes + rules.install_prefixes
            rules.destructive_prefixes = []
            rules.install_prefixes = []
        elif env is ExecutionEnvironment.DOCKER:
            # delete_ and remove_ downgraded from DESTRUCTIVE to MODIFY.
            rules.destructive_prefixes = [p for p in rules.destructive_prefixes if p not in ("delete_",)]
            rules.modify_prefixes = rules.modify_prefixes + ["delete_", "remove_"]
        elif env is ExecutionEnvironment.SERVER:
            # write_ escalates from MODIFY to DESTRUCTIVE (overwrites in prod are dangerous).
            rules.destructive_prefixes = rules.destructive_prefixes + ["write_"]
        # LOCAL and REMOTE_BACKEND use defaults.
        return rules
