"""Finding the JUnit XML report a test command wrote, if any.

There is no standard place for it, so the worktree is searched for an XML file with a
conventional name, written during the step, that looks like a JUnit report.
"""

from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

REPORT_PATTERNS = ("*junit*.xml", "test-*.xml", "*test-results*.xml", "*test-report*.xml")
"""Lower-cased file names that may hold a report (``TEST-*.xml`` is Maven Surefire's)."""

SKIPPED_DIRECTORIES = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".tox"})

MAX_REPORT_BYTES = 10 * 1024**2
"""Larger reports are left out; truncating would leave invalid XML."""

_SNIFF_BYTES = 4096


def find_junit_xml(worktree: Path, *, since: datetime) -> str | None:
    """Return the newest JUnit report under ``worktree`` modified at or after ``since``.

    Blocking: call it in a thread.
    """
    newest: tuple[float, Path] | None = None
    cutoff = since.timestamp()
    for directory, subdirectories, files in worktree.walk():
        subdirectories[:] = [name for name in subdirectories if name not in SKIPPED_DIRECTORIES]
        for name in files:
            if not any(fnmatch(name.lower(), pattern) for pattern in REPORT_PATTERNS):
                continue
            path = directory / name
            stat = path.stat()
            if stat.st_mtime < cutoff or stat.st_size > MAX_REPORT_BYTES:
                continue
            if _looks_like_junit(path) and (newest is None or stat.st_mtime > newest[0]):
                newest = (stat.st_mtime, path)
    return None if newest is None else newest[1].read_text(encoding="utf-8", errors="replace")


def _looks_like_junit(path: Path) -> bool:
    with path.open("rb") as report:
        head = report.read(_SNIFF_BYTES)
    return b"<testsuite" in head
