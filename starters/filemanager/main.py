"""yagura-starter-filemanager — file organization agent.

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
            "yagura-starter-filemanager — organize files by natural-language request.\n"
            "Try: 'list all PDFs under ~/Documents', 'extract text from report.pdf',"
            " 'move duplicates to /tmp/dup'."
        ),
    )


if __name__ == "__main__":
    asyncio.run(_main())
