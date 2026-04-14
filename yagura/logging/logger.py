"""AuditLogger ABC and the log-entry dataclasses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from yagura.llm.provider import TokenUsage
from yagura.plan import PlanState
from yagura.safety.policy import PolicyCheckResult
from yagura.safety.rules import DangerLevel


@dataclass
class OperationLog:
    session_id: str
    user_id: str
    timestamp: datetime
    tool_name: str
    parameters: dict[str, Any]
    result_status: str  # "success", "failure", "skipped"
    token_usage: TokenUsage | None = None
    duration_ms: int | None = None


@dataclass
class AssessmentLog:
    session_id: str
    timestamp: datetime
    tool_name: str
    danger_level: DangerLevel
    assessment_layer: int
    confidence: float
    reason: str
    user_approved: bool | None = None
    policy_check_result: PolicyCheckResult | None = None


@dataclass
class PlanLog:
    session_id: str
    user_id: str
    timestamp: datetime
    plan_json: dict[str, Any]
    confirmed_scope: int
    final_state: PlanState
    total_steps: int
    completed_steps: int
    total_tokens: TokenUsage | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class AuditLogger(ABC):
    """Compliance-ready audit sink.

    Every operation, every assessment, every plan can be logged. The
    default NullLogger is a no-op; FileLogger and StreamLogger write
    JSON lines; users implement this ABC for SIEM, cloud logging, etc.
    """

    @abstractmethod
    async def log_operation(self, entry: OperationLog) -> None: ...

    @abstractmethod
    async def log_assessment(self, entry: AssessmentLog) -> None: ...

    @abstractmethod
    async def log_plan(self, entry: PlanLog) -> None: ...
