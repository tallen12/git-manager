"""Rebasing errors."""

from collections.abc import Sequence

from git_manager.branches.models import BranchState
from git_manager.errors import ConflictError


class GitError(Exception):
    """A git command failed in a way the caller did not expect."""

    def __init__(self, *, argv: Sequence[str], exit_code: int | None, stderr: str) -> None:
        status = "timed out" if exit_code is None else f"exited {exit_code}"
        super().__init__(f"{' '.join(argv)} {status}: {stderr.strip()}")
        self.argv = tuple(argv)
        self.exit_code = exit_code
        self.stderr = stderr


class GitOutputError(GitError):
    """A git command succeeded but printed output the adapter cannot parse."""

    def __init__(self, *, argv: Sequence[str], output: str, problem: str) -> None:
        super().__init__(argv=argv, exit_code=0, stderr=f"{problem}: {output!r}")
        self.output = output


class RemoteBranchMissingError(Exception):
    """A run could not start because its base or feature branch is gone from the remote.

    The branch has already been moved to ``base_missing`` (base gone) or ``idle``
    (feature branch gone) when this is raised; no run was recorded.
    """

    def __init__(self, *, branch: str, missing: str) -> None:
        super().__init__(f"cannot sync {branch}: {missing} is not on the remote")
        self.branch = branch
        self.missing = missing


class BranchOnHoldError(ConflictError):
    """A run could not start because its branch is in a state that holds it.

    Nothing was changed and no run was recorded; see ``branches.polling.may_start``.
    """

    def __init__(self, *, branch: str, state: BranchState) -> None:
        super().__init__(f"cannot run {branch}: it is {state}")
        self.branch = branch
        self.state = state
