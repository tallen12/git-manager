"""Throwaway git remotes and clones for the rebasing integration tests."""

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.rebasing.git import SubprocessGit
from git_manager.runtime import Command, ProcessCompleted, ProcessResult, ProcessTimedOut

IDENTITY = {
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


class LocalProcessRunner:
    """``ProcessRunner`` that runs commands as the current user, for tests only.

    The isolated runner (``isolation/``) is the production one; this keeps the git tests
    free of it.
    """

    async def run(self, command: Command) -> ProcessResult:
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *command.argv,
            cwd=command.cwd,
            env=dict(command.env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timeout = None if command.timeout is None else command.timeout.total_seconds()
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            duration = timedelta(seconds=time.monotonic() - started)
            return ProcessTimedOut(stdout="", stderr="", duration=duration)
        assert process.returncode is not None
        return ProcessCompleted(
            exit_code=process.returncode,
            stdout=stdout.decode("utf-8"),
            stderr=stderr.decode("utf-8"),
            duration=timedelta(seconds=time.monotonic() - started),
        )


def git(cwd: Path, *args: str) -> str:
    """Run git for test setup and return its stdout."""
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=_env()
    )
    return result.stdout.strip()


def commit(clone: Path, name: str, content: str, message: str) -> str:
    """Write ``name`` in ``clone``, commit it and return the new hash."""
    (clone / name).write_text(content, encoding="utf-8")
    git(clone, "add", "--", name)
    git(clone, "commit", "--quiet", "-m", message)
    return git(clone, "rev-parse", "HEAD")


def _env() -> dict[str, str]:
    # Mirrors the explicit environment the adapter gets: nothing from the developer.
    return {
        "PATH": os.environ["PATH"],
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        **IDENTITY,
    }


@dataclass(frozen=True, slots=True)
class Remote:
    """A bare remote with ``main`` and ``feature/one``, a teammate's clone and ours.

    ``feature/one`` adds ``feature.txt`` on top of the first ``main`` commit, which is
    ``fork_point``.
    """

    bare: Path
    teammate: Path
    clone: Path
    fork_point: str
    feature_head: str


@pytest.fixture
def remote(tmp_path: Path) -> Remote:
    bare = tmp_path / "remote.git"
    teammate = tmp_path / "teammate"
    clone = tmp_path / "clone"
    git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(bare))
    git(tmp_path, "clone", "--quiet", str(bare), str(teammate))
    fork_point = commit(teammate, "shared.txt", "one\n", "base")
    git(teammate, "push", "--quiet", "origin", "HEAD:refs/heads/main")
    git(teammate, "switch", "--quiet", "-c", "feature/one")
    feature_head = commit(teammate, "feature.txt", "feature\n", "feature")
    git(teammate, "push", "--quiet", "origin", "HEAD:refs/heads/feature/one")
    git(teammate, "switch", "--quiet", "main")
    git(tmp_path, "clone", "--quiet", str(bare), str(clone))
    return Remote(bare, teammate, clone, fork_point, feature_head)


@pytest.fixture
def subprocess_git(remote: Remote) -> SubprocessGit:
    return SubprocessGit(runner=LocalProcessRunner(), clone=remote.clone, env=_env())
