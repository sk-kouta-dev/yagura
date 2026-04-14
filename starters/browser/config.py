"""Build the browser-automation Agent.

Safety: `development` preset — navigate/click/fill auto-execute, but
`browser_submit` is DESTRUCTIVE (irreversible side effects like payments,
registrations) and always requires confirmation.
"""

from __future__ import annotations

import os

from yagura import Agent, Config, safety_presets
from yagura.llm import AnthropicProvider

from tools import all_tools


def build_agent() -> Agent:
    planner = AnthropicProvider(
        model=os.environ.get("YAGURA_PLANNER_MODEL", "claude-sonnet-4-20250514"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    agent = Agent(
        config=Config(
            planner_llm=planner,
            **safety_presets.development(),
        )
    )
    agent.register_tools(all_tools)
    return agent
