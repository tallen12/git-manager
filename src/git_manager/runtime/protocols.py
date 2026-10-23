"""Runtime contracts: subprocesses, time and ids, injected so tests can fake them."""

from datetime import datetime
from typing import Protocol

from git_manager.runtime.models import Command, ProcessResult


class ProcessRunner(Protocol):
    """Runs subprocesses; the isolated runner switches users through the supervisor."""

    async def run(self, command: Command) -> ProcessResult:
        """Run ``command`` to completion or until its timeout.

        A non-zero exit is a ``ProcessCompleted``, not an error. Raises ``OSError`` only
        when the program cannot be started at all.
        """
        ...


class Clock(Protocol):
    """The current time."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...


class IdGenerator(Protocol):
    """Unique ids for branches, runs and other records."""

    def new_id(self) -> str:
        """Return an id never returned before by this generator."""
        ...
