"""Process-level commands that start a server: ``serve`` and ``mcp stdio``."""

from typing import Annotated

from cyclopts import App, Parameter

from git_manager.core import Connector, Settings


def register(app: App, *, connect: Connector, version: str) -> None:
    """Add ``serve`` and the ``mcp`` command group to ``app``."""

    @app.command
    async def serve(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Start the daemon's REST server on --http.host and --http.port."""
        from git_manager.web.app import serve as serve_rest

        await serve_rest(
            connect=connect, target=settings.target, http=settings.http, version=version
        )

    mcp = App(name="mcp", help="MCP interface.")
    app.command(mcp)

    @mcp.command
    async def stdio(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Serve MCP over stdio, in-process (local mode) or bridged to a daemon (API mode)."""
        from git_manager.mcp.server import serve_stdio

        await serve_stdio(connect=connect, target=settings.target, mcp=settings.mcp)
