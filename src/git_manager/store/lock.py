"""The exclusive data-directory lock, as an advisory ``flock`` on a file inside it."""

import fcntl
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from git_manager.store.errors import DataDirectoryLockedError
from git_manager.store.protocols import DataDirectoryLock

LOCK_FILE = "git-manager.lock"


class FileDataDirectoryLock:
    """``DataDirectoryLock`` backed by ``flock`` on ``<data_dir>/git-manager.lock``.

    ``flock`` belongs to the open file, so a second handle conflicts even in the same
    process, and the kernel drops it when the holder exits, crashed or not: a stale lock
    file never blocks a later start. The file holds the holder's pid for diagnosis only.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._fd: int | None = None

    @property
    def path(self) -> Path:
        """The lock file."""
        return self._data_dir / LOCK_FILE

    def acquire(self) -> None:
        if self._fd is not None:
            msg = f"data directory lock already held by this handle: {self._data_dir}"
            raise RuntimeError(msg)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(fd)
            raise DataDirectoryLockedError(self._data_dir) from error
        except BaseException:
            os.close(fd)
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        # Closing drops the flock; the file stays so a waiting process never races an unlink.
        os.close(fd)


@contextmanager
def held(lock: DataDirectoryLock) -> Generator[None]:
    """Hold ``lock`` for the ``with`` block. Raises ``DataDirectoryLockedError`` if held."""
    lock.acquire()
    try:
        yield
    finally:
        lock.release()
