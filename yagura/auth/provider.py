"""AuthProvider ABC and AuthRequest/AuthResult."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AuthRequest:
    """Credentials submitted by a caller for authentication."""

    token: str | None = None
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    extras: dict[str, str] = field(default_factory=dict)


@dataclass
class AuthResult:
    authenticated: bool
    user_id: str | None = None
    roles: list[str] = field(default_factory=list)
    error: str | None = None


class AuthProvider(ABC):
    """Pluggable authentication backend."""

    @abstractmethod
    async def authenticate(self, request: AuthRequest) -> AuthResult:
        """Validate credentials and return the authenticated user id / roles."""

    @abstractmethod
    async def get_user_id(self, token: str) -> str:
        """Resolve a previously issued token back into a user id."""
