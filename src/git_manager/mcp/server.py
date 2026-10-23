"""FastMCP server factory and stdio entry point."""

from fastmcp import FastMCP

from git_manager.core import Connector, Operations, Target
from git_manager.health import HealthStatus


def create_server(*, operations: Operations) -> FastMCP:
    """Build the MCP server around injected operations."""
    server = FastMCP(name="git-manager")

    @server.tool
    async def health() -> HealthStatus:
        """Report whether Git Manager is alive and which version is running."""
        return await operations.health()

    return server


async def serve_stdio(*, connect: Connector, target: Target) -> None:
    """Serve MCP over stdio for the operations ``target`` selects.

    With an API target this is the spec's stdio bridge to a running daemon.
    """
    async with connect(target) as operations:
        await create_server(operations=operations).run_async(transport="stdio")
