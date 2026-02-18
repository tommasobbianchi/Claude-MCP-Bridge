from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from mcp_bridge.rate_limiter import RateLimiter


def register(mcp: FastMCP, rate_limiter: RateLimiter) -> None:

    @mcp.tool()
    async def system_info() -> str:
        """Get system information: uptime, CPU load, RAM, disk usage, top processes."""
        await rate_limiter.check("system_info")

        async def run(cmd: str) -> str:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return stdout.decode().strip()

        parts: list[str] = []

        uptime = await run("uptime")
        parts.append(f"Uptime: {uptime}")

        mem = await run("free -h | head -3")
        parts.append(f"\nMemory:\n{mem}")

        disk = await run("df -h / /home 2>/dev/null")
        parts.append(f"\nDisk:\n{disk}")

        cpu = await run("nproc")
        load = await run("cat /proc/loadavg")
        parts.append(f"\nCPU: {cpu} cores, Load: {load}")

        top = await run("ps aux --sort=-%cpu | head -8")
        parts.append(f"\nTop processes:\n{top}")

        return "\n".join(parts)
