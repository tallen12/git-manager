"""CLI application and composition root."""

from cyclopts import App

from git_manager.health import HealthReporter, StaticHealthReporter
from git_manager.metadata import package_version


def build_app(*, reporter: HealthReporter, version: str) -> App:
    """Build the CLI around injected capabilities."""
    app = App(name="git-manager", help="Keep git branches rebased.", version=version)

    @app.command
    def health() -> None:
        """Print the local health status as JSON."""
        print(reporter.status().model_dump_json())

    @app.command
    def web(*, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Start the REST server (MCP is mounted at /mcp in a later milestone)."""
        import uvicorn

        from git_manager.web.app import create_app

        uvicorn.run(create_app(reporter=reporter, version=version), host=host, port=port)

    mcp = App(name="mcp", help="MCP interface.")
    app.command(mcp)

    @mcp.command
    def stdio() -> None:
        """Serve MCP over stdio.

        Until M4 this serves the tools in-process; M4 turns it into the spec's stdio bridge
        to a running daemon (``--url``).
        """
        from git_manager.mcp.server import create_server

        create_server(reporter=reporter).run()

    return app


def main() -> None:
    """Wire concrete implementations and run the CLI."""
    version = package_version()
    build_app(reporter=StaticHealthReporter(version=version), version=version)()
