"""Safety presets for Yagura.

from yagura.presets import safety_presets

config = Config(
    planner_llm=AnthropicProvider(model="claude-sonnet-4-20250514"),
    **safety_presets.enterprise(),
)
"""

from __future__ import annotations

from yagura.presets import safety as safety_presets
from yagura.presets.safety import (
    development,
    enterprise,
    internal_tool,
    maximum_security,
    sandbox,
    validate_maximum_security,
)

__all__ = [
    "development",
    "enterprise",
    "internal_tool",
    "maximum_security",
    "safety_presets",
    "sandbox",
    "validate_maximum_security",
]
