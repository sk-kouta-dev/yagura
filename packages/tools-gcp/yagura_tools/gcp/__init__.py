"""yagura-tools-gcp — Google Cloud Platform (GCS, BigQuery, Cloud Functions)."""

from __future__ import annotations

from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _gcs_client():
    try:
        from google.cloud import storage  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-gcp requires 'google-cloud-storage'") from exc
    return storage.Client()


def _bq_client(project: str | None = None):
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-gcp requires 'google-cloud-bigquery'") from exc
    return bigquery.Client(project=project)


# ---------------------------------------------------------------------------
# GCS
# ---------------------------------------------------------------------------


def _gcs_list(bucket: str, prefix: str | None = None) -> ToolResult:
    client = _gcs_client()
    blobs = client.list_blobs(bucket, prefix=prefix)
    items = [{"name": b.name, "size": b.size, "updated": b.updated.isoformat() if b.updated else None} for b in blobs]
    return ToolResult(success=True, data={"bucket": bucket, "objects": items, "count": len(items)})


def _gcs_download(bucket: str, blob_name: str, local_path: str) -> ToolResult:
    client = _gcs_client()
    client.bucket(bucket).blob(blob_name).download_to_filename(local_path)
    return ToolResult(success=True, data={"bucket": bucket, "blob_name": blob_name, "local_path": local_path})


def _gcs_upload(local_path: str, bucket: str, blob_name: str) -> ToolResult:
    client = _gcs_client()
    client.bucket(bucket).blob(blob_name).upload_from_filename(local_path)
    return ToolResult(success=True, data={"bucket": bucket, "blob_name": blob_name, "local_path": local_path})


def _gcs_delete(bucket: str, blob_name: str) -> ToolResult:
    client = _gcs_client()
    client.bucket(bucket).blob(blob_name).delete()
    return ToolResult(success=True, data={"bucket": bucket, "blob_name": blob_name, "deleted": True})


# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------


def _bigquery_query(query: str, project: str | None = None) -> ToolResult:
    client = _bq_client(project)
    job = client.query(query)
    rows = [dict(row) for row in job.result()]
    return ToolResult(
        success=True,
        data={"rows": rows, "row_count": len(rows), "bytes_processed": job.total_bytes_processed},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _bigquery_list_tables(dataset: str, project: str | None = None) -> ToolResult:
    client = _bq_client(project)
    tables = list(client.list_tables(dataset))
    return ToolResult(
        success=True,
        data={
            "dataset": dataset,
            "tables": [{"table_id": t.table_id, "full_table_id": t.full_table_id} for t in tables],
        },
    )


# ---------------------------------------------------------------------------
# Cloud Function invocation
# ---------------------------------------------------------------------------


def _cloud_function_invoke(function_url: str, payload: dict[str, Any] | None = None) -> ToolResult:
    try:
        import httpx  # type: ignore
    except ImportError as exc:
        raise ImportError("cloud_function_invoke requires 'httpx'") from exc
    response = httpx.post(function_url, json=payload or {}, timeout=60)
    return ToolResult(
        success=response.is_success,
        data={"status": response.status_code, "body": response.text},
    )


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
        tags=["gcp"],
        **extra,
    )


tools: list[Tool] = [
    _T(
        "gcs_list",
        "List objects in a GCS bucket.",
        {"bucket": {"type": "string"}, "prefix": {"type": "string"}},
        ["bucket"],
        _gcs_list,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "gcs_download",
        "Download a blob from GCS.",
        {
            "bucket": {"type": "string"},
            "blob_name": {"type": "string"},
            "local_path": {"type": "string"},
        },
        ["bucket", "blob_name", "local_path"],
        _gcs_download,
        DangerLevel.READ,
    ),
    _T(
        "gcs_upload",
        "Upload a file to GCS.",
        {
            "local_path": {"type": "string"},
            "bucket": {"type": "string"},
            "blob_name": {"type": "string"},
        },
        ["local_path", "bucket", "blob_name"],
        _gcs_upload,
        DangerLevel.MODIFY,
    ),
    _T(
        "gcs_delete",
        "Delete a GCS blob.",
        {"bucket": {"type": "string"}, "blob_name": {"type": "string"}},
        ["bucket", "blob_name"],
        _gcs_delete,
        DangerLevel.DESTRUCTIVE,
    ),
    _T(
        "bigquery_query",
        "Execute a BigQuery SQL query. Layer 2 classifies the query.",
        {"query": {"type": "string"}, "project": {"type": "string"}},
        ["query"],
        _bigquery_query,
        None,
        requires_llm=True,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "bigquery_list_tables",
        "List tables in a BigQuery dataset.",
        {"dataset": {"type": "string"}, "project": {"type": "string"}},
        ["dataset"],
        _bigquery_list_tables,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "cloud_function_invoke",
        "Invoke a Cloud Function via HTTP POST.",
        {"function_url": {"type": "string"}, "payload": {"type": "object"}},
        ["function_url"],
        _cloud_function_invoke,
        DangerLevel.MODIFY,
    ),
]

__all__ = ["tools"]
