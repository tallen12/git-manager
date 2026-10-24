"""CLI application and composition root."""

import inspect
import os
import sys
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Annotated, NoReturn

from cyclopts import App, CycloptsError, Parameter
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from git_manager.cli import branches, config, health, runs, server
from git_manager.config import (
    CheckoutRepoConfig,
    ConfigReader,
    RepoConfigSource,
    YamlConfigFile,
)
from git_manager.core import (
    Connector,
    HttpTarget,
    LocalTarget,
    Operations,
    Settings,
    SocketTarget,
    build_connector,
)
from git_manager.core.compose import LocalRuntime, RuntimeOpener, open_local, process_runner
from git_manager.metadata import package_version

# Exit status for invalid settings, matching cyclopts' own usage errors.
_USAGE_ERROR = 2
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


def build_app(
    *,
    connect: Connector,
    open_runtime: RuntimeOpener,
    read_config: ConfigReader,
    version: str,
) -> App:
    """Build the CLI around injected capabilities.

    The target flags belong to the meta app, so they apply to every command. Commands
    that need a target declare ``settings`` with ``parse=False`` and receive the
    validated ``Settings``; ``connect`` opens the operations for its target,
    ``open_runtime`` opens a local target's whole runtime for ``serve``, and
    ``read_config`` opens a config file directly for process-level commands.
    """
    app = App(name="git-manager", help="Keep git branches rebased.", version=version)
    # One module per domain registers that domain's commands.
    health.register(app, connect=connect)
    config.register(app, connect=connect, read_config=read_config)
    branches.register(app, connect=connect)
    runs.register(app, connect=connect)
    server.register(app, connect=connect, open_runtime=open_runtime, version=version)

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


def local_runtime(
    *, environ: Mapping[str, str], repo_config: RepoConfigSource, version: str
) -> RuntimeOpener:
    """Open a local target through ``open_local`` with this process's runner."""

    def open_runtime(target: LocalTarget) -> AbstractAsyncContextManager[LocalRuntime]:
        return open_local(
            target,
            environ=environ,
            repo_config=repo_config,
            runner=process_runner(environ),
            version=version,
        )

    return open_runtime


def local_connector(
    *, environ: Mapping[str, str], repo_config: RepoConfigSource, version: str
) -> Connector:
    """The connector ``main`` uses: local mode through ``open_local``, API mode over httpx."""
    open_runtime = local_runtime(environ=environ, repo_config=repo_config, version=version)

    @asynccontextmanager
    async def local(target: LocalTarget) -> AsyncGenerator[Operations]:
        async with open_runtime(target) as opened:
            yield opened.service

    return build_connector(local=local)


def main() -> None:
    """Wire concrete implementations and run the CLI."""
    version = package_version()
    repo_config = CheckoutRepoConfig()

    def read_config(path: Path) -> YamlConfigFile:
        return YamlConfigFile(path, environ=os.environ, repo_config=repo_config)

    connect = local_connector(environ=os.environ, repo_config=repo_config, version=version)
    open_runtime = local_runtime(environ=os.environ, repo_config=repo_config, version=version)
    run(
        build_app(
            connect=connect, open_runtime=open_runtime, read_config=read_config, version=version
        )
    )
