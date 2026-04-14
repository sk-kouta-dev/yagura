"""yagura-tools-azure — Blob Storage, Azure Functions, Cosmos DB."""

from __future__ import annotations

import os
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _blob_service_client():
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore
        from azure.storage.blob import BlobServiceClient  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-azure requires 'azure-storage-blob' and 'azure-identity'") from exc
    url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    if not url:
        raise RuntimeError("Set AZURE_STORAGE_ACCOUNT_URL (e.g. https://acct.blob.core.windows.net)")
    return BlobServiceClient(account_url=url, credential=DefaultAzureCredential())


def _cosmos_client():
    try:
        from azure.cosmos import CosmosClient  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-azure requires 'azure-cosmos'") from exc
    endpoint = os.environ.get("AZURE_COSMOS_ENDPOINT")
    key = os.environ.get("AZURE_COSMOS_KEY")
    if not endpoint or not key:
        raise RuntimeError("Set AZURE_COSMOS_ENDPOINT and AZURE_COSMOS_KEY")
    return CosmosClient(endpoint, credential=key)


# ---------------------------------------------------------------------------
# Blob Storage
# ---------------------------------------------------------------------------


def _blob_list(container: str, prefix: str | None = None) -> ToolResult:
    svc = _blob_service_client()
    cc = svc.get_container_client(container)
    blobs = list(cc.list_blobs(name_starts_with=prefix))
    items = [{"name": b.name, "size": b.size, "last_modified": b.last_modified.isoformat() if b.last_modified else None} for b in blobs]
    return ToolResult(success=True, data={"container": container, "blobs": items, "count": len(items)})


def _blob_download(container: str, blob_name: str, local_path: str) -> ToolResult:
    svc = _blob_service_client()
    with open(local_path, "wb") as f:
        downloader = svc.get_blob_client(container=container, blob=blob_name).download_blob()
        f.write(downloader.readall())
    return ToolResult(success=True, data={"container": container, "blob_name": blob_name, "local_path": local_path})


def _blob_upload(local_path: str, container: str, blob_name: str) -> ToolResult:
    svc = _blob_service_client()
    with open(local_path, "rb") as f:
        svc.get_blob_client(container=container, blob=blob_name).upload_blob(f, overwrite=True)
    return ToolResult(success=True, data={"container": container, "blob_name": blob_name, "local_path": local_path})


def _blob_delete(container: str, blob_name: str) -> ToolResult:
    svc = _blob_service_client()
    svc.get_blob_client(container=container, blob=blob_name).delete_blob()
    return ToolResult(success=True, data={"container": container, "blob_name": blob_name, "deleted": True})


# ---------------------------------------------------------------------------
# Azure Functions
# ---------------------------------------------------------------------------


def _azure_function_invoke(function_url: str, payload: dict[str, Any] | None = None) -> ToolResult:
    try:
        import httpx  # type: ignore
    except ImportError as exc:
        raise ImportError("azure_function_invoke requires 'httpx'") from exc
    response = httpx.post(function_url, json=payload or {}, timeout=60)
    return ToolResult(success=response.is_success, data={"status": response.status_code, "body": response.text})


# ---------------------------------------------------------------------------
# Cosmos DB
# ---------------------------------------------------------------------------


def _cosmos_query(database: str, container: str, query: str) -> ToolResult:
    client = _cosmos_client()
    cc = client.get_database_client(database).get_container_client(container)
    items = list(cc.query_items(query=query, enable_cross_partition_query=True))
    return ToolResult(
        success=True,
        data={"items": items, "count": len(items)},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _cosmos_upsert(database: str, container: str, document: dict[str, Any]) -> ToolResult:
    client = _cosmos_client()
    cc = client.get_database_client(database).get_container_client(container)
    result = cc.upsert_item(document)
    return ToolResult(success=True, data={"id": result.get("id"), "upserted": True})


def _cosmos_delete(database: str, container: str, document_id: str, partition_key: str | None = None) -> ToolResult:
    client = _cosmos_client()
    cc = client.get_database_client(database).get_container_client(container)
    cc.delete_item(item=document_id, partition_key=partition_key or document_id)
    return ToolResult(success=True, data={"id": document_id, "deleted": True})


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name,
        description=description,
        parameters={"type": "object", "properties": props, "required": required},
        handler=handler,
        danger_level=danger,
        tags=["azure"],
        **extra,
    )


tools: list[Tool] = [
    _T("blob_list", "List blobs in a container.",
        {"container": {"type": "string"}, "prefix": {"type": "string"}},
        ["container"], _blob_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("blob_download", "Download a blob.",
        {"container": {"type": "string"}, "blob_name": {"type": "string"}, "local_path": {"type": "string"}},
        ["container", "blob_name", "local_path"], _blob_download, DangerLevel.READ),
    _T("blob_upload", "Upload a file to Blob Storage.",
        {"local_path": {"type": "string"}, "container": {"type": "string"}, "blob_name": {"type": "string"}},
        ["local_path", "container", "blob_name"], _blob_upload, DangerLevel.MODIFY),
    _T("blob_delete", "Delete a blob.",
        {"container": {"type": "string"}, "blob_name": {"type": "string"}},
        ["container", "blob_name"], _blob_delete, DangerLevel.DESTRUCTIVE),
    _T("azure_function_invoke", "Invoke an Azure Function via HTTP.",
        {"function_url": {"type": "string"}, "payload": {"type": "object"}},
        ["function_url"], _azure_function_invoke, DangerLevel.MODIFY),
    _T("cosmos_query", "Query a Cosmos DB container with SQL.",
        {"database": {"type": "string"}, "container": {"type": "string"}, "query": {"type": "string"}},
        ["database", "container", "query"], _cosmos_query, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("cosmos_upsert", "Insert or update a document.",
        {"database": {"type": "string"}, "container": {"type": "string"}, "document": {"type": "object"}},
        ["database", "container", "document"], _cosmos_upsert, DangerLevel.MODIFY),
    _T("cosmos_delete", "Delete a document.",
        {"database": {"type": "string"}, "container": {"type": "string"}, "document_id": {"type": "string"}, "partition_key": {"type": "string"}},
        ["database", "container", "document_id"], _cosmos_delete, DangerLevel.DESTRUCTIVE),
]

__all__ = ["tools"]
