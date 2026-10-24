"""FastMCP server factory and stdio entry point."""

from fastmcp import FastMCP

from git_manager.core import Connector, Operations, Target
from git_manager.health import HealthStatus
from git_manager.mcp.settings import McpSettings


def create_server(*, operations: Operations, mcp: McpSettings) -> FastMCP:
    """Build the MCP server around injected operations."""
    server = FastMCP(name=mcp.name)

    @server.tool
    async def health() -> HealthStatus:
        """Report whether Git Manager is alive and which version is running."""
        return await operations.health.status()

    return server


async def serve_stdio(*, connect: Connector, target: Target, mcp: McpSettings) -> None:
    """Serve MCP over stdio for the operations ``target`` selects.

    With an API target this is the spec's stdio bridge to a running daemon.
    """
    async with connect(target) as operations:
        await create_server(operations=operations, mcp=mcp).run_async(transport="stdio")
