# yagura-starter-browser

Web automation agent. Playwright-driven browser + HTML/text scraping.

## Safety profile

Preset: `development` — navigation and data extraction are auto-executed;
interactive page actions require confirmation based on their DangerLevel:

| Tool | DangerLevel |
|---|---|
| `browser_navigate`, `browser_get_text`, `browser_screenshot`, `scrape_*` | READ |
| `browser_click`, `browser_fill`, `browser_select`, `browser_cookie_set` | MODIFY |
| `browser_submit` | **DESTRUCTIVE** — forms submissions may trigger payments, sign-ups, or other irreversible actions |

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
```

The first `playwright install` pulls the browser binaries (~300MB).
Subsequent runs reuse them.

## Example workflows

- "Take a full-page screenshot of https://example.com and save to /tmp/example.png"
- "Scrape the first table from https://en.wikipedia.org/wiki/List_of_OECD_countries"
- "Fill in the contact form on acme.dev with name 'Jane Test' and email
  'jane@example.com'" — the agent will stop at the submit button and ask
  you to confirm.

## Notes

- The Playwright browser is shared across tool invocations and torn down
  on exit (`main.py` calls `yagura_tools.browser.close()`).
- To reset the browser state between plans, call `close()` yourself or
  use headful mode by patching `_ensure_page` in the browser tools.
- Screenshots are returned as byte counts in the result; actual image
  bytes are written to disk when you pass `path=...`.
