"""The daemon: polls on each branch's interval and runs queued branches one at a time.

``serve`` runs one ``Daemon`` for the life of the process, inside the block that holds
the data-directory lock, so the lock outlives the last run. The poll loop and the worker
are separate tasks, so polling continues while a run is in progress. ``stop`` (from
SIGTERM or SIGINT) ends polling at once and lets the current run finish; runs still
waiting in the queue are not started and are queued again by the next start.
"""

import asyncio
import logging
from datetime import timedelta

from git_manager.branches.models import BranchState
from git_manager.branches.protocols import BranchPoller, RunQueue, Sleeper
from git_manager.config.errors import ConfigError
from git_manager.config.protocols import ConfigOperations
from git_manager.errors import NotFoundError
from git_manager.rebasing.errors import BranchOnHoldError, GitError, RemoteBranchMissingError
from git_manager.rebasing.models import RunTrigger
from git_manager.rebasing.protocols import RunExecutor
from git_manager.store.protocols import BranchRepository

_LOGGER = logging.getLogger(__name__)

# How often the poll loop wakes; each branch is still polled only on its own interval.
DEFAULT_TICK = timedelta(seconds=1)


class AsyncioSleeper:
    """``Sleeper`` on the event loop's clock."""

    async def sleep(self, delay: timedelta) -> None:
        await asyncio.sleep(delay.total_seconds())


class Daemon:
    """The poll loop and the single run worker."""

    def __init__(
        self,
        *,
        poller: BranchPoller,
        queue: RunQueue,
        executor: RunExecutor,
        config: ConfigOperations,
        branches: BranchRepository,
        sleeper: Sleeper,
        tick: timedelta = DEFAULT_TICK,
        logger: logging.Logger = _LOGGER,
    ) -> None:
        self._poller = poller
        self._queue = queue
        self._executor = executor
        self._config = config
        self._branches = branches
        self._sleeper = sleeper
        self._tick = tick
        self._logger = logger
        self._stopping = asyncio.Event()
        # True from taking a run off the queue until it ends: the worker is not idle.
        self._busy = False

    def stop(self) -> None:
        """Ask ``run`` to stop: no more polls or new runs; the current run finishes."""
        self._stopping.set()

    async def run(self) -> None:
        """Poll and work until ``stop``; return once the current run, if any, has finished.

        The caller must hold the data-directory lock for the whole call. An unexpected
        error from polling stops the daemon the same way and is raised after the drain.
        """
        await self._requeue_scheduled()
        worker = asyncio.create_task(self._work(), name="git-manager-worker")
        try:
            await self._poll_until_stopped()
        finally:
            self._stopping.set()
            await self._drain(worker)

    async def _requeue_scheduled(self) -> None:
        # The queue lives in memory: a branch left ``scheduled`` by the previous process
        # would otherwise wait forever, since the poller never queues it again.
        for branch in await self._branches.list():
            if branch.state is BranchState.SCHEDULED:
                self._queue.put(branch.id, trigger=RunTrigger.POLL)

    async def _poll_until_stopped(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._poller.tick(await self._config.show())
            except (GitError, ConfigError) as error:
                # A remote that is briefly unreachable or a config being edited must not
                # stop the daemon; the next tick tries again.
                self._logger.warning("poll failed: %s", error)
            await self._pause()

    async def _pause(self) -> None:
        sleep = asyncio.ensure_future(self._sleeper.sleep(self._tick))
        stopped = asyncio.ensure_future(self._stopping.wait())
        try:
            await asyncio.wait({sleep, stopped}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleep.cancel()
            stopped.cancel()

    async def _work(self) -> None:
        while not self._stopping.is_set():
            async with self._queue.take() as queued:
                self._busy = True
                try:
                    await self._execute(queued.branch_id, trigger=queued.trigger)
                finally:
                    self._busy = False

    async def _execute(self, branch_id: str, *, trigger: RunTrigger) -> None:
        try:
            config = await self._config.show()
            run = await self._executor.run(branch_id, trigger=trigger, config=config)
        except (NotFoundError, BranchOnHoldError, RemoteBranchMissingError) as error:
            # Untracked or put on hold (paused, needs_human, ...) while queued, or gone from
            # the remote: the branch already says so.
            self._logger.info("run of %s not started: %s", branch_id, error)
        except ConfigError as error:
            self._logger.warning("run of %s not started: %s", branch_id, error)
        except Exception:
            # The executor has already left the run and branch in needs_human; one failed
            # run must not stop the worker for every other branch.
            self._logger.exception("run of %s failed", branch_id)
        else:
            self._logger.info("run %s of %s ended in %s", run.id, branch_id, run.outcome)

    async def _drain(self, worker: asyncio.Task[None]) -> None:
        if not self._busy:
            # Idle in ``take``: nothing to finish.
            worker.cancel()
        # ``wait`` does not re-raise the worker's cancellation; our own still propagates.
        await asyncio.wait({worker})
        if not worker.cancelled() and (error := worker.exception()) is not None:
            raise error
