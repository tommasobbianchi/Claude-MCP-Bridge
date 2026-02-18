from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from mcp_bridge.config import Settings
    from mcp_bridge.rate_limiter import ConcurrencyLimiter, RateLimiter


def register(
    mcp: FastMCP,
    settings: Settings,
    rate_limiter: RateLimiter,
    concurrency_limiter: ConcurrencyLimiter,
) -> None:

    @mcp.tool()
    async def claude_execute(
        prompt: str,
        working_directory: str = "~/projects",
        max_turns: int = 5,
        timeout_seconds: int = 300,
        output_format: str = "text",
    ) -> str:
        """Execute a prompt via Claude Code CLI on the remote server.

        Claude CLI has full access to the filesystem, can read/write files,
        run commands, and complete complex coding tasks autonomously.

        Args:
            prompt: The instruction/prompt to execute
            working_directory: Working directory (must be in allowed list)
            max_turns: Maximum agentic turns (default 5, max 20)
            timeout_seconds: Global timeout in seconds (default 300, max 600)
            output_format: Output format: "text" or "json"
        """
        from mcp_bridge.audit import get_logger, truncate_for_log
        from mcp_bridge.sandbox import validate_path

        await rate_limiter.check("claude_execute")

        cwd = validate_path(working_directory, settings.allowed_dirs)
        max_turns = min(max_turns, 20)
        timeout_seconds = min(timeout_seconds, settings.claude_max_timeout)

        await concurrency_limiter.acquire()
        try:
            cmd = [
                settings.claude_cli_path,
                "--print",
                "--dangerously-skip-permissions",
                "--max-turns",
                str(max_turns),
                "--verbose",
            ]
            if output_format == "json":
                cmd.extend(["--output-format", "json"])
            cmd.extend(["--prompt", prompt])

            # CRITICAL: unset CLAUDECODE env vars so claude CLI can start
            env = os.environ.copy()
            env.pop("CLAUDECODE", None)
            env.pop("CLAUDE_CODE_ENTRYPOINT", None)

            start = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"ERROR: Timeout after {timeout_seconds}s. Process killed."

            elapsed = time.monotonic() - start
            result = stdout.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")
                result = (
                    f"Exit code: {proc.returncode}\n\n"
                    f"STDOUT:\n{result}\n\n"
                    f"STDERR:\n{err}"
                )

            logger = get_logger("claude_execute")
            logger.info(
                "claude_execute_completed",
                prompt_preview=prompt[:100],
                working_directory=str(cwd),
                exit_code=proc.returncode,
                elapsed_seconds=round(elapsed, 2),
                output_length=len(result),
                output_preview=truncate_for_log(result),
            )

            return result
        finally:
            concurrency_limiter.release()
