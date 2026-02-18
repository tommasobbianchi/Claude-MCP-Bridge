from __future__ import annotations

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BearerTokenMiddleware:
    """ASGI middleware that validates Bearer token on all HTTP requests
    except explicitly excluded paths."""

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        exclude_paths: set[str] | None = None,
    ) -> None:
        self.app = app
        self.token = token
        self.exclude_paths = exclude_paths or {"/health"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Pass through lifespan, websocket, etc.
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.exclude_paths:
            await self.app(scope, receive, send)
            return

        # Extract Authorization header
        headers = dict(scope.get("headers", []))
        auth_value = headers.get(b"authorization", b"").decode(
            "utf-8", errors="ignore"
        )

        if not auth_value.startswith("Bearer "):
            response = JSONResponse(
                {"error": "Missing or invalid Authorization header"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        provided_token = auth_value[7:]
        if not hmac.compare_digest(provided_token, self.token):
            response = JSONResponse(
                {"error": "Invalid token"},
                status_code=403,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
