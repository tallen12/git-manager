"""The data-directory lock against another process."""

import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest

from git_manager.store import DataDirectoryLockedError, FileDataDirectoryLock, held

# Takes the lock, says so, then holds it until stdin closes (or it is killed).
HOLDER = """
import sys
from pathlib import Path
from git_manager.store import FileDataDirectoryLock
lock = FileDataDirectoryLock(Path(sys.argv[1]))
lock.acquire()
print("locked", flush=True)
sys.stdin.read()
"""


@pytest.fixture
def holder(tmp_path: Path) -> Generator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "locked"
    yield process
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def test_a_lock_held_by_another_process_is_refused(
    tmp_path: Path, holder: subprocess.Popen[str]
) -> None:
    with pytest.raises(DataDirectoryLockedError) as caught:
        FileDataDirectoryLock(tmp_path).acquire()

    assert "a daemon is using this data directory; use API mode" in str(caught.value)
    assert (tmp_path / "git-manager.lock").read_text(encoding="utf-8").strip() == str(holder.pid)


def test_the_lock_is_free_once_the_holder_exits(
    tmp_path: Path, holder: subprocess.Popen[str]
) -> None:
    assert holder.stdin is not None
    holder.stdin.close()
    assert holder.wait(timeout=10) == 0

    with held(FileDataDirectoryLock(tmp_path)):
        pass


def test_a_crashed_holder_leaves_no_stale_lock(
    tmp_path: Path, holder: subprocess.Popen[str]
) -> None:
    holder.kill()
    holder.wait(timeout=10)

    assert (tmp_path / "git-manager.lock").exists()
    with held(FileDataDirectoryLock(tmp_path)):
        pass
