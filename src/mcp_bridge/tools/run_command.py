from __future__ import annotations

import asyncio
import os
import time
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
    async def run_command(
        command: str,
        working_directory: str = "~/projects",
        timeout_seconds: int = 60,
    ) -> str:
        """Execute a bash command on the remote server.

        For simple operations (build, test, git, status checks).
        For complex tasks requiring reasoning, use claude_execute instead.

        Args:
            command: Bash command to execute
            working_directory: Working directory (must be in allowed list)
            timeout_seconds: Timeout in seconds (default 60, max 300)
        """
        from mcp_bridge.audit import get_logger, truncate_for_log
        from mcp_bridge.sandbox import validate_command, validate_path

        await rate_limiter.check("run_command")

        cwd = validate_path(working_directory, settings.allowed_dirs)
        validate_command(command, settings.blocked_commands)
        timeout_seconds = min(timeout_seconds, 300)

        start = time.monotonic()
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "TERM": "dumb"},
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"ERROR: Timeout after {timeout_seconds}s"

        elapsed = time.monotonic() - start

        parts: list[str] = []
        if stdout:
            parts.append(stdout.decode("utf-8", errors="replace"))
        if stderr:
            parts.append(
                f"\n--- STDERR ---\n{stderr.decode('utf-8', errors='replace')}"
            )
        parts.append(f"\n--- Exit code: {proc.returncode} | Time: {elapsed:.1f}s ---")

        result = "".join(parts)

        logger = get_logger("run_command")
        logger.info(
            "run_command_completed",
            command_preview=command[:100],
            working_directory=str(cwd),
            exit_code=proc.returncode,
            elapsed_seconds=round(elapsed, 2),
            output_preview=truncate_for_log(result),
        )

        return result
