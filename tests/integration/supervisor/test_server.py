import asyncio
import os
import sys
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from git_manager.isolation.channel import UnixSocketSupervisorChannel
from git_manager.isolation.models import (
    Chowned,
    ChownRequest,
    SpawnCompleted,
    SpawnErrorCode,
    SpawnFailed,
    SpawnRequest,
    SupervisorResponse,
)
from git_manager.isolation.wire import MAX_MESSAGE_BYTES, encode_request
from git_manager.runtime import ProcessUser
from git_manager.supervisor.handler import RequestHandler
from git_manager.supervisor.launcher import SubprocessLauncher
from git_manager.supervisor.main import ENTER_COMMAND
from git_manager.supervisor.models import Account
from git_manager.supervisor.server import SupervisorServer
from git_manager.supervisor.settings import SupervisorSettings
from git_manager.supervisor.system import OsOwnership
from tests.unit.supervisor.conftest import FakeAccounts, FixedPeers

RESPONSES: TypeAdapter[SupervisorResponse] = TypeAdapter(SupervisorResponse)
# Every role is the current user here; the real users exist only in the image.
ME = Account(name="me", uid=os.geteuid(), gid=os.getegid(), groups=(), home=Path.home())


def _read_pid(pid_file: Path) -> int | None:
    if pid_file.exists() and (text := pid_file.read_text(encoding="utf-8")):
        return int(text)
    return None


async def _wait_for_pid(pid_file: Path) -> int:
    """The pid the command wrote to ``pid_file``, once it has."""
    for _ in range(200):
        if (pid := _read_pid(pid_file)) is not None:
            return pid
        await asyncio.sleep(0.05)
    pytest.fail("the command never started")


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def worktree(data_root: Path) -> Path:
    path = data_root / "runs" / "run-1"
    path.mkdir(parents=True)
    return path


@pytest.fixture
async def socket_path(data_root: Path) -> AsyncGenerator[Path]:
    accounts = FakeAccounts(users={user: ME for user in ProcessUser})
    handler = RequestHandler(
        settings=SupervisorSettings(data_root=data_root),
        accounts=accounts,
        ownership=OsOwnership(),
        launcher=SubprocessLauncher(entry=ENTER_COMMAND),
    )
    server = SupervisorServer(handler=handler, peers=FixedPeers(uid=ME.uid))
    # AF_UNIX paths are short (104 bytes on macOS); pytest's tmp_path can be too long.
    with tempfile.TemporaryDirectory(prefix="gm-") as directory:
        path = Path(directory) / "s.sock"
        async with server.serving(path):
            yield path
        assert not path.exists()


async def _ask(path: Path, line: bytes) -> SupervisorResponse:
    reader, writer = await asyncio.open_unix_connection(path)
    writer.write(line)
    await writer.drain()
    reply = await reader.read()
    writer.close()
    await writer.wait_closed()
    return RESPONSES.validate_json(reply)


async def test_a_command_runs_over_the_socket(socket_path: Path, worktree: Path) -> None:
    request = SpawnRequest(
        argv=(sys.executable, "-c", "import os; print(os.environ['USER'])"),
        cwd=worktree,
        env={},
        user=ProcessUser.TESTS,
    )

    reply = await _ask(socket_path, encode_request(request))

    assert isinstance(reply, SpawnCompleted)
    assert reply.stdout == "me\n"


async def test_a_tree_is_handed_over_over_the_socket(socket_path: Path, worktree: Path) -> None:
    request = ChownRequest(path=worktree, user=ProcessUser.CLAUDE)

    assert await _ask(socket_path, encode_request(request)) == Chowned()


async def test_the_daemon_client_talks_to_the_supervisor(socket_path: Path, worktree: Path) -> None:
    channel = UnixSocketSupervisorChannel(socket_path)
    request = SpawnRequest(
        argv=(sys.executable, "-c", "print('through the channel')"),
        cwd=worktree,
        env={},
        user=ProcessUser.CLAUDE,
    )

    response = await channel.spawn(request)

    assert isinstance(response, SpawnCompleted)
    assert response.stdout == "through the channel\n"


async def test_a_malformed_request_is_rejected(socket_path: Path) -> None:
    reply = await _ask(socket_path, b'{"kind": "run", "argv": ["sh"]}\n')

    assert isinstance(reply, SpawnFailed)
    assert reply.code is SpawnErrorCode.INVALID_REQUEST


async def test_an_oversized_request_is_rejected(socket_path: Path) -> None:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    writer.write(b"x" * (MAX_MESSAGE_BYTES + 1))
    reply = RESPONSES.validate_json(await reader.read())
    writer.close()

    assert isinstance(reply, SpawnFailed)
    assert reply.code is SpawnErrorCode.INVALID_REQUEST


async def test_hanging_up_mid_command_kills_it(socket_path: Path, worktree: Path) -> None:
    pid_file = worktree / "pid"
    script = (
        f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
    )
    request = SpawnRequest(
        argv=(sys.executable, "-c", script), cwd=worktree, env={}, user=ProcessUser.TESTS
    )
    _reader, writer = await asyncio.open_unix_connection(socket_path)
    writer.write(encode_request(request))
    await writer.drain()
    pid = await _wait_for_pid(pid_file)

    writer.close()
    await writer.wait_closed()

    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("the command outlived its connection")
