"""The in-process run queue: first in, first out, one run at a time."""

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from git_manager.branches.runs import QueuedRun
from git_manager.rebasing.models import RunTrigger
from git_manager.runtime.protocols import Clock


class FifoRunQueue:
    """A ``RunQueue`` in memory. A branch waits at most once; it may wait while it runs."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock
        self._waiting: list[QueuedRun] = []
        self._active: QueuedRun | None = None
        # Set whenever a run is added or finishes; takers re-check and wait again.
        self._changed = asyncio.Event()

    def put(self, branch_id: str, *, trigger: RunTrigger) -> bool:
        if any(run.branch_id == branch_id for run in self._waiting):
            return False
        self._waiting.append(QueuedRun(branch_id, trigger, self._clock.now()))
        self._changed.set()
        return True

    def discard(self, branch_id: str) -> bool:
        kept = [run for run in self._waiting if run.branch_id != branch_id]
        removed = len(kept) != len(self._waiting)
        self._waiting = kept
        return removed

    def waiting(self) -> Sequence[QueuedRun]:
        return tuple(self._waiting)

    @property
    def active(self) -> QueuedRun | None:
        """The run handed out by ``take`` and not finished yet."""
        return self._active

    def take(self) -> AbstractAsyncContextManager[QueuedRun]:
        return self._take()

    @asynccontextmanager
    async def _take(self) -> AsyncGenerator[QueuedRun]:
        while self._active is not None or not self._waiting:
            self._changed.clear()
            await self._changed.wait()
        run = self._waiting.pop(0)
        self._active = run
        try:
            yield run
        finally:
            self._active = None
            self._changed.set()
