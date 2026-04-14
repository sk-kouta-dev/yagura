"""http_request — Dynamic Tool (DangerAssessor Layer 2 inspects method)."""

from __future__ import annotations

import json as _json
from typing import Any
from urllib import error, parse, request

from yagura import Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


async def _http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> ToolResult:
    method = method.upper()
    data: bytes | None = None
    req_headers = dict(headers or {})
    if body is not None:
        if method in ("GET", "HEAD"):
            # Encode body as query string for GET-like methods.
            sep = "&" if "?" in url else "?"
            url = url + sep + parse.urlencode(body, doseq=True)
        else:
            data = _json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")

    req = request.Request(url, data=data, method=method, headers=req_headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            content_type = resp.headers.get("Content-Type", "")
            parsed: Any = payload.decode("utf-8", errors="replace")
            if content_type.startswith("application/json"):
                try:
                    parsed = _json.loads(parsed)
                except _json.JSONDecodeError:
                    pass
            return ToolResult(
                success=True,
                data={
                    "status": resp.status,
                    "headers": dict(resp.headers),
                    "body": parsed,
                },
            )
    except error.HTTPError as exc:
        return ToolResult(
            success=False,
            error=f"HTTP {exc.code}: {exc.reason}",
            data={"status": exc.code, "body": exc.read().decode("utf-8", errors="replace")},
        )
    except error.URLError as exc:
        return ToolResult(success=False, error=f"URL error: {exc.reason}")


http_request = Tool(
    name="http_request",
    description="Make an HTTP request and return the status/headers/body.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                "default": "GET",
            },
            "headers": {"type": "object", "description": "Request headers."},
            "body": {"type": "object", "description": "Request body (JSON-encoded for non-GET)."},
            "timeout": {"type": "integer", "default": 30},
        },
        "required": ["url"],
    },
    handler=_http_request,
    # No danger_level: Layer 2 reads `method` to decide (GET=READ, POST/PUT=MODIFY, DELETE=DESTRUCTIVE).
    requires_llm=True,
    default_reliability=ReliabilityLevel.REFERENCE,
    tags=["common", "http"],
)


tools: list[Tool] = [http_request]
