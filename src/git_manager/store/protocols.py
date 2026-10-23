"""Persistence contracts, one repository per record type.

Writes are atomic per call. Implementations raise ``NotFoundError`` from ``core.errors``
when an update or removal names a record that does not exist.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from git_manager.branches.models import TrackedBranch
from git_manager.events.models import Event, EventDraft
from git_manager.rebasing.models import Run


class BranchRepository(Protocol):
    """Tracked branches."""

    async def add(self, branch: TrackedBranch) -> None:
        """Store a new branch. Raises ``ConflictError`` if its id or name exists."""
        ...

    async def get(self, branch_id: str) -> TrackedBranch | None:
        """Return the branch with ``branch_id``, if any."""
        ...

    async def find(self, name: str) -> TrackedBranch | None:
        """Return the branch called ``name``, if tracked."""
        ...

    async def list(self) -> Sequence[TrackedBranch]:
        """Return every tracked branch, ordered by name."""
        ...

    async def update(self, branch: TrackedBranch) -> None:
        """Replace the stored branch with the same id."""
        ...

    async def remove(self, branch_id: str) -> None:
        """Delete a branch; its runs and events stay."""
        ...


class RunRepository(Protocol):
    """Rebase runs."""

    async def add(self, run: Run) -> None:
        """Store a new run. Raises ``ConflictError`` if its id exists."""
        ...

    async def get(self, run_id: str) -> Run | None:
        """Return the run with ``run_id``, if any."""
        ...

    async def list(self, *, branch_id: str | None = None, limit: int = 50) -> Sequence[Run]:
        """Return runs newest first, optionally for one branch."""
        ...

    async def update(self, run: Run) -> None:
        """Replace the stored run with the same id."""
        ...


class EventRepository(Protocol):
    """The event log."""

    async def append(self, draft: EventDraft, *, at: datetime) -> Event:
        """Store ``draft`` with the next id and return the recorded event."""
        ...

    async def list(self, *, after: int = 0, limit: int = 100) -> Sequence[Event]:
        """Return events with an id above ``after``, oldest first."""
        ...
