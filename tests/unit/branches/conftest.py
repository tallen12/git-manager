"""A branch service wired to the shared fakes."""

from dataclasses import dataclass, field

import pytest

from git_manager.branches import TrackedBranch
from git_manager.branches.results import SyncCompleted, SyncOutcome
from git_manager.branches.service import BranchService
from git_manager.config.models import RepoConfig, RepoSection
from git_manager.rebasing.locks import InMemoryBranchLocks
from tests.conftest import (
    FakeGit,
    InMemoryBranches,
    RecordingEventSink,
    SequentialIds,
    make_run,
    sha,
)

# On the remote, ``main`` is at BASE and ``feature/one`` at HEAD; they fork at FORK.
FORK, HEAD, BASE = sha(1), sha(2), sha(3)
URL = "https://example.com/repo.git"


@dataclass(frozen=True, slots=True)
class StaticConfig:
    """``ConfigOperations`` serving one fixed config."""

    config: RepoConfig = field(default_factory=lambda: RepoConfig(repo=RepoSection(url=URL)))

    async def show(self) -> RepoConfig:
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
