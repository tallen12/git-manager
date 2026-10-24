import asyncio
import os
from pathlib import Path

from git_manager.isolation.models import SpawnErrorCode, SpawnFailed
from git_manager.supervisor.launcher import SubprocessLauncher, read_status, tail_output
from git_manager.supervisor.models import Account, LaunchPlan


def _reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


async def test_output_within_the_limit_is_kept_whole() -> None:
    assert await tail_output(_reader("héllo\n".encode()), 100) == "héllo\n"


async def test_long_output_keeps_its_tail_and_says_what_was_dropped() -> None:
    text = await tail_output(_reader(b"a" * 90 + b"tail-end"), 10)

    assert text == "[git-manager: 88 earlier bytes dropped]\naatail-end"


async def test_no_stream_is_empty_output() -> None:
    assert await tail_output(None, 10) == ""


def _status(data: bytes) -> SpawnFailed | None:
    read, write = os.pipe()
    os.write(write, data)
    os.close(write)
    try:
        return read_status(read)
    finally:
        os.close(read)


def test_an_empty_status_pipe_means_the_command_started() -> None:
    assert _status(b"") is None


def test_the_status_pipe_carries_the_spawn_error() -> None:
    assert _status(b"2\nno such file") == SpawnFailed(
        code=SpawnErrorCode.START_FAILED, message="no such file"
    )
    assert _status(b"garbage") == SpawnFailed(code=SpawnErrorCode.START_FAILED, message="garbage")


async def test_a_missing_entry_helper_is_a_spawn_failure(tmp_path: Path) -> None:
    launcher = SubprocessLauncher(entry=(str(tmp_path / "missing-python"),))
    me = Account(name="me", uid=os.geteuid(), gid=os.getegid(), groups=(), home=tmp_path)
    plan = LaunchPlan(
        argv=("true",),
        cwd=tmp_path,
        env={},
        account=me,
        timeout=None,
        stdin=None,
        output_limit_bytes=10,
    )

    reply = await launcher.run(plan)

    assert isinstance(reply, SpawnFailed)
    assert reply.code is SpawnErrorCode.START_FAILED
