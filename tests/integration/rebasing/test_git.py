from pathlib import Path

import pytest

from git_manager.rebasing import (
    Git,
    GitError,
    LeaseRejected,
    Pushed,
    RebaseCompleted,
    RebaseStopped,
)
from git_manager.rebasing.git import SubprocessGit
from tests.integration.rebasing.conftest import Remote, commit, git


def advance_main(remote: Remote, content: str) -> str:
    """Have the teammate push a new ``main`` commit changing ``shared.txt``."""
    head = commit(remote.teammate, "shared.txt", content, "main moves")
    git(remote.teammate, "push", "--quiet", "origin", "main")
    return head


async def checkout(git_: Git, remote: Remote, tmp_path: Path) -> tuple[Path, str]:
    """Fetch both branches and add a run worktree at the feature tip."""
    await git_.fetch(["main", "feature/one"])
    worktree = tmp_path / "worktrees" / "run-1"
    await git_.add_worktree(worktree, "origin/feature/one")
    return worktree, git(remote.clone, "rev-parse", "origin/main")


async def test_ls_remote_reports_branches_and_omits_missing_ones(
    subprocess_git: SubprocessGit, remote: Remote
) -> None:
    git_: Git = subprocess_git

    heads = await git_.ls_remote(["main", "feature/one", "gone"])

    assert heads == {"main": remote.fork_point, "feature/one": remote.feature_head}


async def test_fetch_of_a_missing_remote_branch_raises(subprocess_git: SubprocessGit) -> None:
    with pytest.raises(GitError, match="gone"):
        await subprocess_git.fetch(["gone"])


async def test_merge_base_and_ancestry(subprocess_git: SubprocessGit, remote: Remote) -> None:
    new_main = advance_main(remote, "two\n")
    await subprocess_git.fetch(["main", "feature/one"])

    base = await subprocess_git.merge_base("origin/main", "origin/feature/one")

    assert base == remote.fork_point
    assert await subprocess_git.is_ancestor(remote.fork_point, new_main)
    assert not await subprocess_git.is_ancestor(new_main, remote.feature_head)


async def test_clean_rebase_moves_the_branch_onto_the_new_base(
    subprocess_git: SubprocessGit, remote: Remote, tmp_path: Path
) -> None:
    advance_main(remote, "two\n")
    worktree, new_base = await checkout(subprocess_git, remote, tmp_path)

    outcome = await subprocess_git.rebase_onto(
        worktree, new_base=new_base, fork_point=remote.fork_point, rebase_merges=False
    )

    assert isinstance(outcome, RebaseCompleted)
    assert git(worktree, "rev-parse", "HEAD~1") == new_base
    assert outcome.head == git(worktree, "rev-parse", "HEAD")
    assert "feature.txt" in await subprocess_git.diff(new_base, outcome.head)


async def test_conflict_stops_with_the_commit_and_paths_and_abort_restores(
    subprocess_git: SubprocessGit, remote: Remote, tmp_path: Path
) -> None:
    git(remote.teammate, "switch", "--quiet", "feature/one")
    conflicting = commit(remote.teammate, "shared.txt", "feature side\n", "edit shared")
    git(remote.teammate, "push", "--quiet", "origin", "feature/one")
    git(remote.teammate, "switch", "--quiet", "main")
    advance_main(remote, "main side\n")
    worktree, new_base = await checkout(subprocess_git, remote, tmp_path)

    outcome = await subprocess_git.rebase_onto(
        worktree, new_base=new_base, fork_point=remote.fork_point, rebase_merges=True
    )
    await subprocess_git.abort_rebase(worktree)

    assert outcome == RebaseStopped(commit=conflicting, conflicted_paths=("shared.txt",))
    assert git(worktree, "rev-parse", "HEAD") == conflicting


async def test_rebase_with_an_unknown_fork_point_raises(
    subprocess_git: SubprocessGit, remote: Remote, tmp_path: Path
) -> None:
    worktree, new_base = await checkout(subprocess_git, remote, tmp_path)

    with pytest.raises(GitError):
        await subprocess_git.rebase_onto(
            worktree, new_base=new_base, fork_point="no-such-ref", rebase_merges=False
        )


async def test_remove_worktree_discards_a_rebase_in_progress_and_tolerates_a_missing_one(
    subprocess_git: SubprocessGit, remote: Remote, tmp_path: Path
) -> None:
    worktree, _ = await checkout(subprocess_git, remote, tmp_path)
    (worktree / "feature.txt").write_text("dirty\n", encoding="utf-8")

    await subprocess_git.remove_worktree(worktree)
    await subprocess_git.remove_worktree(worktree)

    assert not worktree.exists()
    assert str(worktree) not in git(remote.clone, "worktree", "list")


async def test_push_with_a_matching_lease_updates_the_remote(
    subprocess_git: SubprocessGit, remote: Remote, tmp_path: Path
) -> None:
    advance_main(remote, "two\n")
    worktree, new_base = await checkout(subprocess_git, remote, tmp_path)
    rebased = await subprocess_git.rebase_onto(
        worktree, new_base=new_base, fork_point=remote.fork_point, rebase_merges=False
    )
    assert isinstance(rebased, RebaseCompleted)

    outcome = await subprocess_git.push_with_lease(
        worktree, branch="feature/one", head="HEAD", expected=remote.feature_head
    )

    assert outcome == Pushed(head=rebased.head)
    assert git(remote.bare, "rev-parse", "refs/heads/feature/one") == rebased.head


async def test_push_after_a_teammate_pushed_is_rejected_by_the_lease(
    subprocess_git: SubprocessGit, remote: Remote, tmp_path: Path
) -> None:
    advance_main(remote, "two\n")
    worktree, new_base = await checkout(subprocess_git, remote, tmp_path)
    await subprocess_git.rebase_onto(
        worktree, new_base=new_base, fork_point=remote.fork_point, rebase_merges=False
    )
    git(remote.teammate, "switch", "--quiet", "feature/one")
    theirs = commit(remote.teammate, "more.txt", "more\n", "teammate work")
    git(remote.teammate, "push", "--quiet", "origin", "feature/one")

    outcome = await subprocess_git.push_with_lease(
        worktree, branch="feature/one", head="HEAD", expected=remote.feature_head
    )

    assert outcome == LeaseRejected(expected=remote.feature_head)
    assert git(remote.bare, "rev-parse", "refs/heads/feature/one") == theirs


async def test_create_branch_keeps_an_attempt_locally(
    subprocess_git: SubprocessGit, remote: Remote
) -> None:
    await subprocess_git.create_branch("gm/attempt/feature/one/run-1", remote.feature_head)
    await subprocess_git.create_branch("gm/attempt/feature/one/run-1", remote.fork_point)

    assert git(remote.clone, "rev-parse", "gm/attempt/feature/one/run-1") == remote.fork_point
    assert "gm/attempt" not in git(remote.bare, "branch", "--list")
