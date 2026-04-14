"""NoAuth — default single-user AuthProvider."""

from __future__ import annotations

from yagura.auth.provider import AuthProvider, AuthRequest, AuthResult


class NoAuth(AuthProvider):
    """Treats every request as the single built-in user 'default'.

    Suitable for development, single-user CLI usage, and private deployments.
    """

    DEFAULT_USER = "default"

    async def authenticate(self, request: AuthRequest) -> AuthResult:
        return AuthResult(authenticated=True, user_id=self.DEFAULT_USER)

    async def get_user_id(self, token: str) -> str:
        return self.DEFAULT_USER
