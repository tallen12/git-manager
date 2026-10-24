"""``Git`` implemented by running the ``git`` binary through a ``ProcessRunner``."""

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType
from typing import assert_never

from git_manager.branches.models import SHA_PATTERN, CommitSha
from git_manager.rebasing.errors import GitError, GitOutputError
from git_manager.rebasing.models import (
    LeaseRejected,
    Pushed,
    PushOutcome,
    RebaseCompleted,
    RebaseOutcome,
    RebaseStopped,
)
from git_manager.runtime.models import Command, ProcessCompleted, ProcessTimedOut
from git_manager.runtime.protocols import ProcessRunner

_SHA = re.compile(SHA_PATTERN)
_HEADS = "refs/heads/"

# Set on every invocation, so a resolution recorded while a rebase stops is replayed by
# the next rebase whichever command records it. Output settings keep parsing stable.
_CONFIG = (
    "rerere.enabled=true",
    "core.quotePath=false",
    "color.ui=false",
    "advice.detachedHead=false",
)

# Always applied on top of the caller's environment: C messages, and no prompt or editor
# that could block a background process.
_FIXED_ENV = MappingProxyType(
    {"LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "GIT_PAGER": "cat"}
)


def parse_sha(argv: Sequence[str], output: str) -> CommitSha:
    """Return the single commit hash ``output`` holds."""
    value = output.strip()
    if not _SHA.fullmatch(value):
        raise GitOutputError(argv=argv, output=output, problem="expected one commit hash")
    return value


def parse_ls_remote(argv: Sequence[str], output: str, branches: Sequence[str]) -> dict[str, str]:
    """Map each of ``branches`` that ``git ls-remote`` listed to its hash."""
    wanted = {f"{_HEADS}{branch}": branch for branch in branches}
    found: dict[str, str] = {}
    for line in output.splitlines():
        sha, tab, ref = line.partition("\t")
        if not tab or not _SHA.fullmatch(sha) or not ref:
            raise GitOutputError(argv=argv, output=line, problem="expected '<hash>\\t<ref>'")
        # ls-remote matches patterns by suffix, so a request for refs/heads/main also lists
        # refs/heads/x/refs/heads/main; only exact names count.
        if ref in wanted:
            found[wanted[ref]] = sha
    return found


def parse_null_separated(output: str) -> tuple[str, ...]:
    """Split ``-z`` output into its non-empty entries, sorted and without duplicates."""
    return tuple(sorted({entry for entry in output.split("\0") if entry}))


def parse_push(argv: Sequence[str], output: str, ref: str) -> bool:
    """Whether ``git push --porcelain`` updated ``ref``; ``False`` for a stale lease.

    Raises ``GitOutputError`` when ``ref`` is missing and ``GitError`` for any other
    rejection (a hook, branch protection), which a human has to look at.
    """
    for line in output.splitlines():
        flag, tab, rest = line.partition("\t")
        refs, _, summary = rest.partition("\t")
        if not tab or refs.rpartition(":")[2] != ref:
            continue
        if flag in {" ", "+", "*", "="}:
            return True
        if flag == "!" and "(stale info)" in summary:
            return False
        raise GitError(argv=argv, exit_code=1, stderr=f"{ref} rejected: {summary}")
    raise GitOutputError(argv=argv, output=output, problem=f"no status line for {ref}")


@dataclass(frozen=True, slots=True)
class SubprocessGit:
    """``Git`` over the managed clone at ``clone`` and its remote ``remote``.

    ``env`` is the whole environment git sees apart from a few fixed settings: pass
    ``PATH``, ``HOME`` and the credential variables (``GIT_SSH_COMMAND`` and the like)
    here, and nothing else reaches git. ``timeout`` bounds every command.
    """

    runner: ProcessRunner
    clone: Path
    remote: str = "origin"
    program: str = "git"
    env: Mapping[str, str] = field(default_factory=dict)
    timeout: timedelta | None = None

    async def ensure_clone(self, url: str) -> None:
        """Clone ``url`` into ``clone`` as ``remote``, unless a repository is already there.

        Not part of ``Git``: only composition roots prepare the clone, before any run.
        """
        if await asyncio.to_thread((self.clone / ".git").exists):
            return
        await asyncio.to_thread(self.clone.parent.mkdir, parents=True, exist_ok=True)
        argv = self._argv("clone", "--quiet", "--origin", self.remote, "--", url, str(self.clone))
        await self._succeed(argv, cwd=self.clone.parent)

    async def ls_remote(self, refs: Sequence[str]) -> Mapping[str, CommitSha]:
        """Return the remote hash of each branch in ``refs``; missing branches are absent."""
        found: dict[str, CommitSha] = {}
        if not refs:
            return found
        argv = self._argv("ls-remote", "--heads", "--", self.remote)
        argv += tuple(f"{_HEADS}{ref}" for ref in refs)
        result = await self._succeed(argv, cwd=self.clone)
        return parse_ls_remote(argv, result.stdout, refs)

    async def fetch(self, refs: Sequence[str]) -> None:
        """Fetch ``refs`` from the remote into the clone's remote-tracking branches."""
        if not refs:
            return
        # Forced refspecs: the remote branches are rewritten by every rebase we push.
        specs = tuple(f"+{_HEADS}{ref}:refs/remotes/{self.remote}/{ref}" for ref in refs)
        argv = self._argv("fetch", "--no-tags", "--", self.remote, *specs)
        await self._succeed(argv, cwd=self.clone)

    async def merge_base(self, first: str, second: str) -> CommitSha:
        """Return the best common ancestor of two commits."""
        argv = self._argv("merge-base", "--", first, second)
        result = await self._succeed(argv, cwd=self.clone)
        return parse_sha(argv, result.stdout)

    async def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Whether ``ancestor`` is reachable from ``descendant``."""
        argv = self._argv("merge-base", "--is-ancestor", "--", ancestor, descendant)
        result = await self._run(argv, cwd=self.clone)
        if result.exit_code in {0, 1}:
            return result.exit_code == 0
        raise GitError(argv=argv, exit_code=result.exit_code, stderr=result.stderr)

    async def add_worktree(self, path: Path, commit: str) -> None:
        """Create a detached worktree at ``path`` checked out at ``commit``."""
        argv = self._argv("worktree", "add", "--detach", "--", str(path), commit)
        await self._succeed(argv, cwd=self.clone)

    async def remove_worktree(self, path: Path) -> None:
        """Remove the worktree at ``path``, discarding any changes in it.

        A worktree whose folder is already gone is only pruned, so cleanup after a crash
        can call this without checking first.
        """
        argv = self._argv("worktree", "remove", "--force", "--force", "--", str(path))
        result = await self._run(argv, cwd=self.clone)
        if result.succeeded:
            return
        if await asyncio.to_thread(path.exists):
            raise GitError(argv=argv, exit_code=result.exit_code, stderr=result.stderr)
        await self._succeed(self._argv("worktree", "prune"), cwd=self.clone)

    async def rebase_onto(
        self, worktree: Path, *, new_base: str, fork_point: str, rebase_merges: bool
    ) -> RebaseOutcome:
        """Run ``git rebase --onto new_base fork_point`` in ``worktree`` with rerere on.

        A stop on conflicts leaves the rebase in progress and returns ``RebaseStopped``.
        Any other failure raises ``GitError``; if the rebase had started, it is still in
        progress and the caller aborts it or removes the worktree.
        """
        merges = ("--rebase-merges",) if rebase_merges else ()
        argv = self._argv("rebase", *merges, "--onto", new_base, fork_point)
        result = await self._run(argv, cwd=worktree)
        if result.succeeded:
            return RebaseCompleted(head=await self._rev_parse("HEAD", cwd=worktree))
        stopped = await self._stopped_commit(worktree)
        paths = await self._conflicted_paths(worktree)
        if stopped is None or not paths:
            raise GitError(argv=argv, exit_code=result.exit_code, stderr=result.stderr)
        return RebaseStopped(commit=stopped, conflicted_paths=paths)

    async def abort_rebase(self, worktree: Path) -> None:
        """Abort the rebase in progress in ``worktree``."""
        await self._succeed(self._argv("rebase", "--abort"), cwd=worktree)

    async def push_with_lease(
        self, worktree: Path, *, branch: str, head: str, expected: str
    ) -> PushOutcome:
        """Push ``head`` to ``branch`` with ``--force-with-lease=branch:expected`` (G1)."""
        sha = await self._rev_parse(head, cwd=worktree)
        ref = f"{_HEADS}{branch}"
        argv = self._argv(
            "push",
            "--porcelain",
            "--no-verify",
            f"--force-with-lease={ref}:{expected}",
            "--",
            self.remote,
            f"{sha}:{ref}",
        )
        result = await self._run(argv, cwd=worktree)
        # Porcelain status lines go to stdout whether or not the push was rejected; a
        # failure before any ref was tried (network, auth) prints none.
        try:
            updated = parse_push(argv, result.stdout, ref)
        except GitOutputError as error:
            raise GitError(argv=argv, exit_code=result.exit_code, stderr=result.stderr) from error
        return Pushed(head=sha) if updated else LeaseRejected(expected=expected)

    async def create_branch(self, name: str, commit: str) -> None:
        """Create or move the local branch ``name`` (never pushed), e.g. ``gm/attempt/*``."""
        await self._succeed(self._argv("branch", "--force", "--", name, commit), cwd=self.clone)

    async def diff(self, start: str, end: str) -> str:
        """Return ``git diff start end``."""
        argv = self._argv("diff", "--no-ext-diff", "--no-textconv", start, end, "--")
        return (await self._succeed(argv, cwd=self.clone)).stdout

    async def _stopped_commit(self, worktree: Path) -> CommitSha | None:
        argv = self._argv("rev-parse", "--quiet", "--verify", "REBASE_HEAD^{commit}")
        result = await self._run(argv, cwd=worktree)
        return parse_sha(argv, result.stdout) if result.succeeded else None

    async def _conflicted_paths(self, worktree: Path) -> tuple[str, ...]:
        argv = self._argv("diff", "--name-only", "--diff-filter=U", "-z")
        return parse_null_separated((await self._succeed(argv, cwd=worktree)).stdout)

    async def _rev_parse(self, revision: str, *, cwd: Path) -> CommitSha:
        argv = self._argv("rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
        return parse_sha(argv, (await self._succeed(argv, cwd=cwd)).stdout)

    def _argv(self, *args: str) -> tuple[str, ...]:
        config = tuple(part for setting in _CONFIG for part in ("-c", setting))
        return (self.program, *config, *args)

    async def _succeed(self, argv: tuple[str, ...], *, cwd: Path) -> ProcessCompleted:
        result = await self._run(argv, cwd=cwd)
        if not result.succeeded:
            raise GitError(argv=argv, exit_code=result.exit_code, stderr=result.stderr)
        return result

    async def _run(self, argv: tuple[str, ...], *, cwd: Path) -> ProcessCompleted:
        command = Command(argv=argv, cwd=cwd, env={**self.env, **_FIXED_ENV}, timeout=self.timeout)
        match await self.runner.run(command):
            case ProcessCompleted() as completed:
                return completed
            case ProcessTimedOut(stderr=stderr):
                raise GitError(argv=argv, exit_code=None, stderr=stderr)
            case unreachable:
                assert_never(unreachable)
