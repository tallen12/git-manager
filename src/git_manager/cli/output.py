"""What every command prints: errors on one line, exit codes and plain-text tables.

Commands print the same output in local and API mode, since they only see ``Operations``.

Exit codes: ``0`` success, ``1`` the operation failed (``error: ...`` on stderr), ``2``
invalid flags or settings, and ``3`` a ``sync`` whose run ended without pushing (the
branch needs a look; its state says why).
"""

import sys
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import NoReturn

from git_manager.core import ApiError, ApiResponseError, ApiUnreachableError, OperationError
from git_manager.rebasing.errors import GitError

EXIT_FAILED = 1
EXIT_NOT_PUSHED = 3

# What a command reports as a one-line error rather than a traceback. ``GitError`` reaches
# a local-mode ``sync`` when git itself failed; the run is then stopped in needs_human.
COMMAND_ERRORS = (OperationError, ApiError, ApiResponseError, ApiUnreachableError, GitError)


def fail(error: Exception) -> NoReturn:
    """Print ``error`` on one line to stderr and exit ``1``."""
    message = " ".join(str(error).split())
    print(f"error: {message}", file=sys.stderr)
    sys.exit(EXIT_FAILED)


@contextmanager
def reported() -> Generator[None]:
    """Turn any of ``COMMAND_ERRORS`` raised in the block into ``fail``.

    Wrap the whole ``async with connect(...)`` block: opening local mode can fail too, for
    example with the API-mode hint when a daemon holds the data directory.
    """
    try:
        yield
    except COMMAND_ERRORS as error:
        fail(error)


def short(sha: str | None) -> str:
    """A commit hash abbreviated for tables, or ``-`` when there is none."""
    return "-" if sha is None else sha[:12]


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Left-aligned columns separated by two spaces, without trailing blanks."""
    lines = [header, *rows]
    widths = [max(len(line[column]) for line in lines) for column in range(len(header))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in lines
    )
