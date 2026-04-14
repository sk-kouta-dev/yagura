"""Build the DevOps Agent using the `enterprise` preset.

Safety: SERVER environment — `write_file` escalates to DESTRUCTIVE,
every plan requires confirmation, full audit log.
"""

from __future__ import annotations

import os

from yagura import Agent, Config, safety_presets
from yagura.llm import AnthropicProvider

from tools import all_tools


def build_agent(audit_path: str = "./devops_audit.jsonl") -> Agent:
    planner = AnthropicProvider(
        model=os.environ.get("YAGURA_PLANNER_MODEL", "claude-sonnet-4-20250514"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    api_keys = _parse_api_keys(os.environ.get("YAGURA_API_KEYS", ""))
    agent = Agent(
        config=Config(
            planner_llm=planner,
            **safety_presets.enterprise(
                audit_path=audit_path,
                api_keys=api_keys,
                max_concurrent_sessions=5,
            ),
        )
    )
    agent.register_tools(all_tools)
    return agent


def _parse_api_keys(spec: str) -> dict[str, str]:
    """Parse `key1=alice,key2=bob` into a dict for APIKeyAuth."""
    if not spec:
        return {}
    out: dict[str, str] = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key, user = pair.split("=", 1)
        out[key.strip()] = user.strip()
    return out
