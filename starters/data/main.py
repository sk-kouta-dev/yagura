"""yagura-starter-data — data analysis agent.

Run:
    pip install -r requirements.txt
    python init_db.py        # creates sample_data/sample.db
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
            "yagura-starter-data — query, summarize, and explore your SQL data.\n"
            "Sample database: sample_data/sample.db (connection_string=sqlite:///sample_data/sample.db)\n"
            "Try: 'list tables', 'show top 5 customers by revenue',"
            " 'summarize sales trends for the last 30 days'."
        ),
    )


if __name__ == "__main__":
    asyncio.run(_main())
