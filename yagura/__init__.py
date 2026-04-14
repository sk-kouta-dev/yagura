"""Yagura — Safety-native AI agent framework.

Public API surface. Everything else is an internal implementation detail
and may change between versions.
"""

from __future__ import annotations

from yagura.agent import Agent, AgentResponse
from yagura.config import Config
from yagura.plan import (
    PausedState,
    Plan,
    PlanConfirmation,
    PlanExecutor,
    Planner,
    PlanProgress,
    PlanState,
    PlanStep,
    PlanStepSummary,
    PlanSummary,
    StepContext,
    StepStatus,
)
from yagura.presets import safety_presets
from yagura.safety.assessor import DangerAssessment, DangerAssessor
from yagura.safety.policy import PolicyCheckResult, SecurityPolicyProvider
from yagura.safety.reliability import ReliabilityLevel, SearchResult
from yagura.safety.rules import DangerLevel, DangerRules, ExecutionEnvironment
from yagura.tools.tool import ExecutionTarget, Tool, ToolResult

__version__ = "0.1.1"

__all__ = [
    "Agent",
    "AgentResponse",
    "Config",
    "DangerAssessment",
    "DangerAssessor",
    "DangerLevel",
    "DangerRules",
    "ExecutionEnvironment",
    "ExecutionTarget",
    "PausedState",
    "Plan",
    "PlanConfirmation",
    "PlanExecutor",
    "PlanProgress",
    "PlanState",
    "PlanStep",
    "PlanStepSummary",
    "PlanSummary",
    "Planner",
    "PolicyCheckResult",
    "ReliabilityLevel",
    "SearchResult",
    "SecurityPolicyProvider",
    "safety_presets",
    "StepContext",
    "StepStatus",
    "Tool",
    "ToolResult",
    "__version__",
]
