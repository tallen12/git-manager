from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.rebasing import (
    Git,
    GitError,
    GitOutputError,
    LeaseRejected,
    Pushed,
    RebaseCompleted,
    RebaseStopped,
)
from git_manager.rebasing.git import (
    SubprocessGit,
    parse_ls_remote,
    parse_null_separated,
    parse_push,
    parse_sha,
)
from git_manager.runtime import Command, ProcessCompleted, ProcessResult, ProcessTimedOut
from tests.conftest import FakeProcessRunner, sha

CLONE = Path("data") / "repo"
WORKTREE = Path("data") / "worktrees" / "run-1"
ARGV = ("git", "test")
REF = "refs/heads/feature/one"


def done(stdout: str = "", *, exit_code: int = 0, stderr: str = "") -> ProcessCompleted:
    return ProcessCompleted(
        exit_code=exit_code, stdout=stdout, stderr=stderr, duration=timedelta(0)
    )


def subcommand(command: Command) -> tuple[str, ...]:
    """The argv after ``git`` and its ``-c`` options."""
    argv = list(command.argv[1:])
    while argv and argv[0] == "-c":
        argv = argv[2:]
    return tuple(argv)


def scripted(answers: Mapping[str, ProcessResult]) -> Callable[[Command], ProcessResult]:
    """Answer each command by its first matching subcommand prefix, joined by spaces."""

    def respond(command: Command) -> ProcessResult:
        line = " ".join(subcommand(command))
        for prefix, result in answers.items():
            if line.startswith(prefix):
                return result
        return done()

    return respond


def make_git(
    runner: FakeProcessRunner,
    *,
    remote: str = "origin",
    env: Mapping[str, str] | None = None,
    timeout: timedelta | None = None,
) -> SubprocessGit:
    return SubprocessGit(runner=runner, clone=CLONE, remote=remote, env=env or {}, timeout=timeout)


# --- Parsing ---


def test_parse_sha_accepts_one_hash_and_rejects_anything_else() -> None:
    assert parse_sha(ARGV, f"{sha(1)}\n") == sha(1)
    with pytest.raises(GitOutputError, match="expected one commit hash"):
        parse_sha(ARGV, "not a hash\n")


def test_parse_ls_remote_keeps_only_exact_branch_names() -> None:
    output = f"{sha(1)}\trefs/heads/main\n{sha(2)}\trefs/heads/x/refs/heads/main\n"

    assert parse_ls_remote(ARGV, output, ["main", "gone"]) == {"main": sha(1)}


def test_parse_ls_remote_rejects_malformed_lines() -> None:
    with pytest.raises(GitOutputError):
        parse_ls_remote(ARGV, "garbage\n", ["main"])


def test_parse_null_separated_sorts_and_deduplicates() -> None:
    assert parse_null_separated("b.py\0a.py\0b.py\0") == ("a.py", "b.py")


@pytest.mark.parametrize("flag", [" ", "+", "*", "="])
def test_parse_push_reports_an_update(flag: str) -> None:
    output = f"To remote\n{flag}\t{sha(4)}:{REF}\t{sha(2)}...{sha(4)} (forced update)\nDone\n"

    assert parse_push(ARGV, output, REF)


def test_parse_push_reports_a_stale_lease() -> None:
    output = f"To remote\n!\t{sha(4)}:{REF}\t[rejected] (stale info)\nDone\n"

    assert not parse_push(ARGV, output, REF)


def test_parse_push_raises_for_other_rejections_and_missing_status() -> None:
    hook = f"!\t{sha(4)}:{REF}\t[remote rejected] (pre-receive hook declined)\n"
    with pytest.raises(GitError, match="pre-receive hook declined"):
        parse_push(ARGV, hook, REF)
    with pytest.raises(GitOutputError, match="no status line"):
        parse_push(ARGV, f"!\t{sha(4)}:refs/heads/other\t[rejected] (stale info)\n", REF)


# --- Commands ---


async def test_commands_get_only_the_given_env_plus_fixed_settings() -> None:
    runner = FakeProcessRunner(respond=lambda _: done(f"{sha(1)}\trefs/heads/main\n"))
    timeout = timedelta(seconds=30)
    git: Git = make_git(runner, env={"GIT_SSH_COMMAND": "ssh -i key"}, timeout=timeout)

    assert await git.ls_remote(["main"]) == {"main": sha(1)}

    [command] = runner.commands
    assert command.cwd == CLONE
    assert command.timeout == timeout
    assert command.env["GIT_SSH_COMMAND"] == "ssh -i key"
    assert command.env["GIT_TERMINAL_PROMPT"] == "0"
    assert command.env["LC_ALL"] == "C"
    assert "rerere.enabled=true" in command.argv
    assert subcommand(command) == ("ls-remote", "--heads", "--", "origin", "refs/heads/main")


async def test_empty_ref_lists_run_nothing() -> None:
    runner = FakeProcessRunner()
    git = make_git(runner)

    assert await git.ls_remote([]) == {}
    await git.fetch([])

    assert runner.commands == []


async def test_fetch_uses_forced_refspecs_into_remote_tracking_branches() -> None:
    runner = FakeProcessRunner()

    await make_git(runner, remote="upstream").fetch(["main"])

    assert subcommand(runner.commands[0]) == (
        "fetch",
        "--no-tags",
        "--",
        "upstream",
        "+refs/heads/main:refs/remotes/upstream/main",
    )


async def test_failures_and_timeouts_raise_git_error() -> None:
    failing = FakeProcessRunner(respond=lambda _: done(exit_code=128, stderr="fatal: no remote"))
    timing_out = FakeProcessRunner(
        respond=lambda _: ProcessTimedOut(stdout="", stderr="slow", duration=timedelta(0))
    )

    with pytest.raises(GitError, match="exited 128: fatal: no remote") as failed:
        await make_git(failing).ls_remote(["main"])
    with pytest.raises(GitError, match="timed out") as timed_out:
        await make_git(timing_out).fetch(["main"])

    assert failed.value.exit_code == 128
    assert timed_out.value.exit_code is None


async def test_merge_base_validates_its_output() -> None:
    git = make_git(FakeProcessRunner(respond=lambda _: done(f"{sha(1)}\n")))
    broken = make_git(FakeProcessRunner(respond=lambda _: done("\n")))

    assert await git.merge_base("main", "feature/one") == sha(1)
    with pytest.raises(GitOutputError):
        await broken.merge_base("main", "feature/one")


@pytest.mark.parametrize(("exit_code", "expected"), [(0, True), (1, False)])
async def test_is_ancestor_maps_exit_codes(exit_code: int, expected: bool) -> None:
    git = make_git(FakeProcessRunner(respond=lambda _: done(exit_code=exit_code)))

    assert await git.is_ancestor(sha(1), sha(2)) is expected


async def test_is_ancestor_raises_for_unknown_commits() -> None:
    git = make_git(FakeProcessRunner(respond=lambda _: done(exit_code=128, stderr="bad")))

    with pytest.raises(GitError):
        await git.is_ancestor(sha(1), "nope")


async def test_remove_worktree_prunes_when_the_folder_is_gone(tmp_path: Path) -> None:
    runner = FakeProcessRunner(respond=scripted({"worktree remove": done(exit_code=128)}))

    await make_git(runner).remove_worktree(tmp_path / "gone")

    assert [subcommand(command)[:2] for command in runner.commands] == [
        ("worktree", "remove"),
        ("worktree", "prune"),
    ]


async def test_remove_worktree_raises_when_the_folder_remains(tmp_path: Path) -> None:
    runner = FakeProcessRunner(respond=scripted({"worktree remove": done(exit_code=128)}))

    with pytest.raises(GitError):
        await make_git(runner).remove_worktree(tmp_path)


async def test_clean_rebase_returns_the_new_head() -> None:
    runner = FakeProcessRunner(respond=scripted({"rev-parse": done(f"{sha(5)}\n")}))

    outcome = await make_git(runner).rebase_onto(
        WORKTREE, new_base=sha(3), fork_point=sha(1), rebase_merges=True
    )

    assert outcome == RebaseCompleted(head=sha(5))
    rebase = runner.commands[0]
    assert rebase.cwd == WORKTREE
    assert subcommand(rebase) == ("rebase", "--rebase-merges", "--onto", sha(3), sha(1))


async def test_conflicted_rebase_returns_the_stopped_commit_and_paths() -> None:
    runner = FakeProcessRunner(
        respond=scripted(
            {
                "rebase": done(exit_code=1),
                "rev-parse": done(f"{sha(6)}\n"),
                "diff --name-only": done("b.py\0a.py\0"),
            }
        )
    )

    outcome = await make_git(runner).rebase_onto(
        WORKTREE, new_base=sha(3), fork_point=sha(1), rebase_merges=False
    )

    assert outcome == RebaseStopped(commit=sha(6), conflicted_paths=("a.py", "b.py"))


@pytest.mark.parametrize(
    "answers",
    [
        {"rev-parse": done(exit_code=1)},
        {"rev-parse": done(f"{sha(6)}\n"), "diff --name-only": done("")},
    ],
    ids=["never started", "stopped without conflicts"],
)
async def test_rebase_failures_other_than_conflicts_raise(
    answers: dict[str, ProcessResult],
) -> None:
    runner = FakeProcessRunner(
        respond=scripted({"rebase": done(exit_code=1, stderr="error"), **answers})
    )

    with pytest.raises(GitError, match="error"):
        await make_git(runner).rebase_onto(
            WORKTREE, new_base=sha(3), fork_point=sha(1), rebase_merges=False
        )


async def test_push_sends_the_resolved_commit_with_a_lease() -> None:
    status = done(f"To remote\n+\t{sha(4)}:{REF}\t{sha(2)}...{sha(4)} (forced update)\n")
    runner = FakeProcessRunner(respond=scripted({"rev-parse": done(f"{sha(4)}\n"), "push": status}))

    outcome = await make_git(runner).push_with_lease(
        WORKTREE, branch="feature/one", head="HEAD", expected=sha(2)
    )

    assert outcome == Pushed(head=sha(4))
    push = runner.commands[-1]
    assert f"--force-with-lease={REF}:{sha(2)}" in push.argv
    assert push.argv[-2:] == ("origin", f"{sha(4)}:{REF}")


async def test_push_maps_a_stale_lease_to_lease_rejected() -> None:
    status = done(f"!\t{sha(4)}:{REF}\t[rejected] (stale info)\n", exit_code=1)
    runner = FakeProcessRunner(respond=scripted({"rev-parse": done(f"{sha(4)}\n"), "push": status}))

    outcome = await make_git(runner).push_with_lease(
        WORKTREE, branch="feature/one", head="HEAD", expected=sha(2)
    )

    assert outcome == LeaseRejected(expected=sha(2))


async def test_push_that_never_reached_the_remote_raises() -> None:
    failure = done(exit_code=128, stderr="fatal: could not read from remote")
    runner = FakeProcessRunner(
        respond=scripted({"rev-parse": done(f"{sha(4)}\n"), "push": failure})
    )

    with pytest.raises(GitError, match="could not read from remote"):
        await make_git(runner).push_with_lease(
            WORKTREE, branch="feature/one", head="HEAD", expected=sha(2)
        )


async def test_branch_abort_and_diff_commands() -> None:
    runner = FakeProcessRunner(respond=scripted({"diff": done("patch\n")}))
    git = make_git(runner)

    await git.create_branch("gm/attempt/feature/one/run-1", sha(4))
    await git.abort_rebase(WORKTREE)
    patch = await git.diff(sha(1), sha(4))

    assert patch == "patch\n"
    assert [(subcommand(command), command.cwd) for command in runner.commands] == [
        (("branch", "--force", "--", "gm/attempt/feature/one/run-1", sha(4)), CLONE),
        (("rebase", "--abort"), WORKTREE),
        (("diff", "--no-ext-diff", "--no-textconv", sha(1), sha(4), "--"), CLONE),
    ]
