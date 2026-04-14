"""yagura-tools-browser — Playwright-based browser automation.

A single persistent browser context is shared across tool invocations.
Use `browser_close` (not a registered tool — call the module helper
directly) if you need to reset state between plans.
"""

from __future__ import annotations

from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel

_playwright = None
_browser = None
_page = None


async def _ensure_page() -> Any:
    global _playwright, _browser, _page
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "yagura-tools-browser requires 'playwright'. Run: pip install playwright && playwright install"
        ) from exc
    if _page is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch()
        _page = await _browser.new_page()
    return _page


async def close() -> None:
    """Shut down the shared browser. Call between plans if you need a fresh session."""
    global _playwright, _browser, _page
    if _browser is not None:
        await _browser.close()
    if _playwright is not None:
        await _playwright.stop()
    _playwright = _browser = _page = None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _browser_navigate(url: str) -> ToolResult:
    page = await _ensure_page()
    response = await page.goto(url)
    return ToolResult(
        success=response is None or response.ok,
        data={"url": page.url, "status": response.status if response else None},
    )


async def _browser_screenshot(path: str | None = None, full_page: bool = False) -> ToolResult:
    page = await _ensure_page()
    image = await page.screenshot(path=path, full_page=full_page)
    return ToolResult(success=True, data={"path": path, "bytes": len(image)})


async def _browser_click(selector: str) -> ToolResult:
    page = await _ensure_page()
    await page.click(selector)
    return ToolResult(success=True, data={"clicked": selector})


async def _browser_fill(selector: str, value: str) -> ToolResult:
    page = await _ensure_page()
    await page.fill(selector, value)
    return ToolResult(success=True, data={"selector": selector, "length": len(value)})


async def _browser_submit(selector: str | None = None) -> ToolResult:
    page = await _ensure_page()
    if selector:
        await page.click(selector)
    else:
        await page.keyboard.press("Enter")
    return ToolResult(success=True, data={"submitted": selector or "<Enter>"})


async def _browser_get_text(selector: str | None = None) -> ToolResult:
    page = await _ensure_page()
    text = await page.inner_text(selector) if selector else await page.content()
    return ToolResult(success=True, data={"text": text}, reliability=ReliabilityLevel.REFERENCE)


async def _browser_get_html(selector: str | None = None) -> ToolResult:
    page = await _ensure_page()
    if selector:
        html = await page.inner_html(selector)
    else:
        html = await page.content()
    return ToolResult(success=True, data={"html": html}, reliability=ReliabilityLevel.REFERENCE)


async def _browser_wait(selector: str | None = None, timeout: int = 30000) -> ToolResult:
    page = await _ensure_page()
    if selector:
        await page.wait_for_selector(selector, timeout=timeout)
    else:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    return ToolResult(success=True, data={"waited_for": selector or "networkidle"})


async def _browser_select(selector: str, value: str) -> ToolResult:
    page = await _ensure_page()
    await page.select_option(selector, value)
    return ToolResult(success=True, data={"selector": selector, "value": value})


async def _browser_cookie_get(name: str | None = None) -> ToolResult:
    page = await _ensure_page()
    context = page.context
    cookies = await context.cookies()
    if name:
        cookies = [c for c in cookies if c.get("name") == name]
    return ToolResult(success=True, data={"cookies": cookies})


async def _browser_cookie_set(name: str, value: str, domain: str | None = None, path: str = "/") -> ToolResult:
    page = await _ensure_page()
    await page.context.add_cookies(
        [{"name": name, "value": value, "url": page.url if not domain else f"https://{domain}{path}"}]
    )
    return ToolResult(success=True, data={"name": name})


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


browser_navigate = Tool(
    name="browser_navigate",
    description="Navigate to a URL.",
    parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    handler=_browser_navigate,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.REFERENCE,
    tags=["browser"],
)

browser_screenshot = Tool(
    name="browser_screenshot",
    description="Take a screenshot of the current page.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "full_page": {"type": "boolean", "default": False},
        },
        "required": [],
    },
    handler=_browser_screenshot,
    danger_level=DangerLevel.READ,
    tags=["browser"],
)

browser_click = Tool(
    name="browser_click",
    description="Click an element by CSS selector.",
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}},
        "required": ["selector"],
    },
    handler=_browser_click,
    danger_level=DangerLevel.MODIFY,
    tags=["browser"],
)

browser_fill = Tool(
    name="browser_fill",
    description="Fill an input field.",
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}, "value": {"type": "string"}},
        "required": ["selector", "value"],
    },
    handler=_browser_fill,
    danger_level=DangerLevel.MODIFY,
    tags=["browser"],
)

browser_submit = Tool(
    name="browser_submit",
    description=(
        "Submit a form. DESTRUCTIVE because form submission may trigger "
        "irreversible actions (payments, registrations, etc.)."
    ),
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}},
        "required": [],
    },
    handler=_browser_submit,
    danger_level=DangerLevel.DESTRUCTIVE,
    tags=["browser"],
)

browser_get_text = Tool(
    name="browser_get_text",
    description="Extract text from the page (or from a specific element).",
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}},
        "required": [],
    },
    handler=_browser_get_text,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.REFERENCE,
    tags=["browser"],
)

browser_get_html = Tool(
    name="browser_get_html",
    description="Get the page HTML (or an element's inner HTML).",
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}},
        "required": [],
    },
    handler=_browser_get_html,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.REFERENCE,
    tags=["browser"],
)

browser_wait = Tool(
    name="browser_wait",
    description="Wait for a selector to appear or for network idle.",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string"},
            "timeout": {"type": "integer", "default": 30000},
        },
        "required": [],
    },
    handler=_browser_wait,
    danger_level=DangerLevel.READ,
    tags=["browser"],
)

browser_select = Tool(
    name="browser_select",
    description="Select a dropdown option.",
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}, "value": {"type": "string"}},
        "required": ["selector", "value"],
    },
    handler=_browser_select,
    danger_level=DangerLevel.MODIFY,
    tags=["browser"],
)

browser_cookie_get = Tool(
    name="browser_cookie_get",
    description="Get cookies from the current context.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": [],
    },
    handler=_browser_cookie_get,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["browser"],
)

browser_cookie_set = Tool(
    name="browser_cookie_set",
    description="Set a cookie in the current context.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "value": {"type": "string"},
            "domain": {"type": "string"},
            "path": {"type": "string", "default": "/"},
        },
        "required": ["name", "value"],
    },
    handler=_browser_cookie_set,
    danger_level=DangerLevel.MODIFY,
    tags=["browser"],
)


tools: list[Tool] = [
    browser_navigate,
    browser_screenshot,
    browser_click,
    browser_fill,
    browser_submit,
    browser_get_text,
    browser_get_html,
    browser_wait,
    browser_select,
    browser_cookie_get,
    browser_cookie_set,
]

__all__ = ["tools", "close"]
