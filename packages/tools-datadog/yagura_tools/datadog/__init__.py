"""yagura-tools-datadog — metrics, monitors, dashboards, events."""

from __future__ import annotations

import os
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _config():
    try:
        from datadog_api_client import Configuration  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-datadog requires 'datadog-api-client'") from exc
    cfg = Configuration()
    cfg.api_key["apiKeyAuth"] = os.environ.get("DATADOG_API_KEY", "")
    cfg.api_key["appKeyAuth"] = os.environ.get("DATADOG_APP_KEY", "")
    if not cfg.api_key["apiKeyAuth"] or not cfg.api_key["appKeyAuth"]:
        raise RuntimeError("Set DATADOG_API_KEY and DATADOG_APP_KEY")
    return cfg


def _datadog_metrics_query(query: str, from_ts: int, to_ts: int) -> ToolResult:
    from datadog_api_client import ApiClient  # type: ignore
    from datadog_api_client.v1.api.metrics_api import MetricsApi  # type: ignore

    with ApiClient(_config()) as client:
        resp = MetricsApi(client).query_metrics(_from=from_ts, to=to_ts, query=query)
    return ToolResult(
        success=True,
        data={"series": [s.to_dict() for s in (resp.series or [])]},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _datadog_metrics_submit(metric: str, points: list[list[float]], tags: list[str] | None = None) -> ToolResult:
    from datadog_api_client import ApiClient  # type: ignore
    from datadog_api_client.v2.api.metrics_api import MetricsApi  # type: ignore
    from datadog_api_client.v2.model.metric_payload import MetricPayload  # type: ignore
    from datadog_api_client.v2.model.metric_series import MetricSeries  # type: ignore
    from datadog_api_client.v2.model.metric_point import MetricPoint  # type: ignore

    series = MetricSeries(
        metric=metric,
        type=0,
        points=[MetricPoint(timestamp=int(p[0]), value=float(p[1])) for p in points],
        tags=tags or [],
    )
    body = MetricPayload(series=[series])
    with ApiClient(_config()) as client:
        MetricsApi(client).submit_metrics(body=body)
    return ToolResult(success=True, data={"metric": metric, "points": len(points)})


def _datadog_alert_list(name: str | None = None, tags: list[str] | None = None) -> ToolResult:
    from datadog_api_client import ApiClient  # type: ignore
    from datadog_api_client.v1.api.monitors_api import MonitorsApi  # type: ignore

    with ApiClient(_config()) as client:
        kwargs: dict[str, Any] = {}
        if name:
            kwargs["name"] = name
        if tags:
            kwargs["monitor_tags"] = ",".join(tags)
        monitors = MonitorsApi(client).list_monitors(**kwargs)
    return ToolResult(
        success=True,
        data={"monitors": [{"id": m.id, "name": m.name, "status": str(m.overall_state)} for m in monitors]},
    )


def _datadog_alert_mute(monitor_id: int, end: int | None = None) -> ToolResult:
    from datadog_api_client import ApiClient  # type: ignore
    from datadog_api_client.v1.api.monitors_api import MonitorsApi  # type: ignore

    with ApiClient(_config()) as client:
        kwargs: dict[str, Any] = {}
        if end:
            kwargs["end"] = end
        MonitorsApi(client).mute_monitor(monitor_id=monitor_id, **kwargs)
    return ToolResult(success=True, data={"monitor_id": monitor_id, "muted": True})


def _datadog_alert_unmute(monitor_id: int) -> ToolResult:
    from datadog_api_client import ApiClient  # type: ignore
    from datadog_api_client.v1.api.monitors_api import MonitorsApi  # type: ignore

    with ApiClient(_config()) as client:
        MonitorsApi(client).unmute_monitor(monitor_id=monitor_id)
    return ToolResult(success=True, data={"monitor_id": monitor_id, "muted": False})


def _datadog_dashboard_get(dashboard_id: str) -> ToolResult:
    from datadog_api_client import ApiClient  # type: ignore
    from datadog_api_client.v1.api.dashboards_api import DashboardsApi  # type: ignore

    with ApiClient(_config()) as client:
        dashboard = DashboardsApi(client).get_dashboard(dashboard_id)
    return ToolResult(
        success=True,
        data={"id": dashboard.id, "title": dashboard.title, "widgets": len(dashboard.widgets or [])},
    )


def _datadog_event_list(start: int, end: int, tags: list[str] | None = None) -> ToolResult:
    from datadog_api_client import ApiClient  # type: ignore
    from datadog_api_client.v1.api.events_api import EventsApi  # type: ignore

    with ApiClient(_config()) as client:
        kwargs: dict[str, Any] = {"start": start, "end": end}
        if tags:
            kwargs["tags"] = ",".join(tags)
        events = EventsApi(client).list_events(**kwargs)
    return ToolResult(
        success=True,
        data={"events": [{"id": e.id, "title": e.title, "text": e.text} for e in (events.events or [])]},
    )


def _datadog_event_create(title: str, text: str, tags: list[str] | None = None) -> ToolResult:
    from datadog_api_client import ApiClient  # type: ignore
    from datadog_api_client.v1.api.events_api import EventsApi  # type: ignore
    from datadog_api_client.v1.model.event_create_request import EventCreateRequest  # type: ignore

    with ApiClient(_config()) as client:
        body = EventCreateRequest(title=title, text=text, tags=tags or [])
        resp = EventsApi(client).create_event(body=body)
    return ToolResult(success=True, data={"id": resp.event.id if resp.event else None})


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name, description=description,
        parameters={"type": "object", "properties": props, "required": required},
        handler=handler, danger_level=danger, tags=["datadog"], **extra,
    )


tools: list[Tool] = [
    _T("datadog_metrics_query", "Query Datadog metrics.",
        {"query": {"type": "string"}, "from_ts": {"type": "integer"}, "to_ts": {"type": "integer"}},
        ["query", "from_ts", "to_ts"], _datadog_metrics_query, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("datadog_metrics_submit", "Submit custom metric points.",
        {"metric": {"type": "string"}, "points": {"type": "array"}, "tags": {"type": "array", "items": {"type": "string"}}},
        ["metric", "points"], _datadog_metrics_submit, DangerLevel.MODIFY),
    _T("datadog_alert_list", "List monitors.",
        {"name": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
        [], _datadog_alert_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("datadog_alert_mute", "Mute a monitor.",
        {"monitor_id": {"type": "integer"}, "end": {"type": "integer"}},
        ["monitor_id"], _datadog_alert_mute, DangerLevel.MODIFY),
    _T("datadog_alert_unmute", "Unmute a monitor.",
        {"monitor_id": {"type": "integer"}},
        ["monitor_id"], _datadog_alert_unmute, DangerLevel.MODIFY),
    _T("datadog_dashboard_get", "Get a dashboard.",
        {"dashboard_id": {"type": "string"}},
        ["dashboard_id"], _datadog_dashboard_get, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("datadog_event_list", "List events in a time range.",
        {"start": {"type": "integer"}, "end": {"type": "integer"}, "tags": {"type": "array", "items": {"type": "string"}}},
        ["start", "end"], _datadog_event_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("datadog_event_create", "Create an event.",
        {"title": {"type": "string"}, "text": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
        ["title", "text"], _datadog_event_create, DangerLevel.MODIFY),
]

__all__ = ["tools"]
