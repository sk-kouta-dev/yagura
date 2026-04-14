"""yagura-starter-browser — web automation agent (Playwright + scraping).

First-time setup:
    pip install -r requirements.txt
    playwright install chromium
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

from yagura_tools.browser import close as close_browser  # noqa: E402

from config import build_agent  # noqa: E402


async def _main() -> None:
    agent = build_agent()
    try:
        await run_repl(
            agent,
            welcome=(
                "yagura-starter-browser — a Playwright-driven browser assistant.\n"
                "Try: 'take a screenshot of example.com', 'scrape the pricing page"
                " of acme.dev', 'fill out the contact form on mysite.com'."
            ),
        )
    finally:
        # Tear the shared browser down cleanly.
        await close_browser()


if __name__ == "__main__":
    asyncio.run(_main())
