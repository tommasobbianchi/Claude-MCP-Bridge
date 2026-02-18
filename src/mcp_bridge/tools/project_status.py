from __future__ import annotations

import asyncio
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
    async def project_status(
        project_path: str,
        include_diff: bool = False,
        log_count: int = 5,
    ) -> str:
        """Get git status of a project: branch, status, recent commits, optionally diff.

        Args:
            project_path: Path to the project (must be in allowed dirs)
            include_diff: Include diff of uncommitted changes
            log_count: Number of recent commits to show (default 5)
        """
        from mcp_bridge.sandbox import validate_path

        await rate_limiter.check("project_status")
        cwd = validate_path(project_path, settings.allowed_dirs)

        async def run_git(args: list[str]) -> str:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                return f"(git error: {stderr.decode().strip()})"
            return stdout.decode().strip()

        parts: list[str] = []

        branch = await run_git(["branch", "--show-current"])
        parts.append(f"Branch: {branch}")

        status = await run_git(["status", "--short"])
        parts.append(f"\nStatus:\n{status or '(clean)'}")

        log = await run_git(["log", "--oneline", f"-{log_count}"])
        parts.append(f"\nRecent commits:\n{log}")

        if include_diff:
            diff = await run_git(["diff"])
            if diff:
                if len(diff) > 5000:
                    diff = diff[:5000] + f"\n... [truncated, {len(diff)} chars total]"
                parts.append(f"\nDiff:\n{diff}")
            else:
                parts.append("\nDiff: (no unstaged changes)")

        return "\n".join(parts)
