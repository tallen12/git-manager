"""Process-level commands that start a server: ``serve`` and ``mcp stdio``."""

from typing import Annotated, assert_never

from cyclopts import App, Parameter

from git_manager.cli.output import fail, reported
from git_manager.core import (
    Connector,
    HttpTarget,
    LocalTarget,
    OperationError,
    Settings,
    SocketTarget,
)
from git_manager.core.compose import RuntimeOpener

SERVE_NEEDS_CONFIG = (
    "serve runs the daemon on a data directory: give it --config (GM_TARGET__CONFIG), "
    "not --url or --socket"
)


def register(app: App, *, connect: Connector, open_runtime: RuntimeOpener, version: str) -> None:
    """Add ``serve`` and the ``mcp`` command group to ``app``."""

    @app.command
    async def serve(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Run the daemon: poll and rebase tracked branches, and serve REST on --http.host
        and --http.port, until SIGTERM or SIGINT. A run in progress finishes first.
        """
        from git_manager.web.daemon import serve_daemon

        match settings.target:
            case LocalTarget() as target:
                with reported():
                    async with open_runtime(target) as runtime:
                        await serve_daemon(runtime, http=settings.http, version=version)
            case HttpTarget() | SocketTarget():
                fail(OperationError(SERVE_NEEDS_CONFIG))
            case _:
                assert_never(settings.target)

    mcp = App(name="mcp", help="MCP interface.")
    app.command(mcp)

    @mcp.command
    async def stdio(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Serve MCP over stdio, in-process (local mode) or bridged to a daemon (API mode)."""
        from git_manager.mcp.server import serve_stdio

        await serve_stdio(connect=connect, target=settings.target, mcp=settings.mcp)
