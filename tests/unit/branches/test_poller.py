from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from git_manager.branches import BranchState
from git_manager.branches.poller import Poller, branch_options
from git_manager.branches.queue import FifoRunQueue
from git_manager.config.models import (
    BranchConfig,
    BranchOptions,
    CadenceConfig,
    CadenceMode,
    RepoConfig,
    RepoSection,
)
from git_manager.events import EventKind
from git_manager.rebasing.models import RunTrigger
from tests.conftest import (
    FakeGit,
    FixedClock,
    InMemoryBranches,
    RecordingEventSink,
    make_branch,
    sha,
)

OLD_BASE, HEAD, NEW_BASE = sha(1), sha(2), sha(3)
REPO = RepoSection(url="https://example.com/repo.git")


def config(cadence: CadenceMode = CadenceMode.DEBOUNCE, **branches: BranchOptions) -> RepoConfig:
    return RepoConfig(
        repo=REPO,
        defaults=BranchOptions(cadence=CadenceConfig(mode=cadence)),
        branches=tuple(
            BranchConfig(name=name, base="main", **options.model_dump())
            for name, options in branches.items()
        ),
    )


@dataclass(slots=True)
class CountingGit:
    """``FakeGit`` that records each ``ls_remote`` call."""

    inner: FakeGit
    calls: list[tuple[str, ...]] = field(default_factory=list)

    async def ls_remote(self, refs: Sequence[str]) -> Mapping[str, str]:
        self.calls.append(tuple(refs))
        return await self.inner.ls_remote(refs)


@pytest.fixture
def remote() -> FakeGit:
    return FakeGit(remote={"main": OLD_BASE, "feature/one": HEAD})


@pytest.fixture
def counting(remote: FakeGit) -> CountingGit:
    return CountingGit(remote)


@pytest.fixture
def queue(clock: FixedClock) -> FifoRunQueue:
    return FifoRunQueue(clock=clock)


@pytest.fixture
async def branches() -> InMemoryBranches:
    repository = InMemoryBranches()
    await repository.add(make_branch())
    return repository


@pytest.fixture
def poller(
    counting: CountingGit,
    branches: InMemoryBranches,
    event_sink: RecordingEventSink,
    queue: FifoRunQueue,
    clock: FixedClock,
) -> Poller:
    return Poller(
        git=counting,
        branches=branches,
        events=event_sink,
        queue=queue,
        clock=clock,
    )


async def state(branches: InMemoryBranches) -> BranchState:
    branch = await branches.get("branch-1")
    assert branch is not None
    return branch.state


async def test_one_ls_remote_per_branch_for_base_and_branch(
    poller: Poller, counting: CountingGit
) -> None:
    await poller.tick(config())

    assert counting.calls == [("main", "feature/one")]


async def test_each_branch_is_polled_once_per_interval(
    poller: Poller, counting: CountingGit, clock: FixedClock
) -> None:
    await poller.tick(config())
    clock.advance(timedelta(seconds=30))
    await poller.tick(config())
    assert len(counting.calls) == 1

    clock.advance(timedelta(seconds=30))
    await poller.tick(config())
    assert len(counting.calls) == 2


async def test_per_branch_poll_interval(
    poller: Poller, counting: CountingGit, clock: FixedClock
) -> None:
    slow = config(**{"feature/one": BranchOptions(poll_interval=timedelta(minutes=5))})
    await poller.tick(slow)
    clock.advance(timedelta(minutes=1))
    await poller.tick(slow)

    assert len(counting.calls) == 1


async def test_debounced_change_is_scheduled_and_queued(
    poller: Poller,
    remote: FakeGit,
    branches: InMemoryBranches,
    event_sink: RecordingEventSink,
    queue: FifoRunQueue,
    clock: FixedClock,
) -> None:
    await poller.tick(config())
    remote.remote["main"] = NEW_BASE
    clock.advance(timedelta(minutes=1))
    await poller.tick(config())
    assert await state(branches) is BranchState.BEHIND
    assert queue.waiting() == ()

    for _ in range(10):
        clock.advance(timedelta(minutes=1))
        await poller.tick(config())

    assert await state(branches) is BranchState.SCHEDULED
    assert [(run.branch_id, run.trigger) for run in queue.waiting()] == [
        ("branch-1", RunTrigger.POLL)
    ]
    assert [(event.kind, event.state) for event in event_sink.events] == [
        (EventKind.BASE_MOVED, None),
        (EventKind.STATE_CHANGED, BranchState.BEHIND),
        (EventKind.STATE_CHANGED, BranchState.SCHEDULED),
    ]


async def test_manual_cadence_never_queues(
    poller: Poller,
    remote: FakeGit,
    branches: InMemoryBranches,
    queue: FifoRunQueue,
    clock: FixedClock,
) -> None:
    remote.remote["main"] = NEW_BASE
    for _ in range(5):
        await poller.tick(config(CadenceMode.MANUAL))
        clock.advance(timedelta(hours=1))

    assert await state(branches) is BranchState.BEHIND
    assert queue.waiting() == ()


async def test_deleted_base_cancels_the_queued_run(
    poller: Poller,
    remote: FakeGit,
    branches: InMemoryBranches,
    queue: FifoRunQueue,
    clock: FixedClock,
) -> None:
    remote.remote["main"] = NEW_BASE
    await poller.tick(config(CadenceMode.IMMEDIATE))
    assert len(queue.waiting()) == 1

    del remote.remote["main"]
    clock.advance(timedelta(minutes=1))
    await poller.tick(config(CadenceMode.IMMEDIATE))

    assert await state(branches) is BranchState.BASE_MISSING
    assert queue.waiting() == ()


async def test_paused_branch_records_the_change_without_a_run(
    poller: Poller,
    remote: FakeGit,
    branches: InMemoryBranches,
    event_sink: RecordingEventSink,
    queue: FifoRunQueue,
) -> None:
    await branches.update(make_branch(state=BranchState.PAUSED))
    remote.remote["main"] = NEW_BASE

    await poller.tick(config(CadenceMode.IMMEDIATE))

    assert await state(branches) is BranchState.PAUSED
    assert queue.waiting() == ()
    assert [event.kind for event in event_sink.events] == [EventKind.BASE_MOVED]


async def test_untracked_branches_are_forgotten(
    poller: Poller, branches: InMemoryBranches, counting: CountingGit
) -> None:
    await poller.tick(config())
    await branches.remove("branch-1")
    await poller.tick(config())
    await branches.add(make_branch())

    await poller.tick(config())

    assert len(counting.calls) == 2


def test_branch_options_prefer_the_branch_block() -> None:
    own = BranchOptions(poll_interval=timedelta(seconds=5))
    repo = config(**{"feature/one": own})

    assert branch_options(repo, "feature/one").poll_interval == timedelta(seconds=5)
    assert branch_options(repo, "other") == repo.defaults


@dataclass(slots=True)
class RunDuringLsRemote:
    """``RemoteRefs`` during whose call a run takes the branch and pushes ``pushed``."""

    remote: FakeGit
    branches: InMemoryBranches
    pushed: str

    async def ls_remote(self, refs: Sequence[str]) -> Mapping[str, str]:
        branch = self.branches.rows["branch-1"]
        self.branches.rows["branch-1"] = branch.model_copy(
            update={
                "state": BranchState.REBASING,
                "last_base_sha": NEW_BASE,
                "last_head_sha": self.pushed,
            }
        )
        self.remote.remote["feature/one"] = self.pushed
        return await self.remote.ls_remote(refs)


async def test_a_run_that_starts_during_a_poll_is_not_overwritten(
    remote: FakeGit,
    branches: InMemoryBranches,
    event_sink: RecordingEventSink,
    queue: FifoRunQueue,
    clock: FixedClock,
) -> None:
    # The listed copy is scheduled; by the time ls-remote answers, a run owns the branch.
    branches.rows["branch-1"] = make_branch(state=BranchState.SCHEDULED)
    remote.remote["main"] = OLD_BASE
    poller = Poller(
        git=RunDuringLsRemote(remote, branches, pushed=sha(9)),
        branches=branches,
        events=event_sink,
        queue=queue,
        clock=clock,
    )

    await poller.tick(config(CadenceMode.IMMEDIATE))

    branch = branches.rows["branch-1"]
    assert (branch.state, branch.last_head_sha) == (BranchState.REBASING, sha(9))
    assert EventKind.HEAD_MOVED not in [event.kind for event in event_sink.events]


async def test_a_branch_untracked_during_a_poll_is_skipped(
    remote: FakeGit,
    branches: InMemoryBranches,
    event_sink: RecordingEventSink,
    queue: FifoRunQueue,
    clock: FixedClock,
) -> None:
    @dataclass(slots=True)
    class UntrackDuringLsRemote:
        async def ls_remote(self, refs: Sequence[str]) -> Mapping[str, str]:
            await branches.remove("branch-1")
            return await remote.ls_remote(refs)

    poller = Poller(
        git=UntrackDuringLsRemote(),
        branches=branches,
        events=event_sink,
        queue=queue,
        clock=clock,
    )

    assert await poller.tick(config()) == []
    assert event_sink.events == []
