"""NullLogger — default AuditLogger that discards all entries."""

from __future__ import annotations

from yagura.logging.logger import (
    AssessmentLog,
    AuditLogger,
    OperationLog,
    PlanLog,
)


class NullLogger(AuditLogger):
    """Discards every log entry. Zero-cost default."""

    async def log_operation(self, entry: OperationLog) -> None:
        return None

    async def log_assessment(self, entry: AssessmentLog) -> None:
        return None

    async def log_plan(self, entry: PlanLog) -> None:
        return None
