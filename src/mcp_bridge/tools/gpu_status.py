from __future__ import annotations

import asyncio
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from mcp_bridge.rate_limiter import RateLimiter


def register(mcp: FastMCP, rate_limiter: RateLimiter) -> None:

    @mcp.tool()
    async def gpu_status() -> str:
        """Get GPU status: model, VRAM usage, temperature, running processes.

        Returns N/A if no NVIDIA GPU is available.
        """
        await rate_limiter.check("gpu_status")

        if not shutil.which("nvidia-smi"):
            return "GPU: N/A (nvidia-smi not found on this system)"

        query = (
            "gpu_name,gpu_bus_id,memory.total,memory.used,memory.free,"
            "temperature.gpu,utilization.gpu,utilization.memory"
        )
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            f"--query-gpu={query}",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode != 0:
            return f"GPU: Error running nvidia-smi: {stderr.decode()}"

        lines = stdout.decode().strip().split("\n")
        result: list[str] = []
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 8:
                result.append(
                    f"GPU: {parts[0]} (Bus: {parts[1]})\n"
                    f"  VRAM: {parts[3]}MB / {parts[2]}MB (free: {parts[4]}MB)\n"
                    f"  Temperature: {parts[5]}C\n"
                    f"  Utilization: GPU {parts[6]}%, Memory {parts[7]}%"
                )

        proc2 = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-compute-apps=pid,name,used_gpu_memory",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=10)

        if stdout2.strip():
            result.append("\nRunning GPU processes:")
            for pline in stdout2.decode().strip().split("\n"):
                result.append(f"  {pline.strip()}")
        else:
            result.append("\nNo GPU processes running")

        return "\n".join(result)
