"""OAuth 2.0 provider for single-user MCP server with disk persistence.

Implements the MCP SDK's OAuthAuthorizationServerProvider protocol with:
- Dynamic Client Registration (required by claude.ai)
- Auto-approval (personal server, no consent screen needed)
- File-backed token storage (tokens survive server restarts)
- PKCE support (required by MCP auth spec)
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class InMemoryOAuthProvider:
    """Single-user OAuth provider with auto-approval.

    Tokens are persisted to disk so they survive server restarts.
    Pass token_store_path=None to disable persistence (tests).
    """

    def __init__(
        self,
        token_store_path: Path | None = None,
        public_url: str = "",
    ) -> None:
        self._store_path = token_store_path
        self._public_url = public_url.rstrip("/")
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        # code -> (auth_code, client redirect_uri, state), held until /approve.
        # Deliberately separate from _auth_codes: a code in here is NOT redeemable.
        self._pending: dict[str, tuple[AuthorizationCode, str, str | None]] = {}

        if self._store_path:
            self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load persisted tokens from disk, skipping expired access tokens."""
        if not self._store_path or not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text())
            for cdata in data.get("clients", {}).values():
                c = OAuthClientInformationFull.model_validate(cdata)
                self._clients[c.client_id] = c
            now = time.time()
            for tdata in data.get("access_tokens", {}).values():
                at = AccessToken.model_validate(tdata)
                if at.expires_at is None or now < at.expires_at:
                    self._access_tokens[at.token] = at
            for tdata in data.get("refresh_tokens", {}).values():
                rt = RefreshToken.model_validate(tdata)
                self._refresh_tokens[rt.token] = rt
        except Exception:
            pass  # Corrupted store — start fresh

    def _save(self) -> None:
        """Atomically persist current state to disk."""
        if not self._store_path:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "clients": {
                    cid: c.model_dump(mode="json")
                    for cid, c in self._clients.items()
                },
                "access_tokens": {
                    tok: at.model_dump(mode="json")
                    for tok, at in self._access_tokens.items()
                },
                "refresh_tokens": {
                    tok: rt.model_dump(mode="json")
                    for tok, rt in self._refresh_tokens.items()
                },
            }
            tmp = self._store_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, default=str))
            tmp.replace(self._store_path)
        except Exception:
            pass  # Don't crash the server on persistence errors

    # ------------------------------------------------------------------
    # OAuthAuthorizationServerProvider protocol
    # ------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(
        self, client_info: OAuthClientInformationFull
    ) -> None:
        client_id = secrets.token_urlsafe(24)
        client_secret = secrets.token_urlsafe(48)
        client_info.client_id = client_id
        client_info.client_secret = client_secret
        client_info.client_id_issued_at = int(time.time())
        self._clients[client_id] = client_info
        self._save()

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Mint an authorization code, but withhold it behind the approval gate.

        This server is published to the public internet via Tailscale Funnel, and
        its tools run commands on nativedev. Handing the code straight back to the
        client would let any stranger who finds the URL register and get a token.
        So the redirect goes to our own /approve page instead: the code is only
        released to the client's redirect_uri after the operator secret is entered.
        """
        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + 300,  # 5 min expiry
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        # NOT added to _auth_codes yet. The caller of /authorize sees this code
        # in the /approve URL, so if it were redeemable now they could skip the
        # gate and go straight to /token. It only becomes a real, exchangeable
        # code once release_pending() moves it across.
        self._pending[code] = (auth_code, str(params.redirect_uri), params.state)

        return f"{self._public_url}/approve?code={code}"

    # ------------------------------------------------------------------
    # Approval gate (single-user consent, replaces auto-approval)
    # ------------------------------------------------------------------

    def release_pending(self, code: str) -> str | None:
        """Approve a held code: make it exchangeable and return the redirect URI.

        Returns None if the code is unknown, already released, or expired.
        """
        entry = self._pending.pop(code, None)
        if entry is None:
            return None
        auth_code, redirect_uri, state = entry
        if time.time() > auth_code.expires_at:
            return None
        self._auth_codes[code] = auth_code  # only now is it redeemable
        return construct_redirect_uri(redirect_uri, code=code, state=state)

    def drop_pending(self, code: str) -> None:
        """Discard a held code (denied/expired)."""
        self._pending.pop(code, None)

    def seed_client(
        self,
        client_id: str,
        redirect_uris: list[str],
        client_secret: str | None = None,
    ) -> None:
        """Pre-register a fixed client_id, for a client configured by hand.

        claude.ai lets you type an OAuth client ID into the connector instead of
        letting it self-register; that ID never goes through /register, so it has
        to already exist here or /authorize returns "client not found".
        """
        if client_id in self._clients:
            return
        self._clients[client_id] = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uris=redirect_uris,  # type: ignore[arg-type]
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="mcp:tools",
            token_endpoint_auth_method="none" if not client_secret else "client_secret_post",
            client_id_issued_at=int(time.time()),
        )
        self._save()

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        if code is None:
            return None
        if code.client_id != client.client_id:
            return None
        if time.time() > code.expires_at:
            del self._auth_codes[authorization_code]
            return None
        return code

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        # Remove used code (single-use)
        self._auth_codes.pop(authorization_code.code, None)

        access = secrets.token_urlsafe(48)
        refresh = secrets.token_urlsafe(48)
        expires_in = 3600 * 24  # 24 hours

        self._access_tokens[access] = AccessToken(
            token=access,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + expires_in,
            resource=authorization_code.resource,
        )
        self._refresh_tokens[refresh] = RefreshToken(
            token=refresh,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
        )
        self._save()

        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=refresh,
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        token = self._refresh_tokens.get(refresh_token)
        if token and token.client_id == client.client_id:
            return token
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Revoke old refresh token
        self._refresh_tokens.pop(refresh_token.token, None)

        access = secrets.token_urlsafe(48)
        new_refresh = secrets.token_urlsafe(48)
        expires_in = 3600 * 24

        self._access_tokens[access] = AccessToken(
            token=access,
            client_id=client.client_id,
            scopes=scopes or refresh_token.scopes,
            expires_at=int(time.time()) + expires_in,
        )
        self._refresh_tokens[new_refresh] = RefreshToken(
            token=new_refresh,
            client_id=client.client_id,
            scopes=scopes or refresh_token.scopes,
        )
        self._save()

        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=new_refresh,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        at = self._access_tokens.get(token)
        if at is None:
            return None
        if at.expires_at and time.time() > at.expires_at:
            del self._access_tokens[token]
            self._save()
            return None
        return at

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        if isinstance(token, AccessToken):
            self._access_tokens.pop(token.token, None)
        elif isinstance(token, RefreshToken):
            self._refresh_tokens.pop(token.token, None)
        self._save()
