"""yagura-tools-microsoft — Microsoft 365 via Microsoft Graph.

Graph SDK usage is async-first. Handlers are defined as async functions.
Auth: uses `DefaultAzureCredential` from azure-identity, which supports
env vars, managed identity, Visual Studio, Azure CLI, and interactive login.
"""

from __future__ import annotations

import os
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _graph_client():
    try:
        from msgraph import GraphServiceClient  # type: ignore
        from azure.identity import DefaultAzureCredential  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-microsoft requires 'msgraph-sdk' and 'azure-identity'") from exc
    credential = DefaultAzureCredential()
    return GraphServiceClient(credentials=credential, scopes=["https://graph.microsoft.com/.default"])


# ---------------------------------------------------------------------------
# Outlook
# ---------------------------------------------------------------------------


async def _outlook_send(to: str, subject: str, body: str, cc: str | None = None) -> ToolResult:
    try:
        from msgraph.generated.models.message import Message  # type: ignore
        from msgraph.generated.models.item_body import ItemBody  # type: ignore
        from msgraph.generated.models.body_type import BodyType  # type: ignore
        from msgraph.generated.models.recipient import Recipient  # type: ignore
        from msgraph.generated.models.email_address import EmailAddress  # type: ignore
        from msgraph.generated.users.item.send_mail.send_mail_post_request_body import SendMailPostRequestBody  # type: ignore
    except ImportError as exc:
        raise ImportError("msgraph-sdk missing expected modules") from exc

    def _recipient(email: str) -> Any:
        r = Recipient()
        r.email_address = EmailAddress()
        r.email_address.address = email
        return r

    msg = Message()
    msg.subject = subject
    msg.body = ItemBody()
    msg.body.content_type = BodyType.Html
    msg.body.content = body
    msg.to_recipients = [_recipient(addr.strip()) for addr in to.split(",")]
    if cc:
        msg.cc_recipients = [_recipient(addr.strip()) for addr in cc.split(",")]

    req = SendMailPostRequestBody()
    req.message = msg
    req.save_to_sent_items = True

    client = _graph_client()
    await client.me.send_mail.post(req)
    return ToolResult(success=True, data={"to": to, "subject": subject})


async def _outlook_search(query: str, max_results: int = 20) -> ToolResult:
    client = _graph_client()
    from msgraph.generated.users.item.messages.messages_request_builder import MessagesRequestBuilder  # type: ignore
    cfg = MessagesRequestBuilder.MessagesRequestBuilderGetRequestConfiguration(
        query_parameters=MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            search=f'"{query}"', top=max_results
        )
    )
    result = await client.me.messages.get(cfg)
    messages = [
        {"id": m.id, "subject": m.subject, "from": getattr(m.from_, "email_address", None).address if m.from_ else None}
        for m in (result.value or [])
    ]
    return ToolResult(success=True, data={"messages": messages, "count": len(messages)})


async def _outlook_read(message_id: str) -> ToolResult:
    client = _graph_client()
    m = await client.me.messages.by_message_id(message_id).get()
    return ToolResult(
        success=True,
        data={"id": m.id, "subject": m.subject, "body_preview": m.body_preview},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


async def _outlook_draft_create(to: str, subject: str, body: str) -> ToolResult:
    from msgraph.generated.models.message import Message  # type: ignore
    from msgraph.generated.models.item_body import ItemBody  # type: ignore
    from msgraph.generated.models.body_type import BodyType  # type: ignore
    client = _graph_client()
    msg = Message()
    msg.subject = subject
    msg.body = ItemBody()
    msg.body.content_type = BodyType.Html
    msg.body.content = body
    created = await client.me.messages.post(msg)
    return ToolResult(success=True, data={"id": created.id, "to": to})


# ---------------------------------------------------------------------------
# OneDrive
# ---------------------------------------------------------------------------


async def _onedrive_search(query: str, max_results: int = 20) -> ToolResult:
    client = _graph_client()
    results = await client.me.drive.root.search_with_q(q=query).get()
    items = [{"id": it.id, "name": it.name, "web_url": it.web_url} for it in (results.value or [])[:max_results]]
    return ToolResult(success=True, data={"items": items})


async def _onedrive_download(item_id: str, local_path: str) -> ToolResult:
    client = _graph_client()
    stream = await client.me.drive.items.by_drive_item_id(item_id).content.get()
    with open(local_path, "wb") as f:
        f.write(stream)
    return ToolResult(success=True, data={"item_id": item_id, "local_path": local_path})


async def _onedrive_upload(local_path: str, folder_path: str, name: str | None = None) -> ToolResult:
    client = _graph_client()
    with open(local_path, "rb") as f:
        content = f.read()
    filename = name or local_path.rsplit("/", 1)[-1]
    target = f"{folder_path.rstrip('/')}/{filename}"
    # Use the `root:/{path}:content` alias.
    uploaded = await client.me.drive.root.item_with_path(target).content.put(content)
    return ToolResult(success=True, data={"id": uploaded.id, "name": uploaded.name})


async def _onedrive_move(item_id: str, destination_folder_id: str) -> ToolResult:
    from msgraph.generated.models.drive_item import DriveItem  # type: ignore
    from msgraph.generated.models.item_reference import ItemReference  # type: ignore
    client = _graph_client()
    update = DriveItem()
    update.parent_reference = ItemReference()
    update.parent_reference.id = destination_folder_id
    moved = await client.me.drive.items.by_drive_item_id(item_id).patch(update)
    return ToolResult(success=True, data={"id": moved.id, "parent": destination_folder_id})


async def _onedrive_delete(item_id: str) -> ToolResult:
    client = _graph_client()
    await client.me.drive.items.by_drive_item_id(item_id).delete()
    return ToolResult(success=True, data={"id": item_id, "deleted": True})


# ---------------------------------------------------------------------------
# SharePoint
# ---------------------------------------------------------------------------


async def _sharepoint_search(query: str, site_id: str | None = None) -> ToolResult:
    client = _graph_client()
    if site_id:
        result = await client.sites.by_site_id(site_id).drive.root.search_with_q(q=query).get()
    else:
        result = await client.sites.by_site_id("root").drive.root.search_with_q(q=query).get()
    items = [{"id": it.id, "name": it.name, "web_url": it.web_url} for it in (result.value or [])]
    return ToolResult(success=True, data={"items": items})


async def _sharepoint_download(site_id: str, item_id: str, local_path: str) -> ToolResult:
    client = _graph_client()
    stream = await client.sites.by_site_id(site_id).drive.items.by_drive_item_id(item_id).content.get()
    with open(local_path, "wb") as f:
        f.write(stream)
    return ToolResult(success=True, data={"site_id": site_id, "item_id": item_id, "local_path": local_path})


async def _sharepoint_upload(site_id: str, local_path: str, folder_path: str) -> ToolResult:
    client = _graph_client()
    with open(local_path, "rb") as f:
        content = f.read()
    filename = local_path.rsplit("/", 1)[-1]
    target = f"{folder_path.rstrip('/')}/{filename}"
    uploaded = await client.sites.by_site_id(site_id).drive.root.item_with_path(target).content.put(content)
    return ToolResult(success=True, data={"id": uploaded.id, "name": uploaded.name})


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


async def _teams_send(team_id: str, channel_id: str, message: str) -> ToolResult:
    from msgraph.generated.models.chat_message import ChatMessage  # type: ignore
    from msgraph.generated.models.item_body import ItemBody  # type: ignore
    client = _graph_client()
    msg = ChatMessage()
    msg.body = ItemBody()
    msg.body.content = message
    posted = await client.teams.by_team_id(team_id).channels.by_channel_id(channel_id).messages.post(msg)
    return ToolResult(success=True, data={"id": posted.id})


async def _teams_channel_list(team_id: str) -> ToolResult:
    client = _graph_client()
    result = await client.teams.by_team_id(team_id).channels.get()
    channels = [{"id": c.id, "display_name": c.display_name} for c in (result.value or [])]
    return ToolResult(success=True, data={"channels": channels})


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name, description=description,
        parameters={"type": "object", "properties": props, "required": required},
        handler=handler, danger_level=danger, tags=["microsoft"], **extra,
    )


tools: list[Tool] = [
    _T("outlook_send", "Send an email via Outlook. DESTRUCTIVE.",
        {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}, "cc": {"type": "string"}},
        ["to", "subject", "body"], _outlook_send, DangerLevel.DESTRUCTIVE),
    _T("outlook_search", "Search Outlook emails.",
        {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 20}},
        ["query"], _outlook_search, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("outlook_read", "Read a single email.",
        {"message_id": {"type": "string"}},
        ["message_id"], _outlook_read, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("outlook_draft_create", "Create an email draft.",
        {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
        ["to", "subject", "body"], _outlook_draft_create, DangerLevel.MODIFY),
    _T("onedrive_search", "Search OneDrive.",
        {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 20}},
        ["query"], _onedrive_search, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("onedrive_download", "Download from OneDrive.",
        {"item_id": {"type": "string"}, "local_path": {"type": "string"}},
        ["item_id", "local_path"], _onedrive_download, DangerLevel.READ),
    _T("onedrive_upload", "Upload to OneDrive.",
        {"local_path": {"type": "string"}, "folder_path": {"type": "string"}, "name": {"type": "string"}},
        ["local_path", "folder_path"], _onedrive_upload, DangerLevel.MODIFY),
    _T("onedrive_move", "Move a OneDrive item.",
        {"item_id": {"type": "string"}, "destination_folder_id": {"type": "string"}},
        ["item_id", "destination_folder_id"], _onedrive_move, DangerLevel.MODIFY),
    _T("onedrive_delete", "Delete a OneDrive item.",
        {"item_id": {"type": "string"}},
        ["item_id"], _onedrive_delete, DangerLevel.DESTRUCTIVE),
    _T("sharepoint_search", "Search SharePoint.",
        {"query": {"type": "string"}, "site_id": {"type": "string"}},
        ["query"], _sharepoint_search, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("sharepoint_download", "Download from SharePoint.",
        {"site_id": {"type": "string"}, "item_id": {"type": "string"}, "local_path": {"type": "string"}},
        ["site_id", "item_id", "local_path"], _sharepoint_download, DangerLevel.READ),
    _T("sharepoint_upload", "Upload to SharePoint.",
        {"site_id": {"type": "string"}, "local_path": {"type": "string"}, "folder_path": {"type": "string"}},
        ["site_id", "local_path", "folder_path"], _sharepoint_upload, DangerLevel.MODIFY),
    _T("teams_send", "Send a Teams channel message. DESTRUCTIVE.",
        {"team_id": {"type": "string"}, "channel_id": {"type": "string"}, "message": {"type": "string"}},
        ["team_id", "channel_id", "message"], _teams_send, DangerLevel.DESTRUCTIVE),
    _T("teams_channel_list", "List channels in a team.",
        {"team_id": {"type": "string"}},
        ["team_id"], _teams_channel_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
]

__all__ = ["tools"]
