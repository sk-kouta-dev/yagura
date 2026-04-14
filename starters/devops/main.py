"""yagura-starter-devops — containers, Kubernetes, git workflows.

Run:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...
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
            "yagura-starter-devops — SERVER environment, every plan confirms.\n"
            "Try: 'list running containers', 'scale foo deployment to 3 replicas',"
            " 'push the current branch and open a PR'."
        ),
    )


if __name__ == "__main__":
    asyncio.run(_main())
