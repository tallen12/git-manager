from pathlib import Path

import pytest

from git_manager.core.unavailable import UnavailableRuns
from git_manager.rebasing import (
    Git,
    LeaseRejected,
    Pushed,
    RebaseCompleted,
    RebaseStopped,
    RunOperations,
)
from tests.conftest import FakeGit, sha

WORKTREE = Path("worktrees") / "run-1"


async def test_fake_git_reports_only_branches_on_the_remote() -> None:
    git: Git = FakeGit(remote={"main": sha(1), "feature/one": sha(2)})

    assert await git.ls_remote(["main", "gone"]) == {"main": sha(1)}


async def test_fake_git_push_checks_the_lease_against_the_remote() -> None:
    fake = FakeGit(remote={"feature/one": sha(2)})
    git: Git = fake

    rejected = await git.push_with_lease(
        WORKTREE, branch="feature/one", head=sha(4), expected=sha(9)
    )
    pushed = await git.push_with_lease(WORKTREE, branch="feature/one", head=sha(4), expected=sha(2))

    assert rejected == LeaseRejected(expected=sha(9))
    assert pushed == Pushed(head=sha(4))
    assert fake.remote["feature/one"] == sha(4)


async def test_fake_git_replays_scripted_rebase_outcomes_in_a_worktree() -> None:
    fake = FakeGit(
        rebase_outcomes=[
            RebaseStopped(commit=sha(5), conflicted_paths=("app.py",)),
            RebaseCompleted(head=sha(6)),
        ]
    )
    git: Git = fake
    await git.add_worktree(WORKTREE, sha(2))

    first = await git.rebase_onto(WORKTREE, new_base=sha(3), fork_point=sha(1), rebase_merges=False)
    await git.abort_rebase(WORKTREE)
    second = await git.rebase_onto(
        WORKTREE, new_base=sha(3), fork_point=sha(1), rebase_merges=False
    )

    assert isinstance(first, RebaseStopped)
    assert second == RebaseCompleted(head=sha(6))
    assert fake.aborted == [WORKTREE]
    assert fake.worktrees[WORKTREE] == sha(6)


async def test_fake_git_rebase_without_a_script_fails_loudly(git: FakeGit) -> None:
    await git.add_worktree(WORKTREE, sha(2))

    with pytest.raises(AssertionError, match="no rebase outcome scripted"):
        await git.rebase_onto(WORKTREE, new_base=sha(3), fork_point=sha(1), rebase_merges=False)


async def test_fake_git_answers_ancestry_and_merge_base_from_its_tables() -> None:
    git: Git = FakeGit(
        merge_bases={frozenset({"main", "feature/one"}): sha(1)}, ancestry={(sha(1), sha(3))}
    )

    assert await git.merge_base("feature/one", "main") == sha(1)
    assert await git.is_ancestor(sha(1), sha(3))
    assert not await git.is_ancestor(sha(3), sha(1))


def test_unavailable_runs_satisfy_the_protocol() -> None:
    # The annotation is the contract: the type checker rejects a non-conforming class.
    operations: RunOperations = UnavailableRuns("later")

    assert operations is not None
