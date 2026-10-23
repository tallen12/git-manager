from dataclasses import dataclass, field
from pathlib import Path

import pytest

from git_manager.store import (
    DataDirectoryLock,
    DataDirectoryLockedError,
    FileDataDirectoryLock,
    held,
)


def test_a_second_handle_is_refused_while_the_first_holds(tmp_path: Path) -> None:
    first: DataDirectoryLock = FileDataDirectoryLock(tmp_path)
    second = FileDataDirectoryLock(tmp_path)

    with held(first):
        with pytest.raises(DataDirectoryLockedError) as caught:
            second.acquire()
        assert caught.value.data_dir == tmp_path
        assert "use API mode (--url or --socket)" in str(caught.value)

    second.acquire()
    second.release()


def test_acquiring_creates_the_data_directory(tmp_path: Path) -> None:
    lock = FileDataDirectoryLock(tmp_path / "missing" / "data")

    with held(lock):
        assert lock.path.is_file()


def test_the_lock_file_names_the_holder(tmp_path: Path) -> None:
    lock = FileDataDirectoryLock(tmp_path)

    with held(lock):
        pid = lock.path.read_text(encoding="utf-8").strip()

    assert pid.isdigit()


def test_release_is_idempotent_and_a_handle_can_reacquire(tmp_path: Path) -> None:
    lock = FileDataDirectoryLock(tmp_path)
    lock.release()

    lock.acquire()
    lock.release()
    lock.release()
    lock.acquire()
    lock.release()


def test_acquiring_twice_on_one_handle_is_a_bug(tmp_path: Path) -> None:
    lock = FileDataDirectoryLock(tmp_path)

    with held(lock), pytest.raises(RuntimeError):
        lock.acquire()


@dataclass(slots=True)
class RecordingLock:
    calls: list[str] = field(default_factory=list)

    def acquire(self) -> None:
        self.calls.append("acquire")

    def release(self) -> None:
        self.calls.append("release")


def test_held_releases_when_the_block_raises() -> None:
    lock = RecordingLock()

    with pytest.raises(ValueError, match="boom"), held(lock):
        raise ValueError("boom")

    assert lock.calls == ["acquire", "release"]


def test_held_does_not_release_a_lock_it_could_not_take(tmp_path: Path) -> None:
    holder = FileDataDirectoryLock(tmp_path)
    other = FileDataDirectoryLock(tmp_path)

    with held(holder):
        with pytest.raises(DataDirectoryLockedError), held(other):
            pass
        # The holder still has it: a third handle is refused too.
        with pytest.raises(DataDirectoryLockedError):
            FileDataDirectoryLock(tmp_path).acquire()
