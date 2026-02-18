from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from mcp_bridge.config import Settings
    from mcp_bridge.rate_limiter import ConcurrencyLimiter, RateLimiter


def register_all_tools(
    mcp: FastMCP,
    settings: Settings,
    rate_limiter: RateLimiter,
    concurrency_limiter: ConcurrencyLimiter,
) -> None:
    """Register all MCP tools with the server."""
    from mcp_bridge.tools.claude_execute import register as reg_claude
    from mcp_bridge.tools.file_ops import register as reg_file
    from mcp_bridge.tools.gpu_status import register as reg_gpu
    from mcp_bridge.tools.project_status import register as reg_project
    from mcp_bridge.tools.run_command import register as reg_run
    from mcp_bridge.tools.system_info import register as reg_system

    reg_claude(mcp, settings, rate_limiter, concurrency_limiter)
    reg_run(mcp, settings, rate_limiter)
    reg_file(mcp, settings, rate_limiter)
    reg_gpu(mcp, rate_limiter)
    reg_project(mcp, settings, rate_limiter)
    reg_system(mcp, rate_limiter)
