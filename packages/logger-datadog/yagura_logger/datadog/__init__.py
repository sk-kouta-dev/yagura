"""DatadogLogger — forward Yagura audit events to Datadog Logs."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from yagura.logging.logger import (
    AssessmentLog,
    AuditLogger,
    OperationLog,
    PlanLog,
)


class DatadogLogger(AuditLogger):
    """Structured audit logging to Datadog.

    Logs are sent to the v2 Logs API with tags that make them easy to
    slice in dashboards (tool_name, danger_level, user_id).
    """

    def __init__(
        self,
        api_key: str,
        app_key: str | None = None,
        service: str = "yagura-agent",
        env: str = "production",
        site: str = "datadoghq.com",
        source: str = "python",
    ) -> None:
        try:
            from datadog_api_client import Configuration  # type: ignore # noqa: F401
        except ImportError as exc:
            raise ImportError("yagura-logger-datadog requires 'datadog-api-client'") from exc
        self.api_key = api_key
        self.app_key = app_key
        self.service = service
        self.env = env
        self.site = site
        self.source = source

    async def log_operation(self, entry: OperationLog) -> None:
        await self._submit(
            kind="operation",
            message=f"{entry.tool_name} [{entry.result_status}]",
            tags={
                "tool_name": entry.tool_name,
                "result_status": entry.result_status,
                "user_id": entry.user_id,
            },
            attributes=_asdict(entry),
        )

    async def log_assessment(self, entry: AssessmentLog) -> None:
        await self._submit(
            kind="assessment",
            message=f"{entry.tool_name} → {entry.danger_level.name} (layer {entry.assessment_layer})",
            tags={
                "tool_name": entry.tool_name,
                "danger_level": entry.danger_level.name,
                "layer": str(entry.assessment_layer),
            },
            attributes=_asdict(entry),
        )

    async def log_plan(self, entry: PlanLog) -> None:
        await self._submit(
            kind="plan",
            message=f"plan {entry.final_state.value} [{entry.completed_steps}/{entry.total_steps}]",
            tags={
                "final_state": entry.final_state.value,
                "user_id": entry.user_id,
            },
            attributes=_asdict(entry),
        )

    async def _submit(self, kind: str, message: str, tags: dict[str, str], attributes: dict[str, Any]) -> None:
        from datadog_api_client import ApiClient, Configuration  # type: ignore
        from datadog_api_client.v2.api.logs_api import LogsApi  # type: ignore
        from datadog_api_client.v2.model.http_log import HTTPLog  # type: ignore
        from datadog_api_client.v2.model.http_log_item import HTTPLogItem  # type: ignore

        cfg = Configuration()
        cfg.server_variables["site"] = self.site
        cfg.api_key["apiKeyAuth"] = self.api_key
        if self.app_key:
            cfg.api_key["appKeyAuth"] = self.app_key

        ddtags = ",".join(f"{k}:{v}" for k, v in tags.items() if v is not None)

        def _submit_sync() -> None:
            with ApiClient(cfg) as client:
                LogsApi(client).submit_log(
                    body=HTTPLog(
                        [
                            HTTPLogItem(
                                ddsource=self.source,
                                ddtags=f"kind:{kind},env:{self.env},{ddtags}",
                                hostname="yagura",
                                message=f"{kind}: {message} | {json.dumps(attributes, default=str)}",
                                service=self.service,
                            )
                        ]
                    ),
                )

        # The datadog SDK is sync. Run in thread to avoid blocking the event loop.
        await asyncio.to_thread(_submit_sync)


def _asdict(obj: Any) -> dict[str, Any]:
    if is_dataclass(obj):
        return json.loads(json.dumps(asdict(obj), default=_default))
    return json.loads(json.dumps(obj, default=_default))


def _default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value if isinstance(obj.value, (str, int, float, bool)) else obj.name
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


__all__ = ["DatadogLogger"]
