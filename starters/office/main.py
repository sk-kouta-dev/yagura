"""yagura-starter-office — Google Workspace + Slack office assistant.

Run:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...
    export GOOGLE_APPLICATION_CREDENTIALS=./credentials/service-account.json
    export SLACK_BOT_TOKEN=xoxb-...
    python main.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_shared"))
import bootstrap  # noqa: E402 F401 — monorepo-mode sys.path setup for yagura_tools.*
from cli import run_repl  # noqa: E402

from config import build_agent  # noqa: E402


async def _main() -> None:
    agent = build_agent()
    await run_repl(
        agent,
        welcome=(
            "yagura-starter-office — Gmail + Drive + Calendar + Slack.\n"
            "Try: 'search emails about Q4 budget', 'create a calendar event"
            " tomorrow at 10am with Bob', 'post the meeting notes in #general'."
        ),
    )


if __name__ == "__main__":
    asyncio.run(_main())
