"""yagura-tools-notion — page/db/block operations via notion-client."""

from __future__ import annotations

import os
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _client(token: str | None = None):
    try:
        from notion_client import Client  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-notion requires 'notion-client'") from exc
    return Client(auth=token or os.environ.get("NOTION_TOKEN"))


def _notion_page_search(query: str, token: str | None = None) -> ToolResult:
    resp = _client(token).search(query=query)
    results = [{"id": r["id"], "type": r.get("object"), "title": _extract_title(r)} for r in resp.get("results", [])]
    return ToolResult(success=True, data={"results": results})


def _notion_page_get(page_id: str, token: str | None = None) -> ToolResult:
    page = _client(token).pages.retrieve(page_id)
    blocks = _client(token).blocks.children.list(page_id)
    return ToolResult(
        success=True,
        data={"page": page, "blocks": blocks.get("results", [])},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _notion_page_create(parent_id: str, title: str, content: list[dict] | None = None, token: str | None = None) -> ToolResult:
    page = _client(token).pages.create(
        parent={"page_id": parent_id},
        properties={"title": [{"text": {"content": title}}]},
        children=content or [],
    )
    return ToolResult(success=True, data={"id": page["id"], "url": page.get("url")})


def _notion_page_update(page_id: str, properties: dict[str, Any], token: str | None = None) -> ToolResult:
    page = _client(token).pages.update(page_id=page_id, properties=properties)
    return ToolResult(success=True, data={"id": page["id"]})


def _notion_page_delete(page_id: str, token: str | None = None) -> ToolResult:
    page = _client(token).pages.update(page_id=page_id, archived=True)
    return ToolResult(success=True, data={"id": page["id"], "archived": True})


def _notion_db_query(database_id: str, filter: dict | None = None, sorts: list | None = None, token: str | None = None) -> ToolResult:
    kwargs: dict[str, Any] = {"database_id": database_id}
    if filter:
        kwargs["filter"] = filter
    if sorts:
        kwargs["sorts"] = sorts
    resp = _client(token).databases.query(**kwargs)
    return ToolResult(
        success=True,
        data={"results": resp.get("results", [])},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _notion_db_add_row(database_id: str, properties: dict[str, Any], token: str | None = None) -> ToolResult:
    page = _client(token).pages.create(parent={"database_id": database_id}, properties=properties)
    return ToolResult(success=True, data={"id": page["id"]})


def _notion_block_append(page_id: str, children: list[dict], token: str | None = None) -> ToolResult:
    resp = _client(token).blocks.children.append(page_id, children=children)
    return ToolResult(success=True, data={"added": len(resp.get("results", []))})


def _notion_block_update(block_id: str, content: dict[str, Any], token: str | None = None) -> ToolResult:
    block = _client(token).blocks.update(block_id=block_id, **content)
    return ToolResult(success=True, data={"id": block["id"]})


def _notion_block_delete(block_id: str, token: str | None = None) -> ToolResult:
    _client(token).blocks.delete(block_id)
    return ToolResult(success=True, data={"id": block_id, "deleted": True})


def _extract_title(obj: dict) -> str:
    props = obj.get("properties") or {}
    for p in props.values():
        if p.get("type") == "title":
            return "".join(t["plain_text"] for t in p.get("title", []))
    return obj.get("url", obj.get("id", ""))


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name, description=description,
        parameters={"type": "object", "properties": props, "required": required},
        handler=handler, danger_level=danger, tags=["notion"], **extra,
    )


_TOKEN = {"type": "string", "description": "Notion integration token (falls back to $NOTION_TOKEN)."}


tools: list[Tool] = [
    _T("notion_page_search", "Search Notion pages/databases.",
        {"query": {"type": "string"}, "token": _TOKEN},
        ["query"], _notion_page_search, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("notion_page_get", "Get a Notion page and its blocks.",
        {"page_id": {"type": "string"}, "token": _TOKEN},
        ["page_id"], _notion_page_get, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("notion_page_create", "Create a Notion page.",
        {"parent_id": {"type": "string"}, "title": {"type": "string"}, "content": {"type": "array"}, "token": _TOKEN},
        ["parent_id", "title"], _notion_page_create, DangerLevel.MODIFY),
    _T("notion_page_update", "Update page properties.",
        {"page_id": {"type": "string"}, "properties": {"type": "object"}, "token": _TOKEN},
        ["page_id", "properties"], _notion_page_update, DangerLevel.MODIFY),
    _T("notion_page_delete", "Archive (delete) a page. DESTRUCTIVE.",
        {"page_id": {"type": "string"}, "token": _TOKEN},
        ["page_id"], _notion_page_delete, DangerLevel.DESTRUCTIVE),
    _T("notion_db_query", "Query a Notion database.",
        {"database_id": {"type": "string"}, "filter": {"type": "object"}, "sorts": {"type": "array"}, "token": _TOKEN},
        ["database_id"], _notion_db_query, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("notion_db_add_row", "Add a row to a Notion database.",
        {"database_id": {"type": "string"}, "properties": {"type": "object"}, "token": _TOKEN},
        ["database_id", "properties"], _notion_db_add_row, DangerLevel.MODIFY),
    _T("notion_block_append", "Append blocks to a page.",
        {"page_id": {"type": "string"}, "children": {"type": "array"}, "token": _TOKEN},
        ["page_id", "children"], _notion_block_append, DangerLevel.MODIFY),
    _T("notion_block_update", "Update a block.",
        {"block_id": {"type": "string"}, "content": {"type": "object"}, "token": _TOKEN},
        ["block_id", "content"], _notion_block_update, DangerLevel.MODIFY),
    _T("notion_block_delete", "Delete a block. DESTRUCTIVE.",
        {"block_id": {"type": "string"}, "token": _TOKEN},
        ["block_id"], _notion_block_delete, DangerLevel.DESTRUCTIVE),
]

__all__ = ["tools"]
