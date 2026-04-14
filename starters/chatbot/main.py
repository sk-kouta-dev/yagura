"""yagura-starter-chatbot — basic conversational agent with a CLI interface.

Run:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...
    python main.py
"""

from __future__ import annotations

import asyncio
import os
import sys

# Import the shared CLI loop. When you copy this starter out of the monorepo,
# inline `run_repl` below or vendor `_shared/cli.py` alongside.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_shared"))
import bootstrap  # noqa: E402 F401 — monorepo-mode sys.path setup for yagura_tools.*
from cli import run_repl  # noqa: E402

from config import build_agent  # noqa: E402


async def _main() -> None:
    agent = build_agent()
    await run_repl(
        agent,
        welcome=(
            "yagura-starter-chatbot — powered by yagura-agent.\n"
            "Ask me to list files, read text, fetch URLs, or run shell commands."
        ),
    )


if __name__ == "__main__":
    asyncio.run(_main())
