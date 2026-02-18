"""Tests for OAuth 2.0 authentication (InMemoryOAuthProvider + app endpoints)."""

import os
import time

import pytest
from httpx import ASGITransport, AsyncClient

from mcp_bridge.oauth_provider import InMemoryOAuthProvider
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider():
    return InMemoryOAuthProvider()


@pytest.fixture
def app():
    os.environ["BEARER_TOKEN"] = "test-token-123"
    os.environ["ALLOWED_DIRS_RAW"] = "/tmp"
    os.environ["BLOCKED_COMMANDS_RAW"] = ""
    os.environ["HOST"] = "127.0.0.1"
    os.environ["PORT"] = "9999"
    os.environ["PUBLIC_URL"] = "http://localhost:9999"

    import mcp_bridge.config as cfg
    cfg._settings = None

    from mcp_bridge.server import create_app
    app, _ = create_app()

    yield app

    os.environ.pop("PUBLIC_URL", None)
    cfg._settings = None


async def _register_client(provider: InMemoryOAuthProvider) -> OAuthClientInformationFull:
    """Helper: register a client and return the populated client info."""
    client_info = OAuthClientInformationFull(
        client_id="placeholder",
        redirect_uris=[AnyUrl("http://localhost/callback")],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="client_secret_post",
    )
    await provider.register_client(client_info)
    return client_info


# ---------------------------------------------------------------------------
# InMemoryOAuthProvider unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_and_get_client(provider):
    client = await _register_client(provider)
    assert client.client_id != "placeholder"
    assert client.client_secret is not None

    retrieved = await provider.get_client(client.client_id)
    assert retrieved is not None
    assert retrieved.client_id == client.client_id


@pytest.mark.asyncio
async def test_get_unknown_client_returns_none(provider):
    assert await provider.get_client("nonexistent") is None


@pytest.mark.asyncio
async def test_authorize_and_exchange(provider):
    client = await _register_client(provider)

    params = AuthorizationParams(
        client_id=client.client_id,
        redirect_uri=AnyUrl("http://localhost/callback"),
        redirect_uri_provided_explicitly=True,
        state="test-state",
        scopes=["mcp:tools"],
        code_challenge="challenge123",
        code_challenge_method="S256",
    )
    redirect_url = await provider.authorize(client, params)
    assert "code=" in redirect_url
    assert "state=test-state" in redirect_url

    # Extract code from redirect URL
    code = redirect_url.split("code=")[1].split("&")[0]

    auth_code = await provider.load_authorization_code(client, code)
    assert auth_code is not None
    assert auth_code.client_id == client.client_id

    token = await provider.exchange_authorization_code(client, auth_code)
    assert token.access_token
    assert token.refresh_token
    assert token.token_type == "Bearer"

    # Code is single-use — loading again should return None
    assert await provider.load_authorization_code(client, code) is None


@pytest.mark.asyncio
async def test_refresh_token_flow(provider):
    client = await _register_client(provider)
    params = AuthorizationParams(
        client_id=client.client_id,
        redirect_uri=AnyUrl("http://localhost/callback"),
        redirect_uri_provided_explicitly=True,
        state="s",
        scopes=["mcp:tools"],
        code_challenge="c",
        code_challenge_method="S256",
    )
    redirect_url = await provider.authorize(client, params)
    code = redirect_url.split("code=")[1].split("&")[0]
    auth_code = await provider.load_authorization_code(client, code)
    token = await provider.exchange_authorization_code(client, auth_code)

    # Refresh
    rt = await provider.load_refresh_token(client, token.refresh_token)
    assert rt is not None
    new_token = await provider.exchange_refresh_token(client, rt, ["mcp:tools"])
    assert new_token.access_token != token.access_token
    assert new_token.refresh_token != token.refresh_token

    # Old refresh token is revoked
    assert await provider.load_refresh_token(client, token.refresh_token) is None


@pytest.mark.asyncio
async def test_expired_auth_code(provider):
    client = await _register_client(provider)
    params = AuthorizationParams(
        client_id=client.client_id,
        redirect_uri=AnyUrl("http://localhost/callback"),
        redirect_uri_provided_explicitly=True,
        state="s",
        scopes=[],
        code_challenge="c",
        code_challenge_method="S256",
    )
    redirect_url = await provider.authorize(client, params)
    code = redirect_url.split("code=")[1].split("&")[0]

    # Expire the code manually
    provider._auth_codes[code].expires_at = time.time() - 1

    assert await provider.load_authorization_code(client, code) is None


@pytest.mark.asyncio
async def test_expired_access_token(provider):
    client = await _register_client(provider)
    params = AuthorizationParams(
        client_id=client.client_id,
        redirect_uri=AnyUrl("http://localhost/callback"),
        redirect_uri_provided_explicitly=True,
        state="s",
        scopes=[],
        code_challenge="c",
        code_challenge_method="S256",
    )
    redirect_url = await provider.authorize(client, params)
    code = redirect_url.split("code=")[1].split("&")[0]
    auth_code = await provider.load_authorization_code(client, code)
    token = await provider.exchange_authorization_code(client, auth_code)

    # Expire the access token manually
    provider._access_tokens[token.access_token].expires_at = int(time.time()) - 1

    assert await provider.load_access_token(token.access_token) is None


@pytest.mark.asyncio
async def test_revoke_access_token(provider):
    client = await _register_client(provider)
    params = AuthorizationParams(
        client_id=client.client_id,
        redirect_uri=AnyUrl("http://localhost/callback"),
        redirect_uri_provided_explicitly=True,
        state="s",
        scopes=[],
        code_challenge="c",
        code_challenge_method="S256",
    )
    redirect_url = await provider.authorize(client, params)
    code = redirect_url.split("code=")[1].split("&")[0]
    auth_code = await provider.load_authorization_code(client, code)
    token = await provider.exchange_authorization_code(client, auth_code)

    at = await provider.load_access_token(token.access_token)
    assert at is not None
    await provider.revoke_token(at)
    assert await provider.load_access_token(token.access_token) is None


@pytest.mark.asyncio
async def test_wrong_client_cannot_load_code(provider):
    client_a = await _register_client(provider)
    client_b = await _register_client(provider)

    params = AuthorizationParams(
        client_id=client_a.client_id,
        redirect_uri=AnyUrl("http://localhost/callback"),
        redirect_uri_provided_explicitly=True,
        state="s",
        scopes=[],
        code_challenge="c",
        code_challenge_method="S256",
    )
    redirect_url = await provider.authorize(client_a, params)
    code = redirect_url.split("code=")[1].split("&")[0]

    # Client B cannot load Client A's code
    assert await provider.load_authorization_code(client_b, code) is None


# ---------------------------------------------------------------------------
# App-level endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_no_auth_required(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_oauth_discovery(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/.well-known/oauth-authorization-server")
        assert r.status_code == 200
        data = r.json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data


@pytest.mark.asyncio
async def test_mcp_without_auth_returns_401(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1"},
            },
        })
        assert r.status_code == 401
