"""Config commands: ``config show`` (any mode) and ``config validate`` (offline)."""

import sys
from typing import Annotated, assert_never

from cyclopts import App, Parameter

from git_manager.cli.output import reported
from git_manager.config import ConfigError, ConfigReader
from git_manager.core import Connector, HttpTarget, LocalTarget, Settings, SocketTarget

_NEEDS_FILE = "config validate checks a config file: pass --config PATH or set GM_TARGET__CONFIG"


def register(app: App, *, connect: Connector, read_config: ConfigReader) -> None:
    """Add the ``config`` command group to ``app``."""
    config = App(name="config", help="Repo config.")
    app.command(config)

    @config.command
    async def show(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Print the effective config as JSON, with defaults and overrides merged."""
        with reported():
            async with connect(settings.target) as operations:
                effective = await operations.config.show()
        print(effective.model_dump_json(indent=2))

    @config.command
    def validate(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Check the --config file with GM_* overrides, without a daemon or the state.

        Exits 1 and lists every problem when the config is invalid.
        """
        match settings.target:
            case LocalTarget(config=path):
                pass
            case HttpTarget() | SocketTarget():
                print(f"error: {_NEEDS_FILE}", file=sys.stderr)
                sys.exit(1)
            case _:
                assert_never(settings.target)
        try:
            effective = read_config(path).load()
        except ConfigError as error:
            for problem in error.problems:
                print(f"error: {error.source}: {problem}", file=sys.stderr)
            sys.exit(1)
        print(f"ok: {path} ({len(effective.branches)} branches)")
