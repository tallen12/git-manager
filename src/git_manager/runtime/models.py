"""Process value types."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType


class ProcessUser(StrEnum):
    """The Unix user a command runs as (see Process isolation in the spec).

    Outside the container there are no separate users; the local runner runs every
    command as the current user and logs that isolation is off.
    """

    ORCHESTRATOR = "gm"
    CLAUDE = "gm-claude"
    TESTS = "gm-tests"


def _frozen_env(env: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(env))


@dataclass(frozen=True, slots=True)
class Command:
    """One subprocess to run, as an argument list (never through a shell).

    ``env`` is the complete environment apart from a short allowlist of non-secret
    variables (``PATH``, locale, ``TMPDIR``; see ``isolation.environment``) that runners
    add, so credentials reach a command only when the caller passes them here on purpose.
    """

    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str] = field(default_factory=dict)
    user: ProcessUser = ProcessUser.ORCHESTRATOR
    timeout: timedelta | None = None
    stdin: str | None = None

    def __post_init__(self) -> None:
        if not self.argv:
            msg = "a command needs at least the program name"
            raise ValueError(msg)
        # Callers keep their dict; the command keeps a read-only copy.
        object.__setattr__(self, "env", _frozen_env(self.env))


@dataclass(frozen=True, slots=True)
class ProcessCompleted:
    """The command exited on its own, successfully or not."""

    exit_code: int
    stdout: str
    stderr: str
    duration: timedelta

    @property
    def succeeded(self) -> bool:
        """Whether the command exited 0."""
        return self.exit_code == 0


@dataclass(frozen=True, slots=True)
class ProcessTimedOut:
    """The command ran past its timeout and was killed with its process group."""

    stdout: str
    stderr: str
    duration: timedelta


type ProcessResult = ProcessCompleted | ProcessTimedOut
