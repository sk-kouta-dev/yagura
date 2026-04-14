"""Custom exception classes for Yagura framework."""

from __future__ import annotations


class YaguraError(Exception):
    """Base exception for all Yagura framework errors."""


class ToolError(YaguraError):
    """Base for tool-related errors."""


class ToolNotFoundError(ToolError):
    """Raised when a referenced tool is not registered."""


class DuplicateToolError(ToolError):
    """Raised when registering a tool whose name already exists."""


class HandlerAlreadyBoundError(ToolError):
    """Raised when binding a handler to a tool that already has one."""


class ToolExecutionError(ToolError):
    """Raised when a tool handler fails during execution."""


class PlanError(YaguraError):
    """Base for plan-related errors."""


class InvalidPlanStateTransitionError(PlanError):
    """Raised when attempting an invalid Plan state transition."""


class PlanGenerationError(PlanError):
    """Raised when the planner LLM fails to produce a valid plan."""


class StepReferenceError(PlanError):
    """Raised when a $step_N reference cannot be resolved."""


class SessionError(YaguraError):
    """Base for session-related errors."""


class SessionNotFoundError(SessionError):
    """Raised when a session lookup fails."""


class ConcurrentPlanError(SessionError):
    """Raised when a user already has an active plan."""


class ResourceConflictError(SessionError):
    """Raised when optimistic locking detects a concurrent modification."""


class SafetyError(YaguraError):
    """Base for safety/assessment errors."""


class DangerAssessmentError(SafetyError):
    """Raised when DangerAssessor cannot determine a danger level."""


class PolicyDeniedError(SafetyError):
    """Raised when a SecurityPolicyProvider rejects an operation."""


class ConfirmationDeniedError(SafetyError):
    """Raised when the user denies confirmation for a dangerous operation."""


class LLMError(YaguraError):
    """Base for LLM provider errors."""


class LLMRateLimitError(LLMError):
    """Raised when the LLM provider returns a rate-limit error."""


class LLMTimeoutError(LLMError):
    """Raised when the LLM provider times out."""


class LLMInvalidResponseError(LLMError):
    """Raised when the LLM returns a response that cannot be parsed."""


class AuthError(YaguraError):
    """Base for authentication errors."""


class AuthenticationFailedError(AuthError):
    """Raised when authentication credentials are invalid."""


class RuleError(YaguraError):
    """Base for rule engine errors."""


class RuleConflictError(RuleError):
    """Raised when a newly registered rule conflicts with an existing one."""
