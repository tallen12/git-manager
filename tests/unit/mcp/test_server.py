from fastmcp import Client

from git_manager.core import Operations
from git_manager.mcp.server import create_server
from tests.conftest import TEST_VERSION


async def test_health_tool_reports_ok(service: Operations) -> None:
    async with Client(create_server(operations=service)) as client:
        result = await client.call_tool("health", {})

    assert result.structured_content == {"status": "ok", "version": TEST_VERSION}
