from fastmcp import Client

from git_manager.core import Operations
from git_manager.mcp.server import create_server
from git_manager.mcp.settings import McpSettings
from tests.conftest import TEST_VERSION


async def test_health_tool_reports_ok(service: Operations) -> None:
    async with Client(create_server(operations=service, mcp=McpSettings())) as client:
        result = await client.call_tool("health", {})

    assert result.structured_content == {"status": "ok", "version": TEST_VERSION}


def test_server_uses_the_configured_name(service: Operations) -> None:
    server = create_server(operations=service, mcp=McpSettings(name="gm-staging"))

    assert server.name == "gm-staging"
