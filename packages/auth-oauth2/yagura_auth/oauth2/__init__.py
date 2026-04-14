"""OAuth2Provider — OAuth2/OIDC authentication for Yagura.

Supports:
  - Authorization Code flow with PKCE (for web apps).
  - Client Credentials flow (for server-to-server).
  - JWT validation via JWKS.
  - Access token refresh with short-lived caches.
  - Works with any OIDC-compliant provider (Google, Azure AD, Okta,
    Auth0, Keycloak, etc.).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from yagura.auth.provider import AuthProvider, AuthRequest, AuthResult
from yagura.errors import AuthenticationFailedError


@dataclass
class _TokenRecord:
    user_id: str
    roles: list[str]
    expires_at: float
    refresh_token: str | None
    claims: dict[str, Any]


class OAuth2Provider(AuthProvider):
    """OIDC/OAuth2 AuthProvider.

    Parameters:
      issuer: OIDC issuer URL (discovered via /.well-known/openid-configuration).
      client_id: OAuth2 client id.
      client_secret: client secret (omit for public clients using PKCE).
      scopes: OAuth2 scopes.
      audience: optional JWT audience claim to validate.
      user_id_claim: which JWT claim to use as the Yagura user_id
                     (default: "sub"; Azure AD often uses "oid" or "preferred_username").
      roles_claim: JWT claim containing the user's roles.
    """

    def __init__(
        self,
        issuer: str,
        client_id: str,
        client_secret: str | None = None,
        scopes: list[str] | None = None,
        audience: str | None = None,
        user_id_claim: str = "sub",
        roles_claim: str = "roles",
    ) -> None:
        try:
            import httpx  # type: ignore # noqa: F401
            import jwt  # type: ignore # noqa: F401
        except ImportError as exc:
            raise ImportError("yagura-auth-oauth2 requires 'authlib', 'httpx', and 'pyjwt[crypto]'") from exc
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes or ["openid", "profile", "email"]
        self.audience = audience
        self.user_id_claim = user_id_claim
        self.roles_claim = roles_claim

        self._metadata: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._tokens: dict[str, _TokenRecord] = {}

    # --- Discovery --------------------------------------------------------

    async def _discover(self) -> dict[str, Any]:
        if self._metadata is not None:
            return self._metadata
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.issuer}/.well-known/openid-configuration")
            response.raise_for_status()
            self._metadata = response.json()
        return self._metadata

    async def _jwks_keys(self) -> dict[str, Any]:
        if self._jwks is not None:
            return self._jwks
        import httpx

        metadata = await self._discover()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(metadata["jwks_uri"])
            response.raise_for_status()
            self._jwks = response.json()
        return self._jwks

    # --- Authorization Code flow helpers --------------------------------

    async def build_authorize_url(
        self,
        redirect_uri: str,
        state: str | None = None,
        use_pkce: bool = True,
    ) -> dict[str, str]:
        """Return the browser redirect URL + any client-side state needed to finish the flow.

        The authorization endpoint is resolved via OIDC discovery
        (`/.well-known/openid-configuration`) so this works against Google,
        Azure AD, Okta, Auth0, Keycloak, and any OIDC-compliant provider
        regardless of its URL layout.
        """
        state = state or secrets.token_urlsafe(16)
        params: dict[str, str] = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
        }
        verifier: str | None = None
        if use_pkce:
            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            ).rstrip(b"=").decode("ascii")
            params["code_challenge"] = challenge
            params["code_challenge_method"] = "S256"

        metadata = await self._discover()
        authorization_endpoint = metadata.get("authorization_endpoint")
        if not authorization_endpoint:
            raise RuntimeError(
                "OIDC discovery document did not contain 'authorization_endpoint'"
            )
        separator = "&" if "?" in authorization_endpoint else "?"
        authorize_url = f"{authorization_endpoint}{separator}{urlencode(params)}"
        return {
            "url": authorize_url,
            "state": state,
            **({"code_verifier": verifier} if verifier else {}),
        }

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> AuthResult:
        """Exchange an authorization code for tokens, then validate the ID token."""
        import httpx

        metadata = await self._discover()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        if code_verifier:
            data["code_verifier"] = code_verifier

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(metadata["token_endpoint"], data=data)
        if response.status_code != 200:
            return AuthResult(authenticated=False, error=f"token exchange failed: {response.text}")
        tokens = response.json()
        return await self._finalize_tokens(tokens)

    async def client_credentials(self) -> AuthResult:
        """Server-to-server flow. Uses client_id + client_secret."""
        import httpx

        metadata = await self._discover()
        if not self.client_secret:
            return AuthResult(authenticated=False, error="client_credentials flow requires a client_secret")
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": " ".join(self.scopes),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(metadata["token_endpoint"], data=data)
        if response.status_code != 200:
            return AuthResult(authenticated=False, error=f"client_credentials failed: {response.text}")
        return await self._finalize_tokens(response.json())

    # --- AuthProvider interface -----------------------------------------

    async def authenticate(self, request: AuthRequest) -> AuthResult:
        """Accepts a JWT access/id token via `request.token`."""
        token = request.token
        if not token:
            return AuthResult(authenticated=False, error="no_token")
        try:
            claims = await self._validate_jwt(token)
        except Exception as exc:  # noqa: BLE001
            return AuthResult(authenticated=False, error=f"invalid_token: {exc}")
        user_id = str(claims.get(self.user_id_claim, ""))
        if not user_id:
            return AuthResult(authenticated=False, error=f"missing_claim:{self.user_id_claim}")
        roles = list(claims.get(self.roles_claim) or [])
        self._tokens[token] = _TokenRecord(
            user_id=user_id,
            roles=roles,
            expires_at=float(claims.get("exp", 0)),
            refresh_token=None,
            claims=claims,
        )
        return AuthResult(authenticated=True, user_id=user_id, roles=roles)

    async def get_user_id(self, token: str) -> str:
        record = self._tokens.get(token)
        if record and record.expires_at > time.time():
            return record.user_id
        result = await self.authenticate(AuthRequest(token=token))
        if not result.authenticated or not result.user_id:
            raise AuthenticationFailedError(result.error or "authentication_failed")
        return result.user_id

    # --- Internals -------------------------------------------------------

    async def _finalize_tokens(self, tokens: dict[str, Any]) -> AuthResult:
        # Prefer id_token for user identity; fall back to access_token claims.
        validate_target = tokens.get("id_token") or tokens.get("access_token")
        if not validate_target:
            return AuthResult(authenticated=False, error="token response missing id_token/access_token")
        try:
            claims = await self._validate_jwt(validate_target)
        except Exception as exc:  # noqa: BLE001
            return AuthResult(authenticated=False, error=f"jwt_validation_failed: {exc}")

        user_id = str(claims.get(self.user_id_claim, ""))
        roles = list(claims.get(self.roles_claim) or [])

        # Cache by access_token so subsequent get_user_id(token) calls are fast.
        if access := tokens.get("access_token"):
            self._tokens[access] = _TokenRecord(
                user_id=user_id,
                roles=roles,
                expires_at=time.time() + int(tokens.get("expires_in", 3600)),
                refresh_token=tokens.get("refresh_token"),
                claims=claims,
            )
        return AuthResult(authenticated=True, user_id=user_id, roles=roles)

    async def _validate_jwt(self, token: str) -> dict[str, Any]:
        import jwt
        from jwt import PyJWKClient

        metadata = await self._discover()
        jwk_client = PyJWKClient(metadata["jwks_uri"])
        signing_key = jwk_client.get_signing_key_from_jwt(token).key
        options: dict[str, Any] = {"verify_aud": bool(self.audience)}
        kwargs: dict[str, Any] = {"algorithms": metadata.get("id_token_signing_alg_values_supported") or ["RS256"], "options": options}
        if self.audience:
            kwargs["audience"] = self.audience
        return jwt.decode(token, signing_key, **kwargs)


__all__ = ["OAuth2Provider"]
