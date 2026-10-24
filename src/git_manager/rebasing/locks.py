"""In-process branch locks."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager


class InMemoryBranchLocks:
    """``BranchLocks`` for one process; the data-directory lock keeps it the only one."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def hold(self, branch_id: str) -> AbstractAsyncContextManager[None]:
        return self._hold(branch_id)

    def held(self, branch_id: str) -> bool:
        """Whether someone holds ``branch_id`` right now."""
        lock = self._locks.get(branch_id)
        return lock is not None and lock.locked()

    @asynccontextmanager
    async def _hold(self, branch_id: str) -> AsyncGenerator[None]:
        lock = self._locks.setdefault(branch_id, asyncio.Lock())
        async with lock:
            yield
