"""Authentication subsystem."""

from __future__ import annotations

from yagura.auth.apikey import APIKeyAuth
from yagura.auth.noauth import NoAuth
from yagura.auth.provider import AuthProvider, AuthRequest, AuthResult

__all__ = [
    "APIKeyAuth",
    "AuthProvider",
    "AuthRequest",
    "AuthResult",
    "NoAuth",
]
