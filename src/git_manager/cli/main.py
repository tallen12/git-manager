"""CLI application and composition root."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from pydantic import ValidationError

from git_manager.cli.connect import Connector, build_connector
from git_manager.cli.http_operations import ApiError, ApiUnreachableError
from git_manager.cli.settings import ClientSettings, HttpTarget, LocalTarget, SocketTarget
from git_manager.core import Operations, Service
from git_manager.health import StaticHealthReporter
from git_manager.metadata import package_version

# Exit status for invalid settings, matching cyclopts' own usage errors.
_USAGE_ERROR = 2


@Parameter(name="*")
@dataclass(frozen=True, slots=True)
class Connection:
    """Target flags shared by every command that runs an operation."""

    config: Annotated[
        Path | None, Parameter(help="Config file; run in-process (local mode). [env: GM_CONFIG]")
    ] = None
    url: Annotated[str | None, Parameter(help="Daemon URL; run through the API. [env: GM_URL]")] = (
        None
    )
    token_file: Annotated[
        Path | None,
        Parameter(help="File holding the API token for --url. [env: GM_TOKEN_FILE, GM_TOKEN]"),
    ] = None
    socket: Annotated[
        Path | None,
        Parameter(help="Daemon Unix socket; run through the API. [env: GM_SOCKET]"),
    ] = None

    def settings(self) -> ClientSettings:
        """Merge these flags over ``GM_*`` variables; unset flags leave the variables in charge."""
        flags = {
            "config": self.config,
            "url": self.url,
            "token_file": self.token_file,
            "socket": self.socket,
        }
        return ClientSettings.model_validate({k: v for k, v in flags.items() if v is not None})


def _target(connection: Connection | None) -> LocalTarget | HttpTarget | SocketTarget:
    try:
        return (connection or Connection()).settings().target()
    except ValidationError as error:
        for detail in error.errors():
            print(f"error: {detail['msg'].removeprefix('Value error, ')}", file=sys.stderr)
        sys.exit(_USAGE_ERROR)


def build_app(*, operations: Operations, connect: Connector, version: str) -> App:
    """Build the CLI around injected capabilities.

    ``operations`` serves the in-process servers (``serve``, ``mcp stdio``); ``connect``
    opens the operations for the target each client command selects.
    """
    app = App(name="git-manager", help="Keep git branches rebased.", version=version)

    @app.command
    async def doctor(*, connection: Connection | None = None) -> None:
        """Print the health status as JSON, in local or API mode."""
        async with connect(_target(connection)) as target_operations:
            try:
                status = await target_operations.health()
            except (ApiError, ApiUnreachableError) as error:
                print(f"error: {error}", file=sys.stderr)
                sys.exit(1)
        print(status.model_dump_json())

    @app.command
    def serve(*, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Start the daemon's REST server (MCP is mounted at /mcp in a later milestone)."""
        import uvicorn

        from git_manager.web.app import create_app

        uvicorn.run(create_app(operations=operations, version=version), host=host, port=port)

    mcp = App(name="mcp", help="MCP interface.")
    app.command(mcp)

    @mcp.command
    def stdio() -> None:
        """Serve MCP over stdio.

        Until M4 this serves the tools in-process; M4 turns it into the spec's stdio bridge
        to a running daemon (``--url``).
        """
        from git_manager.mcp.server import create_server

        create_server(operations=operations).run()

    return app


def main() -> None:
    """Wire concrete implementations and run the CLI."""
    version = package_version()
    service = Service(reporter=StaticHealthReporter(version=version))
    # Local mode will load the target's config file once config lands (M1).
    connect = build_connector(local=lambda _target: service)
    build_app(operations=service, connect=connect, version=version)()
