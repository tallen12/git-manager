"""The poller: ``ls-remote`` each tracked branch per interval and act on what moved."""

from collections.abc import Sequence
from datetime import datetime
from typing import assert_never

from git_manager.branches.models import TrackedBranch
from git_manager.branches.polling import (
    Dequeue,
    Enqueue,
    LeaveQueue,
    Observation,
    Watch,
    observe,
    poll_due,
)
from git_manager.branches.protocols import RemoteRefs, RunScheduler
from git_manager.config.models import BranchOptions, RepoConfig
from git_manager.events.protocols import EventSink
from git_manager.rebasing.models import RunTrigger
from git_manager.runtime.protocols import Clock
from git_manager.store.protocols import BranchRepository


def branch_options(config: RepoConfig, name: str) -> BranchOptions:
    """The effective options of the branch called ``name``: its block, else ``defaults``."""
    return config.branch(name) or config.defaults


class Poller:
    """Detects base and feature-branch movement and feeds the run queue.

    The daemon calls ``tick`` on a short timer with the current config; each branch is
    polled when its own ``poll_interval`` has passed. Runs are executed elsewhere.
    """

    def __init__(
        self,
        *,
        git: RemoteRefs,
        branches: BranchRepository,
        events: EventSink,
        queue: RunScheduler,
        clock: Clock,
    ) -> None:
        self._git = git
        self._branches = branches
        self._events = events
        self._queue = queue
        self._clock = clock
        self._watches: dict[str, Watch] = {}

    async def tick(self, config: RepoConfig) -> Sequence[Observation]:
        """Poll every tracked branch that is due; return what each poll decided."""
        tracked = await self._branches.list()
        # Forget branches that were untracked so a re-track starts fresh.
        live = {branch.id for branch in tracked}
        self._watches = {key: watch for key, watch in self._watches.items() if key in live}
        observations: list[Observation] = []
        for branch in tracked:
            options = branch_options(config, branch.name)
            if poll_due(
                self._watches.get(branch.id), interval=options.poll_interval, now=self._now()
            ):
                observation = await self._poll(branch, options)
                if observation is not None:
                    observations.append(observation)
        return observations

    async def _poll(self, listed: TrackedBranch, options: BranchOptions) -> Observation | None:
        remote = await self._git.ls_remote([listed.base, listed.name])
        # A run may have pushed or changed state during ``ls-remote``: judge (and write)
        # the stored branch, not the listed copy, so its push is recognized as ours and
        # its state is not overwritten.
        branch = await self._branches.get(listed.id)
        if branch is None:
            return None
        observation = observe(
            branch,
            remote=remote,
            watch=self._watches.get(branch.id),
            cadence=options.cadence,
            now=self._now(),
        )
        self._watches[branch.id] = observation.watch
        if (observation.state, observation.reason) != (branch.state, branch.reason):
            await self._branches.update(
                branch.model_copy(update={"state": observation.state, "reason": observation.reason})
            )
        for draft in observation.events:
            await self._events.emit(draft)
        # Queue last, so the run starts after its branch shows scheduled.
        match observation.queue:
            case Enqueue():
                self._queue.put(branch.id, trigger=RunTrigger.POLL)
            case Dequeue():
                self._queue.discard(branch.id)
            case LeaveQueue():
                pass
            case _:
                assert_never(observation.queue)
        return observation

    def _now(self) -> datetime:
        return self._clock.now()
