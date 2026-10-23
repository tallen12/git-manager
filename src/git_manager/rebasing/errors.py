"""Rebasing errors."""

from collections.abc import Sequence


class GitError(Exception):
    """A git command failed in a way the caller did not expect."""

    def __init__(self, *, argv: Sequence[str], exit_code: int | None, stderr: str) -> None:
        status = "timed out" if exit_code is None else f"exited {exit_code}"
        super().__init__(f"{' '.join(argv)} {status}: {stderr.strip()}")
        self.argv = tuple(argv)
        self.exit_code = exit_code
        self.stderr = stderr
