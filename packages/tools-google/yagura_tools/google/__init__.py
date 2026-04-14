"""yagura-tools-google — Gmail, Drive, Calendar, Sheets.

Credentials: this package uses Application Default Credentials via
`google.auth.default()`. Set `GOOGLE_APPLICATION_CREDENTIALS=<service-account.json>`
in the environment for a service account, or use `gcloud auth application-default login`.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _service(api: str, version: str):
    try:
        from googleapiclient.discovery import build  # type: ignore
        from google.auth import default  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-google requires 'google-api-python-client' and 'google-auth'") from exc
    credentials, _ = default(scopes=_SCOPES)
    return build(api, version, credentials=credentials, cache_discovery=False)


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------


def _gmail_send(to: str, subject: str, body: str, cc: str | None = None, attachments: list[str] | None = None) -> ToolResult:
    service = _service("gmail", "v1")
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    message.set_content(body)
    for path in attachments or []:
        with open(path, "rb") as f:
            data = f.read()
        message.add_attachment(data, maintype="application", subtype="octet-stream", filename=path.rsplit("/", 1)[-1])
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return ToolResult(success=True, data={"id": sent.get("id"), "thread_id": sent.get("threadId")})


def _gmail_search(query: str, max_results: int = 20) -> ToolResult:
    service = _service("gmail", "v1")
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    messages = resp.get("messages", [])
    return ToolResult(success=True, data={"messages": messages, "count": len(messages)})


def _gmail_read(message_id: str) -> ToolResult:
    service = _service("gmail", "v1")
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return ToolResult(
        success=True,
        data={"id": message_id, "subject": headers.get("Subject"), "from": headers.get("From"), "snippet": msg.get("snippet")},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _gmail_draft_create(to: str, subject: str, body: str) -> ToolResult:
    service = _service("gmail", "v1")
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return ToolResult(success=True, data={"draft_id": draft.get("id")})


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------


def _gdrive_search(query: str, max_results: int = 20) -> ToolResult:
    service = _service("drive", "v3")
    resp = service.files().list(q=query, pageSize=max_results, fields="files(id, name, mimeType, modifiedTime)").execute()
    return ToolResult(success=True, data={"files": resp.get("files", [])})


def _gdrive_download(file_id: str, local_path: str) -> ToolResult:
    service = _service("drive", "v3")
    request = service.files().get_media(fileId=file_id)
    from googleapiclient.http import MediaIoBaseDownload  # type: ignore
    with open(local_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return ToolResult(success=True, data={"file_id": file_id, "local_path": local_path})


def _gdrive_upload(local_path: str, folder_id: str | None = None, name: str | None = None) -> ToolResult:
    service = _service("drive", "v3")
    from googleapiclient.http import MediaFileUpload  # type: ignore
    metadata: dict[str, Any] = {"name": name or local_path.rsplit("/", 1)[-1]}
    if folder_id:
        metadata["parents"] = [folder_id]
    media = MediaFileUpload(local_path, resumable=True)
    created = service.files().create(body=metadata, media_body=media, fields="id, name").execute()
    return ToolResult(success=True, data={"id": created["id"], "name": created["name"]})


def _gdrive_move(file_id: str, destination_folder_id: str) -> ToolResult:
    service = _service("drive", "v3")
    f = service.files().get(fileId=file_id, fields="parents").execute()
    prev = ",".join(f.get("parents", []))
    service.files().update(fileId=file_id, addParents=destination_folder_id, removeParents=prev, fields="id, parents").execute()
    return ToolResult(success=True, data={"file_id": file_id, "destination": destination_folder_id})


def _gdrive_delete(file_id: str) -> ToolResult:
    service = _service("drive", "v3")
    service.files().delete(fileId=file_id).execute()
    return ToolResult(success=True, data={"file_id": file_id, "deleted": True})


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def _gcalendar_list(calendar_id: str = "primary", time_min: str | None = None, time_max: str | None = None) -> ToolResult:
    service = _service("calendar", "v3")
    resp = service.events().list(calendarId=calendar_id, timeMin=time_min, timeMax=time_max, singleEvents=True, orderBy="startTime").execute()
    return ToolResult(success=True, data={"events": resp.get("items", [])})


def _gcalendar_create(summary: str, start: str, end: str, attendees: list[str] | None = None, calendar_id: str = "primary") -> ToolResult:
    service = _service("calendar", "v3")
    event = {
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "attendees": [{"email": a} for a in attendees or []],
    }
    created = service.events().insert(calendarId=calendar_id, body=event).execute()
    return ToolResult(success=True, data={"id": created["id"], "html_link": created.get("htmlLink")})


def _gcalendar_update(event_id: str, updates: dict[str, Any], calendar_id: str = "primary") -> ToolResult:
    service = _service("calendar", "v3")
    service.events().patch(calendarId=calendar_id, eventId=event_id, body=updates).execute()
    return ToolResult(success=True, data={"id": event_id, "updated": True})


def _gcalendar_delete(event_id: str, calendar_id: str = "primary") -> ToolResult:
    service = _service("calendar", "v3")
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return ToolResult(success=True, data={"id": event_id, "deleted": True})


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------


def _gsheets_read(spreadsheet_id: str, range: str) -> ToolResult:
    service = _service("sheets", "v4")
    resp = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range).execute()
    return ToolResult(
        success=True,
        data={"range": resp.get("range"), "values": resp.get("values", [])},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _gsheets_write(spreadsheet_id: str, range: str, values: list[list[Any]]) -> ToolResult:
    service = _service("sheets", "v4")
    resp = service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=range, valueInputOption="USER_ENTERED", body={"values": values}
    ).execute()
    return ToolResult(success=True, data={"updated_cells": resp.get("updatedCells", 0)})


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name, description=description,
        parameters={"type": "object", "properties": props, "required": required},
        handler=handler, danger_level=danger, tags=["google"], **extra,
    )


tools: list[Tool] = [
    _T("gmail_send", "Send an email. DESTRUCTIVE.",
        {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}, "cc": {"type": "string"}, "attachments": {"type": "array", "items": {"type": "string"}}},
        ["to", "subject", "body"], _gmail_send, DangerLevel.DESTRUCTIVE),
    _T("gmail_search", "Search emails.",
        {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 20}},
        ["query"], _gmail_search, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("gmail_read", "Read a single email.",
        {"message_id": {"type": "string"}},
        ["message_id"], _gmail_read, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("gmail_draft_create", "Create an email draft.",
        {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
        ["to", "subject", "body"], _gmail_draft_create, DangerLevel.MODIFY),
    _T("gdrive_search", "Search Google Drive files.",
        {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 20}},
        ["query"], _gdrive_search, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("gdrive_download", "Download a Drive file.",
        {"file_id": {"type": "string"}, "local_path": {"type": "string"}},
        ["file_id", "local_path"], _gdrive_download, DangerLevel.READ),
    _T("gdrive_upload", "Upload a file to Drive.",
        {"local_path": {"type": "string"}, "folder_id": {"type": "string"}, "name": {"type": "string"}},
        ["local_path"], _gdrive_upload, DangerLevel.MODIFY),
    _T("gdrive_move", "Move a Drive file.",
        {"file_id": {"type": "string"}, "destination_folder_id": {"type": "string"}},
        ["file_id", "destination_folder_id"], _gdrive_move, DangerLevel.MODIFY),
    _T("gdrive_delete", "Delete a Drive file.",
        {"file_id": {"type": "string"}},
        ["file_id"], _gdrive_delete, DangerLevel.DESTRUCTIVE),
    _T("gcalendar_list", "List calendar events.",
        {"calendar_id": {"type": "string", "default": "primary"}, "time_min": {"type": "string"}, "time_max": {"type": "string"}},
        [], _gcalendar_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("gcalendar_create", "Create a calendar event.",
        {"summary": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}, "attendees": {"type": "array", "items": {"type": "string"}}, "calendar_id": {"type": "string", "default": "primary"}},
        ["summary", "start", "end"], _gcalendar_create, DangerLevel.MODIFY),
    _T("gcalendar_update", "Update a calendar event.",
        {"event_id": {"type": "string"}, "updates": {"type": "object"}, "calendar_id": {"type": "string", "default": "primary"}},
        ["event_id", "updates"], _gcalendar_update, DangerLevel.MODIFY),
    _T("gcalendar_delete", "Delete a calendar event.",
        {"event_id": {"type": "string"}, "calendar_id": {"type": "string", "default": "primary"}},
        ["event_id"], _gcalendar_delete, DangerLevel.DESTRUCTIVE),
    _T("gsheets_read", "Read spreadsheet values.",
        {"spreadsheet_id": {"type": "string"}, "range": {"type": "string"}},
        ["spreadsheet_id", "range"], _gsheets_read, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("gsheets_write", "Write values to a spreadsheet range.",
        {"spreadsheet_id": {"type": "string"}, "range": {"type": "string"}, "values": {"type": "array", "items": {"type": "array"}}},
        ["spreadsheet_id", "range", "values"], _gsheets_write, DangerLevel.MODIFY),
]

__all__ = ["tools"]
