import socket
import stat
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from git_manager.web.listeners import SOCKET_MODE, unix_listener


@pytest.fixture
def directory() -> Generator[Path]:
    # Unix socket paths are limited to about 100 bytes; pytest's tmp_path can be longer.
    with tempfile.TemporaryDirectory(prefix="gm-") as name:
        yield Path(name)


def test_the_socket_takes_the_mode_and_its_directory_group(directory: Path) -> None:
    path = directory / "api.sock"

    with unix_listener(path) as listener:
        info = path.stat()
        assert stat.S_ISSOCK(info.st_mode)
        assert stat.S_IMODE(info.st_mode) == SOCKET_MODE
        assert info.st_gid == directory.stat().st_gid
        assert listener.family == socket.AF_UNIX

    assert not path.exists()


def test_a_stale_socket_is_replaced(directory: Path) -> None:
    path = directory / "api.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
        stale.bind(str(path))

    with unix_listener(path):
        assert stat.S_ISSOCK(path.stat().st_mode)


def test_another_file_at_the_path_is_kept(directory: Path) -> None:
    path = directory / "api.sock"
    path.write_text("not a socket", encoding="utf-8")

    with pytest.raises(OSError), unix_listener(path):
        pass

    assert path.read_text(encoding="utf-8") == "not a socket"
