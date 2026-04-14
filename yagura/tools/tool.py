"""Tool dataclass, ExecutionTarget, and ToolResult."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from yagura.safety.reliability import ReliabilityLevel
from yagura.safety.rules import DangerLevel


class ExecutionTarget(Enum):
    """Where a tool's handler runs."""

    LOCAL = "local"
    REMOTE = "remote"
    CLIENT = "client"


@dataclass
class Tool:
    """A capability the agent can invoke.

    The framework has zero built-in tools. All capabilities come from
    user-registered Tools. The LLM selects tools based on their
    `name` + `description` + `parameters` JSON Schema.

    Execution modes (mutually orthogonal):
      - Static (default, requires_llm=False, llm_task_template=None):
        handler is called directly with resolved params.
      - Dynamic (requires_llm=True, llm_task_template=None):
        executor LLM transforms params before the handler runs.
      - LLM-as-tool (llm_task_template is not None):
        handler is NOT invoked. The executor LLM receives the rendered
        template and the returned text becomes the ToolResult data.
        Use for `summarize`, `translate`, `classify`, etc. where the
        tool IS the LLM call.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any] | None = None
    danger_level: DangerLevel | None = None
    execution_target: ExecutionTarget = ExecutionTarget.LOCAL
    tags: list[str] = field(default_factory=list)
    default_reliability: ReliabilityLevel = ReliabilityLevel.REFERENCE
    requires_llm: bool = False
    # When set, the executor LLM runs the rendered template directly. The
    # string may contain Python format placeholders (e.g. "Summarize: {text}");
    # resolved step params are substituted in. The LLM's text output is wrapped
    # in ToolResult.data under `output_key` (default "output"). The tool's
    # handler is ignored.
    llm_task_template: str | None = None
    llm_output_key: str = "output"

    def to_schema(self) -> dict[str, Any]:
        """Return the tool as a JSON Schema suitable for LLM tool-use."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


@dataclass
class ToolResult:
    """The return value of a tool invocation.

    `reliability`, when set, overrides the Tool.default_reliability for
    this particular result.
    """

    success: bool
    data: Any = None
    reliability: ReliabilityLevel | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
