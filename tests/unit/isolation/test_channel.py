import tempfile
from pathlib import Path

import pytest

from git_manager.isolation import (
    DEFAULT_SOCKET,
    SpawnRequest,
    SupervisorUnavailableError,
    UnixSocketSupervisorChannel,
)
from git_manager.runtime import ProcessUser


def test_the_default_socket_lives_under_run() -> None:
    assert DEFAULT_SOCKET.name == "supervisor.sock"
    assert DEFAULT_SOCKET.is_absolute()


async def test_a_missing_supervisor_is_unavailable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        channel = UnixSocketSupervisorChannel(Path(directory) / "missing.sock")
        request = SpawnRequest(user=ProcessUser.TESTS, argv=("true",), cwd=Path.cwd(), env={})

        with pytest.raises(SupervisorUnavailableError, match=r"missing\.sock"):
            await channel.spawn(request)
