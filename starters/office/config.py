"""Build the Office Agent.

Safety: `internal_tool` preset — READ auto-executes (searching inbox,
listing files), MODIFY/DESTRUCTIVE (sending email, posting Slack, deleting
Drive files) requires confirmation.
"""

from __future__ import annotations

import os

from yagura import Agent, Config, safety_presets
from yagura.llm import AnthropicProvider

from tools import all_tools


def build_agent(audit_path: str = "./office_audit.jsonl") -> Agent:
    planner = AnthropicProvider(
        model=os.environ.get("YAGURA_PLANNER_MODEL", "claude-sonnet-4-20250514"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    agent = Agent(
        config=Config(
            planner_llm=planner,
            **safety_presets.internal_tool(audit_path=audit_path),
        )
    )
    agent.register_tools(all_tools)
    return agent
