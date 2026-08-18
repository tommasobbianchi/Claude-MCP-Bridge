"""Claude MCP Bridge Server — Entry Point."""

from __future__ import annotations

from hmac import compare_digest
from html import escape
from urllib.parse import quote

import uvicorn
from dotenv import load_dotenv
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

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
    token_store = settings.log_dir / "tokens.json"
    oauth_provider = InMemoryOAuthProvider(
        token_store_path=token_store,
        public_url=settings.public_url,
    )

    # Pre-register hand-configured client IDs (claude.ai lets you type one in
    # instead of self-registering; such an ID never hits /register).
    for cid in settings.static_client_ids:
        oauth_provider.seed_client(
            cid, redirect_uris=["https://claude.ai/api/mcp/auth_callback"]
        )

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

    # ------------------------------------------------------------------
    # Approval gate — the only thing standing between the public internet
    # and claude_execute. /authorize parks the code here; it is released to
    # the client only on the operator secret.
    # ------------------------------------------------------------------

    @mcp.custom_route("/approve", methods=["GET"])
    async def approve_form(request: Request) -> HTMLResponse:
        code = request.query_params.get("code", "")
        bad = request.query_params.get("bad")
        warn = (
            '<p style="color:#c00">Wrong secret — try again.</p>' if bad else ""
        )
        return HTMLResponse(
            "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Approve MCP connection</title>"
            "<body style='font-family:system-ui;max-width:24rem;margin:4rem auto;padding:0 1rem'>"
            "<h2>Approve MCP connection</h2>"
            "<p>A client is asking to connect to <b>nativedev</b>. "
            "Enter the bridge secret to approve.</p>"
            f"{warn}"
            "<form method=post action='/approve'>"
            f"<input type=hidden name=code value='{escape(code)}'>"
            "<input type=password name=secret autofocus required "
            "style='width:100%;padding:.6rem;font-size:1rem'>"
            "<button type=submit style='margin-top:.8rem;padding:.6rem 1.2rem;font-size:1rem'>"
            "Approve</button></form></body>",
            status_code=401 if bad else 200,
        )

    @mcp.custom_route("/approve", methods=["POST"])
    async def approve_submit(request: Request):
        form = await request.form()
        code = str(form.get("code", ""))
        secret = str(form.get("secret", ""))
        logger = get_logger("approve")

        # compare_digest: constant time, so the secret can't be guessed by timing
        if not compare_digest(secret, settings.bearer_token):
            logger.warning("approve_rejected", client_host=request.client.host if request.client else "?")
            return RedirectResponse(f"/approve?code={quote(code)}&bad=1", status_code=303)

        target = oauth_provider.release_pending(code)
        if target is None:
            return HTMLResponse(
                "<body style='font-family:system-ui;margin:4rem auto;max-width:24rem'>"
                "<h2>Link expired</h2><p>Start the connection again from the client.</p>",
                status_code=400,
            )
        logger.info("approve_granted")
        return RedirectResponse(target, status_code=302)

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
