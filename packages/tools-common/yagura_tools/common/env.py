"""env_get — read environment variables."""

from __future__ import annotations

import os

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _env_get(name: str) -> ToolResult:
    value = os.environ.get(name)
    if value is None:
        return ToolResult(success=False, error=f"Environment variable not set: {name}")
    return ToolResult(success=True, data={"name": name, "value": value})


env_get = Tool(
    name="env_get",
    description="Get an environment variable.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    handler=_env_get,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["common", "env"],
)


tools: list[Tool] = [env_get]
