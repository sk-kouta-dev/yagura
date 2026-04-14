"""yagura-tools-slack — send/search/channels/files.

Auth: set `SLACK_BOT_TOKEN` (xoxb-...) in the environment, or pass `token`.
"""

from __future__ import annotations

import os
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _client(token: str | None = None):
    try:
        from slack_sdk import WebClient  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-slack requires 'slack-sdk'") from exc
    tok = token or os.environ.get("SLACK_BOT_TOKEN")
    if not tok:
        raise RuntimeError("Set SLACK_BOT_TOKEN or pass token= to the tool call")
    return WebClient(token=tok)


def _slack_send(channel: str, text: str, thread_ts: str | None = None, token: str | None = None) -> ToolResult:
    resp = _client(token).chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
    return ToolResult(success=resp["ok"], data={"ts": resp.get("ts"), "channel": resp.get("channel")})


def _slack_search(query: str, sort: str = "timestamp", count: int = 20, token: str | None = None) -> ToolResult:
    resp = _client(token).search_messages(query=query, sort=sort, count=count)
    matches = resp.get("messages", {}).get("matches", [])
    return ToolResult(
        success=resp["ok"],
        data={"matches": matches, "count": len(matches)},
        reliability=ReliabilityLevel.REFERENCE,
    )


def _slack_channel_list(types: str = "public_channel", limit: int = 200, token: str | None = None) -> ToolResult:
    resp = _client(token).conversations_list(types=types, limit=limit)
    return ToolResult(
        success=resp["ok"],
        data={"channels": [{"id": c["id"], "name": c["name"]} for c in resp.get("channels", [])]},
    )


def _slack_channel_create(name: str, is_private: bool = False, token: str | None = None) -> ToolResult:
    resp = _client(token).conversations_create(name=name, is_private=is_private)
    return ToolResult(success=resp["ok"], data={"id": resp["channel"]["id"], "name": resp["channel"]["name"]})


def _slack_reaction_add(channel: str, timestamp: str, name: str, token: str | None = None) -> ToolResult:
    resp = _client(token).reactions_add(channel=channel, timestamp=timestamp, name=name)
    return ToolResult(success=resp["ok"], data={"reaction": name})


def _slack_file_upload(channel: str, file_path: str, title: str | None = None, token: str | None = None) -> ToolResult:
    resp = _client(token).files_upload_v2(channel=channel, file=file_path, title=title)
    return ToolResult(success=resp["ok"], data={"file_id": resp.get("file", {}).get("id")})


def _slack_user_list(limit: int = 200, token: str | None = None) -> ToolResult:
    resp = _client(token).users_list(limit=limit)
    return ToolResult(
        success=resp["ok"],
        data={"users": [{"id": u["id"], "name": u["name"], "real_name": u.get("real_name")} for u in resp.get("members", [])]},
    )


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name, description=description,
        parameters={"type": "object", "properties": props, "required": required},
        handler=handler, danger_level=danger, tags=["slack"], **extra,
    )


tools: list[Tool] = [
    _T("slack_send", "Send a Slack message. DESTRUCTIVE because messages cannot be unsent (only deleted).",
        {"channel": {"type": "string"}, "text": {"type": "string"}, "thread_ts": {"type": "string"}, "token": {"type": "string"}},
        ["channel", "text"], _slack_send, DangerLevel.DESTRUCTIVE),
    _T("slack_search", "Search Slack messages.",
        {"query": {"type": "string"}, "sort": {"type": "string", "default": "timestamp"}, "count": {"type": "integer", "default": 20}, "token": {"type": "string"}},
        ["query"], _slack_search, DangerLevel.READ,
        default_reliability=ReliabilityLevel.REFERENCE),
    _T("slack_channel_list", "List Slack channels.",
        {"types": {"type": "string", "default": "public_channel"}, "limit": {"type": "integer", "default": 200}, "token": {"type": "string"}},
        [], _slack_channel_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("slack_channel_create", "Create a Slack channel.",
        {"name": {"type": "string"}, "is_private": {"type": "boolean", "default": False}, "token": {"type": "string"}},
        ["name"], _slack_channel_create, DangerLevel.MODIFY),
    _T("slack_reaction_add", "Add a reaction to a message.",
        {"channel": {"type": "string"}, "timestamp": {"type": "string"}, "name": {"type": "string"}, "token": {"type": "string"}},
        ["channel", "timestamp", "name"], _slack_reaction_add, DangerLevel.MODIFY),
    _T("slack_file_upload", "Upload a file to a channel.",
        {"channel": {"type": "string"}, "file_path": {"type": "string"}, "title": {"type": "string"}, "token": {"type": "string"}},
        ["channel", "file_path"], _slack_file_upload, DangerLevel.MODIFY),
    _T("slack_user_list", "List workspace users.",
        {"limit": {"type": "integer", "default": 200}, "token": {"type": "string"}},
        [], _slack_user_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
]

__all__ = ["tools"]
