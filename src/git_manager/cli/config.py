"""Config commands: ``config show`` and ``set`` (any mode), ``config validate`` (offline)."""

import sys
from typing import Annotated, assert_never

from cyclopts import App, Parameter
from pydantic import JsonValue, TypeAdapter, ValidationError

from git_manager.cli.output import reported
from git_manager.config import ConfigError, ConfigPath, ConfigReader
from git_manager.core import Connector, HttpTarget, LocalTarget, Settings, SocketTarget

_NEEDS_FILE = "config validate checks a config file: pass --config PATH or set GM_TARGET__CONFIG"

_JSON = TypeAdapter[JsonValue](JsonValue)


def parse_key(key: str) -> ConfigPath:
    """A dotted key as a config path; all-digit parts are list indexes.

    ``defaults.cadence.mode`` is ``("defaults", "cadence", "mode")`` and
    ``branches.0.base`` is ``("branches", 0, "base")``.
    """
    return tuple(int(part) if part.isdigit() else part for part in key.split("."))


def parse_value(text: str) -> JsonValue:
    """``text`` as JSON (``true``, ``30``, ``["a"]``, ``null``), or else the plain string."""
    try:
        return _JSON.validate_json(text)
    except ValidationError:
        return text


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

    @config.command(name="set")
    async def set_(
        key: str, value: str, *, settings: Annotated[Settings, Parameter(parse=False)]
    ) -> None:
        """Set KEY (dotted, like defaults.cadence.mode) to VALUE in the config file.

        VALUE is read as JSON when it parses (true, 30, ["a"], null), else as a string.
        Comments in the file are kept. Prints the new effective config as JSON. Over the
        API, sensitive keys (verify, claude, budget, ...) need the approve scope.
        """
        with reported():
            async with connect(settings.target) as operations:
                effective = await operations.config.set(parse_key(key), parse_value(value))
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
