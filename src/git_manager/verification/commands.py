"""Verify commands from config, and how a command string becomes an argument list."""

import hashlib
import json
import shlex
from dataclasses import dataclass

from git_manager.config.models import VerifyConfig
from git_manager.verification.errors import InvalidCommandError
from git_manager.verification.models import CommandSource, VerifyCommands


@dataclass(frozen=True, slots=True)
class CommandsMissing:
    """Config sets no test command; the branch goes to ``needs_config``."""


@dataclass(frozen=True, slots=True)
class CommandsInvalid:
    """A configured command cannot be parsed; the branch goes to ``needs_config``."""

    message: str


type ConfigCommands = VerifyCommands | CommandsMissing | CommandsInvalid


def split_command(command: str) -> tuple[str, ...]:
    """Split ``command`` with POSIX shell quoting rules; it then runs without a shell.

    Pipelines, ``&&`` and redirections are not interpreted: a repo that needs them puts
    them in a script or task runner recipe.
    """
    try:
        argv = tuple(shlex.split(command))
    except ValueError as error:
        msg = f"cannot parse verify command {command!r}: {error}"
        raise InvalidCommandError(msg) from error
    if not argv:
        msg = "a verify command needs at least the program name"
        raise InvalidCommandError(msg)
    return argv


def config_commands(config: VerifyConfig) -> ConfigCommands:
    """The commands set in ``config`` (priority 1 in the spec), if it sets a test command.

    Discovery from ``AGENTS.md`` (priority 2) is not done here.
    """
    if config.test is None:
        return CommandsMissing()
    try:
        for command in (config.setup, config.test, config.lint):
            if command is not None:
                split_command(command)
    except InvalidCommandError as error:
        return CommandsInvalid(message=str(error))
    block = {"setup": config.setup, "test": config.test, "lint": config.lint}
    digest = hashlib.sha256(json.dumps(block, sort_keys=True).encode("utf-8")).hexdigest()
    return VerifyCommands(
        setup=config.setup,
        test=config.test,
        lint=config.lint,
        source=CommandSource.CONFIG,
        source_hash=digest,
    )
