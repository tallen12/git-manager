"""FastMCP server factory."""

from fastmcp import FastMCP

from git_manager.health import HealthReporter, HealthStatus


def create_server(*, reporter: HealthReporter) -> FastMCP:
    """Build the MCP server around injected capabilities."""
    server = FastMCP(name="git-manager")

    @server.tool
    def health() -> HealthStatus:
        """Report whether Git Manager is alive and which version is running."""
        return reporter.status()

    return server
