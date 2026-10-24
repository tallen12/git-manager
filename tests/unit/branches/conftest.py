"""A branch service wired to the shared fakes, and fakes for the daemon's collaborators."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from git_manager.branches import BranchState, TrackedBranch
from git_manager.branches.results import SyncCompleted, SyncOutcome
from git_manager.branches.service import BranchService
from git_manager.config.models import RepoConfig, RepoSection
from git_manager.rebasing.locks import InMemoryBranchLocks
from git_manager.rebasing.models import Run, RunTrigger
from tests.conftest import (
    FakeGit,
    FixedClock,
    InMemoryBranches,
    RecordingEventSink,
    SequentialIds,
    make_run,
    sha,
)

# On the remote, ``main`` is at BASE and ``feature/one`` at HEAD; they fork at FORK.
FORK, HEAD, BASE = sha(1), sha(2), sha(3)
URL = "https://example.com/repo.git"


@dataclass(slots=True)
class StaticConfig:
    """``ConfigOperations`` serving one config, or raising ``error`` while it is set."""

    config: RepoConfig = field(default_factory=lambda: RepoConfig(repo=RepoSection(url=URL)))
    error: Exception | None = None

    async def show(self) -> RepoConfig:
        if self.error is not None:
            raise self.error
        return self.config


@dataclass(slots=True)
class RecordingSyncer:
    """``BranchSyncer`` that records each branch and reports a finished run for it."""

    synced: list[TrackedBranch] = field(default_factory=list)

    async def sync(self, branch: TrackedBranch) -> SyncOutcome:
        self.synced.append(branch)
        return SyncCompleted(run=make_run(branch_id=branch.id))


@dataclass(frozen=True, slots=True)
class BranchHarness:
    """The service and every fake it talks to."""

    service: BranchService
    git: FakeGit
    branches: InMemoryBranches
    events: RecordingEventSink
    syncer: RecordingSyncer
    locks: InMemoryBranchLocks


@pytest.fixture
def harness(git: FakeGit, branch_repository: InMemoryBranches) -> BranchHarness:
    git.remote.update({"main": BASE, "feature/one": HEAD})
    git.merge_bases[frozenset({BASE, HEAD})] = FORK
    events = RecordingEventSink()
    syncer = RecordingSyncer()
    locks = InMemoryBranchLocks()
    service = BranchService(
        repo_id="repo",
        config=StaticConfig(),
        git=git,
        branches=branch_repository,
        syncer=syncer,
        events=events,
        locks=locks,
        ids=SequentialIds(prefix="branch"),
    )
    return BranchHarness(service, git, branch_repository, events, syncer, locks)


@dataclass(slots=True)
class FakeSleeper:
    """``Sleeper`` that moves ``clock`` forward instead of waiting, then yields once."""

    clock: FixedClock
    slept: list[timedelta] = field(default_factory=list)

    async def sleep(self, delay: timedelta) -> None:
        self.slept.append(delay)
        self.clock.advance(delay)
        await asyncio.sleep(0)


@dataclass(slots=True)
class ScriptedExecutor:
    """``RunExecutor`` that records runs; each waits for ``release`` while ``hold`` is on.

    ``effect`` runs inside each run, before it returns: a test's stand-in for what the
    real run does to the remote and the store.
    """

    hold: bool = False
    fail_with: Exception | None = None
    effect: Callable[[str], None] | None = None
    started: list[tuple[str, RunTrigger]] = field(default_factory=list)
    finished: list[str] = field(default_factory=list)
    running: int = 0
    most_at_once: int = 0
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def run(self, branch_id: str, *, trigger: RunTrigger, config: RepoConfig) -> Run:
        self.started.append((branch_id, trigger))
        self.running += 1
        self.most_at_once = max(self.most_at_once, self.running)
        try:
            if self.hold:
                await self.release.wait()
            if self.fail_with is not None:
                raise self.fail_with
            if self.effect is not None:
                self.effect(branch_id)
        finally:
            self.running -= 1
        self.finished.append(branch_id)
        return make_run(
            id=f"run-{len(self.finished)}", branch_id=branch_id, outcome=BranchState.IDLE
        )


async def wait_until(condition: Callable[[], bool], *, steps: int = 10_000) -> None:
    """Yield to the event loop until ``condition`` holds; fail after ``steps`` turns."""
    for _ in range(steps):
        if condition():
            return
        await asyncio.sleep(0)
    msg = "condition never held"
    raise AssertionError(msg)
