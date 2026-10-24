"""A rebase runner wired to the shared fakes."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from git_manager.config.models import BranchOptions, RepoConfig, RepoSection, VerifyConfig
from git_manager.rebasing.locks import InMemoryBranchLocks
from git_manager.rebasing.runner import RebaseRunner
from git_manager.verification.protocols import Verifier
from tests.conftest import (
    FakeGit,
    FakeVerifier,
    FixedClock,
    InMemoryBranches,
    InMemoryRuns,
    RecordingApprovalGate,
    RecordingEventSink,
    SequentialIds,
    make_branch,
    sha,
)

# The tracked branch sits on OLD_BASE at HEAD; the remote base has moved to NEW_BASE.
OLD_BASE, HEAD, NEW_BASE, REBASED = sha(1), sha(2), sha(3), sha(4)
BRANCH = "feature/one"


def repo_config(data_dir: Path, **options: object) -> RepoConfig:
    """Config whose defaults verify with ``just test``; pass options to override."""
    values: dict[str, object] = {"verify": VerifyConfig(test="just test")} | options
    return RepoConfig(
        repo=RepoSection(url="https://example.com/repo.git", data_dir=data_dir),
        defaults=BranchOptions.model_validate(values),
    )


@dataclass(frozen=True, slots=True)
class Harness:
    """The runner and every fake it talks to."""

    runner: RebaseRunner
    git: FakeGit
    branches: InMemoryBranches
    runs: InMemoryRuns
    events: RecordingEventSink
    verifier: Verifier
    approvals: RecordingApprovalGate
    locks: InMemoryBranchLocks
    data_dir: Path


def make_harness(
    data_dir: Path, *, git: FakeGit | None = None, verifier: Verifier | None = None
) -> Harness:
    """A runner whose branch sits on ``OLD_BASE`` at ``HEAD`` while the base is at
    ``NEW_BASE``; pass a ``git`` or ``verifier`` to replace the default fakes.
    """
    git = git if git is not None else FakeGit()
    git.remote.update({"main": NEW_BASE, BRANCH: HEAD})
    git.ancestry.add((OLD_BASE, NEW_BASE))
    verifier = verifier if verifier is not None else FakeVerifier()
    branches = InMemoryBranches()
    branches.rows["branch-1"] = make_branch(
        fork_point=OLD_BASE, last_base_sha=OLD_BASE, last_head_sha=HEAD
    )
    runs = InMemoryRuns()
    clock = FixedClock()
    events = RecordingEventSink(clock=clock)
    approvals = RecordingApprovalGate()
    locks = InMemoryBranchLocks()
    runner = RebaseRunner(
        git=git,
        branches=branches,
        runs=runs,
        events=events,
        verifier=verifier,
        approvals=approvals,
        locks=locks,
        clock=clock,
        ids=SequentialIds(prefix="run"),
    )
    return Harness(
        runner=runner,
        git=git,
        branches=branches,
        runs=runs,
        events=events,
        verifier=verifier,
        approvals=approvals,
        locks=locks,
        data_dir=data_dir,
    )


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return make_harness(tmp_path / "data")
