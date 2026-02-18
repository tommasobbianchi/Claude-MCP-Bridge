from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from mcp_bridge.config import Settings
    from mcp_bridge.rate_limiter import RateLimiter


def register(
    mcp: FastMCP,
    settings: Settings,
    rate_limiter: RateLimiter,
) -> None:

    @mcp.tool()
    async def file_read(
        path: str,
        line_start: int | None = None,
        line_end: int | None = None,
    ) -> str:
        """Read a file from the server.

        Args:
            path: Absolute or ~ path to the file (must be in allowed dirs)
            line_start: Optional start line (1-based, inclusive)
            line_end: Optional end line (1-based, inclusive)
        """
        from mcp_bridge.sandbox import validate_path

        await rate_limiter.check("file_read")
        resolved = validate_path(path, settings.allowed_dirs)

        if not resolved.is_file():
            return f"ERROR: '{resolved}' is not a file or does not exist"

        size = resolved.stat().st_size
        if size > 1_000_000:
            return (
                f"ERROR: File too large ({size} bytes, max 1MB). "
                "Use line_start/line_end to read a portion."
            )

        content = resolved.read_text(encoding="utf-8", errors="replace")

        if line_start is not None or line_end is not None:
            lines = content.splitlines(keepends=True)
            start = (line_start or 1) - 1
            end = line_end or len(lines)
            content = "".join(lines[start:end])

        return content

    @mcp.tool()
    async def file_write(
        path: str,
        content: str,
        mode: str = "overwrite",
    ) -> str:
        """Write content to a file on the server.

        Args:
            path: Absolute or ~ path (must be in allowed dirs)
            content: Content to write
            mode: "overwrite" (default) or "append"
        """
        from mcp_bridge.sandbox import validate_path

        await rate_limiter.check("file_write")
        resolved = validate_path(path, settings.allowed_dirs)

        resolved.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with open(resolved, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            resolved.write_text(content, encoding="utf-8")

        return f"OK: Written {len(content)} chars to {resolved}"
