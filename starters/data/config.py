"""Build the data analysis Agent.

Safety: `internal_tool` preset. SELECT queries auto-execute. INSERT/UPDATE
require confirmation. DROP/DELETE are always DESTRUCTIVE — DangerAssessor
Layer 2 inspects the SQL at runtime.
"""

from __future__ import annotations

import os

from yagura import Agent, Config, safety_presets
from yagura.llm import AnthropicProvider

from tools import all_tools


def build_agent(audit_path: str = "./data_audit.jsonl") -> Agent:
    planner = AnthropicProvider(
        model=os.environ.get("YAGURA_PLANNER_MODEL", "claude-sonnet-4-20250514"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    # executor_llm is used by Dynamic Tools (db_query, db_natural_query, llm_*).
    executor = planner  # same model; split if you want a cheaper executor.
    agent = Agent(
        config=Config(
            planner_llm=planner,
            executor_llm=executor,
            **safety_presets.internal_tool(audit_path=audit_path),
        )
    )
    agent.register_tools(all_tools)
    return agent
