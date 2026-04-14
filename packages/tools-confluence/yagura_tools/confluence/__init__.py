"""yagura-tools-confluence — Confluence page/attachment/space operations.

Credentials: `CONFLUENCE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`
environment variables, or pass them per-call.
"""

from __future__ import annotations

import os
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _client(url: str | None = None, email: str | None = None, token: str | None = None):
    try:
        from atlassian import Confluence  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-confluence requires 'atlassian-python-api'") from exc
    url = url or os.environ.get("CONFLUENCE_URL")
    email = email or os.environ.get("CONFLUENCE_EMAIL")
    token = token or os.environ.get("CONFLUENCE_API_TOKEN")
    if not (url and email and token):
        raise RuntimeError("Set CONFLUENCE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN")
    return Confluence(url=url, username=email, password=token, cloud=True)


def _confluence_page_search(cql: str, max_results: int = 25, **auth) -> ToolResult:
    resp = _client(**auth).cql(cql, limit=max_results)
    return ToolResult(
        success=True,
        data={"results": resp.get("results", [])},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _confluence_page_get(page_id: str, **auth) -> ToolResult:
    page = _client(**auth).get_page_by_id(page_id, expand="body.storage,version")
    return ToolResult(
        success=True,
        data={
            "id": page["id"],
            "title": page["title"],
            "body": page.get("body", {}).get("storage", {}).get("value", ""),
            "version": page.get("version", {}).get("number"),
        },
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _confluence_page_create(space_key: str, title: str, body: str, parent_id: str | None = None, **auth) -> ToolResult:
    page = _client(**auth).create_page(space=space_key, title=title, body=body, parent_id=parent_id)
    return ToolResult(success=True, data={"id": page["id"], "title": title})


def _confluence_page_update(page_id: str, title: str | None = None, body: str | None = None, **auth) -> ToolResult:
    client = _client(**auth)
    current = client.get_page_by_id(page_id, expand="version")
    updated = client.update_page(
        page_id=page_id,
        title=title or current["title"],
        body=body or "",
    )
    return ToolResult(success=True, data={"id": updated["id"]})


def _confluence_page_delete(page_id: str, **auth) -> ToolResult:
    _client(**auth).remove_page(page_id)
    return ToolResult(success=True, data={"id": page_id, "deleted": True})


def _confluence_attachment_upload(page_id: str, file_path: str, **auth) -> ToolResult:
    result = _client(**auth).attach_file(file_path, page_id=page_id)
    return ToolResult(success=True, data={"id": result.get("id"), "title": result.get("title")})


def _confluence_attachment_list(page_id: str, **auth) -> ToolResult:
    resp = _client(**auth).get_attachments_from_content(page_id)
    return ToolResult(
        success=True,
        data={
            "attachments": [
                {"id": a["id"], "title": a.get("title"), "size": a.get("extensions", {}).get("fileSize")}
                for a in resp.get("results", [])
            ],
        },
    )


def _confluence_space_list(type: str | None = None, **auth) -> ToolResult:
    spaces = _client(**auth).get_all_spaces(space_type=type)
    return ToolResult(
        success=True,
        data={
            "spaces": [
                {"key": s["key"], "name": s["name"], "type": s.get("type")}
                for s in spaces.get("results", [])
            ],
        },
    )


_AUTH = {
    "url": {"type": "string"},
    "email": {"type": "string"},
    "token": {"type": "string"},
}


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name, description=description,
        parameters={"type": "object", "properties": {**_AUTH, **props}, "required": required},
        handler=handler, danger_level=danger, tags=["confluence"], **extra,
    )


tools: list[Tool] = [
    _T("confluence_page_search", "Search pages via CQL.",
        {"cql": {"type": "string"}, "max_results": {"type": "integer", "default": 25}},
        ["cql"], _confluence_page_search, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("confluence_page_get", "Get a page by id.",
        {"page_id": {"type": "string"}},
        ["page_id"], _confluence_page_get, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("confluence_page_create", "Create a page.",
        {"space_key": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}, "parent_id": {"type": "string"}},
        ["space_key", "title", "body"], _confluence_page_create, DangerLevel.MODIFY),
    _T("confluence_page_update", "Update a page.",
        {"page_id": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}},
        ["page_id"], _confluence_page_update, DangerLevel.MODIFY),
    _T("confluence_page_delete", "Delete a page. DESTRUCTIVE.",
        {"page_id": {"type": "string"}},
        ["page_id"], _confluence_page_delete, DangerLevel.DESTRUCTIVE),
    _T("confluence_attachment_upload", "Attach a file to a page.",
        {"page_id": {"type": "string"}, "file_path": {"type": "string"}},
        ["page_id", "file_path"], _confluence_attachment_upload, DangerLevel.MODIFY),
    _T("confluence_attachment_list", "List attachments on a page.",
        {"page_id": {"type": "string"}},
        ["page_id"], _confluence_attachment_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("confluence_space_list", "List spaces.",
        {"type": {"type": "string"}},
        [], _confluence_space_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
]

__all__ = ["tools"]
