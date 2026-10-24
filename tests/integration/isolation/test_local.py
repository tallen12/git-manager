import asyncio
import sys
import time
from datetime import timedelta
from pathlib import Path

from git_manager.isolation import LocalProcessRunner
from git_manager.runtime import Command, ProcessCompleted, ProcessTimedOut

INHERITED = {"PATH": "/usr/bin:/bin"}

# Appends to the file in argv[1] until killed.
BEAT = """
import sys, time
while True:
    with open(sys.argv[1], "a") as beats:
        beats.write(".")
    time.sleep(0.02)
"""
# Starts BEAT as a grandchild in the command's process group.
HEARTBEAT = f"""
import subprocess, sys
subprocess.Popen(
    [sys.executable, "-c", {BEAT!r}, sys.argv[1]],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
"""


def size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def wait_until_beating(beats: Path) -> None:
    deadline = time.monotonic() + 5
    while size(beats) == 0:
        assert time.monotonic() < deadline, "the heartbeat never started"
        time.sleep(0.02)


async def assert_stopped(beats: Path) -> None:
    """The heartbeat process is dead once the file stops growing."""
    await asyncio.sleep(0.1)
    before = size(beats)
    await asyncio.sleep(0.3)
    assert before > 0
    assert size(beats) == before


def python(code: str, *args: str, timeout: timedelta | None = None) -> Command:
    return Command(argv=(sys.executable, "-c", code, *args), cwd=Path.cwd(), timeout=timeout)


async def test_a_timeout_kills_the_whole_process_group_and_keeps_partial_output(
    tmp_path: Path,
) -> None:
    beats = tmp_path / "beats"
    code = HEARTBEAT + "print('started', flush=True)\nimport time\ntime.sleep(60)\n"
    runner = LocalProcessRunner(inherited=INHERITED)

    result = await runner.run(python(code, str(beats), timeout=timedelta(seconds=1)))

    assert isinstance(result, ProcessTimedOut)
    assert result.stdout == "started\n"
    assert timedelta(seconds=1) <= result.duration < timedelta(seconds=5)
    await assert_stopped(beats)


async def test_a_timeout_sends_sigterm_first_so_commands_can_clean_up() -> None:
    code = (
        "import signal, sys, time\n"
        "def stop(*_): print('cleaned up', flush=True); sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n"
    )
    runner = LocalProcessRunner(inherited=INHERITED)

    result = await runner.run(python(code, timeout=timedelta(seconds=1)))

    assert isinstance(result, ProcessTimedOut)
    assert result.stdout == "ready\ncleaned up\n"


async def test_a_command_ignoring_sigterm_is_killed_after_the_grace_period() -> None:
    code = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n"
    )
    runner = LocalProcessRunner(inherited=INHERITED, kill_grace=timedelta(milliseconds=200))
    started = time.monotonic()

    result = await runner.run(python(code, timeout=timedelta(seconds=1)))

    assert isinstance(result, ProcessTimedOut)
    assert time.monotonic() - started < 5


async def test_processes_left_behind_by_a_finished_command_are_killed(tmp_path: Path) -> None:
    beats = tmp_path / "beats"
    code = (
        HEARTBEAT
        + "import pathlib, sys, time\n"
        + "while not pathlib.Path(sys.argv[1]).exists(): time.sleep(0.01)\n"
    )
    runner = LocalProcessRunner(inherited=INHERITED)

    result = await runner.run(python(code, str(beats)))

    assert isinstance(result, ProcessCompleted)
    assert result.succeeded
    await assert_stopped(beats)


async def test_cancelling_a_run_kills_its_process_group(tmp_path: Path) -> None:
    beats = tmp_path / "beats"
    code = HEARTBEAT + "import time\ntime.sleep(60)\n"
    runner = LocalProcessRunner(inherited=INHERITED)

    task = asyncio.create_task(runner.run(python(code, str(beats))))
    await asyncio.to_thread(wait_until_beating, beats)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:  # pragma: no cover - the run must not swallow cancellation
        raise AssertionError("the run finished instead of being cancelled")

    await assert_stopped(beats)


async def test_runs_do_not_block_the_event_loop() -> None:
    runner = LocalProcessRunner(inherited=INHERITED)
    sleep = python("import time; time.sleep(1)")
    started = time.monotonic()

    results = await asyncio.gather(runner.run(sleep), runner.run(sleep), runner.run(sleep))

    assert all(isinstance(result, ProcessCompleted) for result in results)
    assert time.monotonic() - started < 2.5
