"""APIKeyAuth — simple mapping from API keys to user ids."""

from __future__ import annotations

from yagura.auth.provider import AuthProvider, AuthRequest, AuthResult
from yagura.errors import AuthenticationFailedError


class APIKeyAuth(AuthProvider):
    """Authenticates callers by an API key → user id mapping.

    The mapping is in-memory by default. For production, wrap this class
    around a secrets manager or a DB-backed store.
    """

    def __init__(self, keys: dict[str, str], roles: dict[str, list[str]] | None = None) -> None:
        self._keys = dict(keys)
        self._roles = dict(roles or {})

    async def authenticate(self, request: AuthRequest) -> AuthResult:
        candidate = request.api_key or request.token
        if candidate is None:
            return AuthResult(authenticated=False, error="no_api_key_provided")
        user_id = self._keys.get(candidate)
        if user_id is None:
            return AuthResult(authenticated=False, error="unknown_api_key")
        return AuthResult(
            authenticated=True,
            user_id=user_id,
            roles=list(self._roles.get(user_id, [])),
        )

    async def get_user_id(self, token: str) -> str:
        user_id = self._keys.get(token)
        if user_id is None:
            raise AuthenticationFailedError("Unknown API key")
        return user_id
