import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app():
    os.environ["BEARER_TOKEN"] = "test-token-123"
    os.environ["ALLOWED_DIRS_RAW"] = "/tmp"
    os.environ["BLOCKED_COMMANDS_RAW"] = ""
    os.environ["HOST"] = "127.0.0.1"
    os.environ["PORT"] = "9999"

    # Reset cached settings
    import mcp_bridge.config as cfg
    cfg._settings = None

    from mcp_bridge.server import create_app
    app, _ = create_app()
    return app


@pytest.mark.asyncio
async def test_health_no_auth_required(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_mcp_requires_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/mcp")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_mcp_wrong_token_403(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/mcp", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_mcp_valid_token_passes_auth(app):
    """Verify valid token passes the auth middleware and reaches the MCP layer.

    The session manager isn't initialized without lifespan, so the MCP layer
    raises RuntimeError — but that proves the auth middleware let it through.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="Task group is not initialized"):
            await client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer test-token-123",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0.1"},
                    },
                },
            )
