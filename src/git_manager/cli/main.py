"""CLI application and composition root."""

import inspect
import sys
from collections.abc import Sequence
from typing import Annotated, NoReturn

from cyclopts import App, CycloptsError, Parameter
from pydantic import ValidationError

from git_manager.core import (
    ApiError,
    ApiUnreachableError,
    Connector,
    Service,
    Settings,
    build_connector,
)
from git_manager.health import StaticHealthReporter
from git_manager.metadata import package_version

# Exit status for invalid settings, matching cyclopts' own usage errors.
_USAGE_ERROR = 2


def _usage_error(error: ValidationError) -> NoReturn:
    for detail in error.errors():
        message = detail["msg"].removeprefix("Value error, ")
        # Path checks do not name the option or path; the other messages already do.
        option = detail["loc"][-1] if detail["loc"] else None
        if detail["type"].startswith("path_") and isinstance(option, str):
            message = f"--{option.replace('_', '-')} {detail['input']}: {message}"
        print(f"error: {message}", file=sys.stderr)
    sys.exit(_USAGE_ERROR)


def _settings(flags: Settings | None) -> Settings:
    """Return the settings cyclopts built from flags, or read them from ``GM_*`` alone."""
    if flags is not None:
        return flags
    try:
        return Settings()
    except ValidationError as error:
        _usage_error(error)


def build_app(*, connect: Connector, version: str) -> App:
    """Build the CLI around injected capabilities.

    The target flags belong to the meta app, so they apply to every command. Commands
    that need a target declare ``settings`` with ``parse=False`` and receive the
    validated ``Settings``; ``connect`` opens the operations for its target.
    """
    app = App(name="git-manager", help="Keep git branches rebased.", version=version)

    @app.command
    async def doctor(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Print the health status as JSON, in local or API mode."""
        async with connect(settings.target) as operations:
            try:
                status = await operations.health()
            except (ApiError, ApiUnreachableError) as error:
                print(f"error: {error}", file=sys.stderr)
                sys.exit(1)
        print(status.model_dump_json())

    @app.command
    async def serve(
        *,
        settings: Annotated[Settings, Parameter(parse=False)],
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        """Start the daemon's REST server (MCP is mounted at /mcp in a later milestone)."""
        from git_manager.web.app import serve as serve_rest

        await serve_rest(
            connect=connect, target=settings.target, version=version, host=host, port=port
        )

    mcp = App(name="mcp", help="MCP interface.")
    app.command(mcp)

    @mcp.command
    async def stdio(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Serve MCP over stdio, in-process (local mode) or bridged to a daemon (API mode)."""
        from git_manager.mcp.server import serve_stdio

        await serve_stdio(connect=connect, target=settings.target)

    @app.meta.default
    async def launch(
        *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
        settings: Annotated[Settings | None, Parameter(name="*")] = None,
    ) -> None:
        command, bound, ignored = app.parse_args(tokens)
        if "settings" in ignored:
            bound.arguments["settings"] = _settings(settings)
        result = command(*bound.args, **bound.kwargs)
        if inspect.isawaitable(result):
            await result

    return app


def run(app: App, tokens: Sequence[str] | None = None) -> None:
    """Run ``app`` through its meta app, reporting invalid flags like invalid variables."""
    try:
        app.meta(tokens, exit_on_error=False, print_error=False)
    except CycloptsError as error:
        if isinstance(error.__cause__, ValidationError):
            _usage_error(error.__cause__)
        print(f"error: {error}", file=sys.stderr)
        sys.exit(_USAGE_ERROR)


def main() -> None:
    """Wire concrete implementations and run the CLI."""
    version = package_version()
    service = Service(reporter=StaticHealthReporter(version=version))
    # Local mode will load the target's config file once config lands (M1).
    connect = build_connector(local=lambda _target: service)
    run(build_app(connect=connect, version=version))
