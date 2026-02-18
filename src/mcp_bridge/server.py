"""Claude MCP Bridge Server — Entry Point."""

from __future__ import annotations

import uvicorn
from dotenv import load_dotenv
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_bridge.audit import get_logger, setup_logging
from mcp_bridge.config import get_settings
from mcp_bridge.oauth_provider import InMemoryOAuthProvider
from mcp_bridge.rate_limiter import ConcurrencyLimiter, RateLimiter
from mcp_bridge.tools import register_all_tools


def create_app() -> tuple:
    """Create and configure the MCP server application."""
    load_dotenv()
    settings = get_settings()

    setup_logging(settings.log_dir, settings.log_level, settings.max_log_size_mb)
    logger = get_logger("server")
    logger.info("server_starting", host=settings.host, port=settings.port)

    # OAuth provider and auth settings
    oauth_provider = InMemoryOAuthProvider()

    auth_settings = None
    if settings.public_url:
        auth_settings = AuthSettings(
            issuer_url=settings.public_url,
            resource_server_url=settings.public_url + "/mcp",
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["mcp:tools"],
                default_scopes=["mcp:tools"],
            ),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=[],
        )

    # Disable DNS rebinding protection — Tailscale Funnel changes the Host header
    mcp = FastMCP(
        name="claude-mcp-bridge",
        instructions=(
            "This server provides tools to interact with a remote Ubuntu server "
            "via Claude CLI and direct commands. Use claude_execute for complex "
            "coding tasks, run_command for simple operations."
        ),
        host=settings.host,
        port=settings.port,
        auth_server_provider=oauth_provider if auth_settings else None,
        auth=auth_settings,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )

    # Health check endpoint
    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "server": "claude-mcp-bridge",
            "version": "0.1.0",
        })

    # Rate limiter and concurrency control
    rate_limiter = RateLimiter(max_per_minute=settings.max_requests_per_minute)
    concurrency_limiter = ConcurrencyLimiter(
        max_concurrent=settings.max_concurrent_claude
    )

    # Register all tools
    register_all_tools(mcp, settings, rate_limiter, concurrency_limiter)

    # Build the Starlette app (includes OAuth routes + auth middleware)
    app = mcp.streamable_http_app()

    logger.info(
        "server_configured",
        allowed_dirs=[str(d) for d in settings.allowed_dirs],
        oauth_enabled=bool(auth_settings),
    )

    return app, settings


def main() -> None:
    """Entry point for the server."""
    app, settings = create_app()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
