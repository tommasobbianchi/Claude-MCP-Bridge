from unittest.mock import patch

import pytest

from mcp_bridge.rate_limiter import ConcurrencyLimiter, RateLimiter


@pytest.mark.asyncio
async def test_gpu_status_no_gpu():
    """gpu_status returns N/A when nvidia-smi is not available."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test")
    limiter = RateLimiter(max_per_minute=100)

    from mcp_bridge.tools.gpu_status import register
    register(mcp, limiter)

    with patch("shutil.which", return_value=None):
        result = await mcp.call_tool("gpu_status", {})
        text = str(result)
        assert "N/A" in text


@pytest.mark.asyncio
async def test_rate_limiter_blocks():
    """Rate limiter raises after exceeding limit."""
    limiter = RateLimiter(max_per_minute=2)
    await limiter.check("test_tool")
    await limiter.check("test_tool")
    with pytest.raises(RuntimeError, match="Rate limit exceeded"):
        await limiter.check("test_tool")


@pytest.mark.asyncio
async def test_concurrency_limiter():
    """Concurrency limiter blocks when at capacity."""
    limiter = ConcurrencyLimiter(max_concurrent=1)
    await limiter.acquire()
    with pytest.raises(RuntimeError, match="Max concurrent"):
        await limiter.acquire()
    limiter.release()
    # Should work again after release
    await limiter.acquire()
    limiter.release()
