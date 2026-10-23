"""CLI application and composition root."""

import inspect
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, NoReturn

from cyclopts import App, CycloptsError, Parameter
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from git_manager.cli import config, health, server
from git_manager.config import CheckoutRepoConfig, ConfigReader, ConfigService, YamlConfigFile
from git_manager.core import (
    Connector,
    HttpTarget,
    LocalTarget,
    Operations,
    Service,
    Settings,
    SocketTarget,
    build_connector,
)
from git_manager.core.unavailable import UnavailableBranches, UnavailableRuns
from git_manager.health import HealthService, StaticHealthReporter
from git_manager.metadata import package_version

# Exit status for invalid settings, matching cyclopts' own usage errors.
_USAGE_ERROR = 2
# Replaced domain by domain as M1 lands; see design-docs/feature-plan.md.
_NOT_BUILT_YET = "not implemented yet"
# The token has no flag, so its errors keep the ``target.token`` path.
_TARGET_FLAGS = frozenset(
    {*LocalTarget.model_fields, *HttpTarget.model_fields, *SocketTarget.model_fields} - {"token"}
)


def _describe(detail: ErrorDetails) -> str:
    message = detail["msg"].removeprefix("Value error, ")
    loc = detail["loc"]
    # Our own validators and the target discriminator already name the option.
    if detail["type"] in {"value_error", "target"} or not loc:
        return message
    if detail["type"].startswith("path_") and isinstance(loc[-1], str):
        return f"--{loc[-1].replace('_', '-')} {detail['input']}: {message}"
    # Target fields are plain flags after the union tag pydantic adds (``target.http.url``
    # is ``--url``); anything else, like an unknown key from a file, keeps its dotted path.
    if loc[0] == "target" and len(loc) == 3 and loc[2] in _TARGET_FLAGS:
        return f"--{str(loc[2]).replace('_', '-')}: {message}"
    parts = [part for index, part in enumerate(loc) if not (index == 1 and loc[0] == "target")]
    return f"{'.'.join(str(part) for part in parts)}: {message}"


def _usage_error(error: ValidationError) -> NoReturn:
    for detail in error.errors():
        print(f"error: {_describe(detail)}", file=sys.stderr)
    sys.exit(_USAGE_ERROR)


def _settings(flags: Settings | None) -> Settings:
    """Return the settings cyclopts built from flags, or read them from ``GM_*`` alone."""
    if flags is not None:
        return flags
    try:
        return Settings()
    except ValidationError as error:
        _usage_error(error)


def build_app(*, connect: Connector, read_config: ConfigReader, version: str) -> App:
    """Build the CLI around injected capabilities.

    The target flags belong to the meta app, so they apply to every command. Commands
    that need a target declare ``settings`` with ``parse=False`` and receive the
    validated ``Settings``; ``connect`` opens the operations for its target, and
    ``read_config`` opens a config file directly for process-level commands.
    """
    app = App(name="git-manager", help="Keep git branches rebased.", version=version)
    # One module per domain registers that domain's commands.
    health.register(app, connect=connect)
    config.register(app, connect=connect, read_config=read_config)
    server.register(app, connect=connect, version=version)

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
    health_service = HealthService(reporter=StaticHealthReporter(version=version))
    repo_config = CheckoutRepoConfig()

    def read_config(path: Path) -> YamlConfigFile:
        return YamlConfigFile(path, environ=os.environ, repo_config=repo_config)

    def local(target: LocalTarget) -> Operations:
        return Service(
            health=health_service,
            config=ConfigService(read_config(target.config)),
            branches=UnavailableBranches(_NOT_BUILT_YET),
            runs=UnavailableRuns(_NOT_BUILT_YET),
        )

    connect = build_connector(local=local)
    run(build_app(connect=connect, read_config=read_config, version=version))
