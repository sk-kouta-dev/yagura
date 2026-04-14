"""SecurityPolicyProvider interface and PolicyCheckResult."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from yagura.safety.rules import DangerLevel


@dataclass
class PolicyCheckResult:
    """Outcome of a SecurityPolicyProvider check."""

    allowed: bool
    reason: str | None = None
    requires_admin_approval: bool = False


class SecurityPolicyProvider(ABC):
    """Enterprise security policy integration point.

    Called for DESTRUCTIVE and INSTALL operations. Implementations can
    consult policy DBs, RBAC systems, or external compliance services.
    """

    @abstractmethod
    async def check(
        self,
        tool_name: str,
        params: dict[str, Any],
        danger_level: DangerLevel,
    ) -> PolicyCheckResult:
        """Evaluate the proposed operation against security policy."""
