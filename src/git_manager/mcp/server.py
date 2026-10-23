"""FastMCP server factory."""

from fastmcp import FastMCP

from git_manager.core import Operations
from git_manager.health import HealthStatus


def create_server(*, operations: Operations) -> FastMCP:
    """Build the MCP server around injected operations."""
    server = FastMCP(name="git-manager")

    @server.tool
    async def health() -> HealthStatus:
        """Report whether Git Manager is alive and which version is running."""
        return await operations.health()

    return server
