"""Browser + scraping + minimal local FS."""

from __future__ import annotations

from yagura_tools.browser import tools as _browser_tools
from yagura_tools.common.file import file_read, file_write
from yagura_tools.scraping import tools as _scraping_tools

# Keep only the non-OCR scraping tools here (OCR needs an extra install).
_web_tools = [t for t in _scraping_tools if t.name in {"scrape_webpage", "scrape_links", "scrape_tables"}]

all_tools = [
    file_read,
    file_write,          # For saving screenshots / scraped HTML.
    *_browser_tools,
    *_web_tools,
]
