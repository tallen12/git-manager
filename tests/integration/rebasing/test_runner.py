from pathlib import Path

import pytest

from git_manager.branches import BranchState, Reason
from git_manager.config.models import BranchOptions, RepoConfig, RepoSection, VerifyConfig
from git_manager.rebasing import RunTrigger
from git_manager.rebasing.git import SubprocessGit
from git_manager.rebasing.locks import InMemoryBranchLocks
from git_manager.rebasing.runner import RebaseRunner
from tests.conftest import (
    FakeVerifier,
    FixedClock,
    InMemoryBranches,
    InMemoryRuns,
    RecordingApprovalGate,
    RecordingEventSink,
    SequentialIds,
    make_branch,
)
from tests.integration.rebasing.conftest import Remote, commit, git


def repo_config(data_dir: Path) -> RepoConfig:
    return RepoConfig(
        repo=RepoSection(url="https://example.com/repo.git", data_dir=data_dir),
        defaults=BranchOptions(verify=VerifyConfig(test="just test")),
    )


@pytest.fixture
def branches(remote: Remote) -> InMemoryBranches:
    store = InMemoryBranches()
    store.rows["branch-1"] = make_branch(
        fork_point=remote.fork_point,
        last_base_sha=remote.fork_point,
        last_head_sha=remote.feature_head,
    )
    return store


@pytest.fixture
def runner(subprocess_git: SubprocessGit, branches: InMemoryBranches) -> RebaseRunner:
    clock = FixedClock()
    return RebaseRunner(
        git=subprocess_git,
        branches=branches,
        runs=InMemoryRuns(),
        events=RecordingEventSink(clock=clock),
        verifier=FakeVerifier(),
        approvals=RecordingApprovalGate(),
        locks=InMemoryBranchLocks(),
        clock=clock,
        ids=SequentialIds(prefix="run"),
    )


def worktrees(clone: Path) -> list[str]:
    listing = git(clone, "worktree", "list", "--porcelain")
    return [line for line in listing.splitlines() if line.startswith("worktree ")]


async def test_clean_rebase_is_pushed_to_the_remote(
    runner: RebaseRunner, branches: InMemoryBranches, remote: Remote, tmp_path: Path
) -> None:
    new_base = commit(remote.teammate, "other.txt", "base work\n", "main moves")
    git(remote.teammate, "push", "--quiet", "origin", "main")
    data_dir = tmp_path / "data"

    run = await runner.run("branch-1", trigger=RunTrigger.MANUAL, config=repo_config(data_dir))

    assert run.outcome is BranchState.IDLE
    pushed = git(remote.bare, "rev-parse", "refs/heads/feature/one")
    assert run.heads[0].new_head == pushed
    assert git(remote.bare, "rev-parse", "refs/heads/feature/one~1") == new_base
    assert git(remote.bare, "show", "-s", "--format=%s", pushed) == "feature"
    branch = branches.rows["branch-1"]
    assert (branch.fork_point, branch.last_base_sha, branch.last_head_sha) == (
        new_base,
        new_base,
        pushed,
    )
    assert not (data_dir / "worktrees" / run.id).exists()
    assert len(worktrees(remote.clone)) == 1


async def test_conflict_keeps_the_partial_attempt_as_a_local_branch(
    runner: RebaseRunner, remote: Remote, tmp_path: Path
) -> None:
    git(remote.teammate, "switch", "--quiet", "feature/one")
    commit(remote.teammate, "shared.txt", "feature side\n", "edit shared")
    git(remote.teammate, "push", "--quiet", "origin", "feature/one")
    git(remote.teammate, "switch", "--quiet", "main")
    new_base = commit(remote.teammate, "shared.txt", "base side\n", "main edits shared")
    git(remote.teammate, "push", "--quiet", "origin", "main")
    before = git(remote.bare, "rev-parse", "refs/heads/feature/one")

    run = await runner.run(
        "branch-1", trigger=RunTrigger.MANUAL, config=repo_config(tmp_path / "data")
    )

    assert (run.outcome, run.reason) == (BranchState.NEEDS_HUMAN, Reason.CONFLICT)
    assert git(remote.bare, "rev-parse", "refs/heads/feature/one") == before
    attempt = f"refs/heads/gm/attempt/feature/one/{run.id}"
    # The attempt holds the commits replayed before the conflict, on the new base.
    assert git(remote.clone, "rev-parse", f"{attempt}~1") == new_base
    assert git(remote.clone, "show", "-s", "--format=%s", attempt) == "feature"
    assert len(worktrees(remote.clone)) == 1
