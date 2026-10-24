import asyncio
import os
import signal
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.isolation.models import (
    SpawnCompleted,
    SpawnErrorCode,
    SpawnFailed,
    SpawnTimedOut,
)
from git_manager.supervisor.launcher import SubprocessDaemonStarter, SubprocessLauncher
from git_manager.supervisor.main import ENTER_COMMAND
from git_manager.supervisor.models import Account, LaunchPlan

PYTHON = sys.executable


def _same_directory(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


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
def me(tmp_path: Path) -> Account:
    return Account(name="me", uid=os.geteuid(), gid=os.getegid(), groups=(), home=tmp_path)


def _plan(
    me: Account,
    cwd: Path,
    *argv: str,
    timeout: timedelta | None = None,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    limit: int = 1024,
) -> LaunchPlan:
    return LaunchPlan(
        argv=argv,
        cwd=cwd,
        env=env or {"PATH": os.defpath},
        account=me,
        timeout=timeout,
        stdin=stdin,
        output_limit_bytes=limit,
    )


@pytest.fixture
def launcher() -> SubprocessLauncher:
    return SubprocessLauncher(entry=ENTER_COMMAND)


async def test_a_command_runs_in_its_directory_and_keeps_its_exit_code(
    launcher: SubprocessLauncher, me: Account, tmp_path: Path
) -> None:
    script = "import os, sys; print(os.getcwd()); sys.exit(3)"

    reply = await launcher.run(_plan(me, tmp_path, PYTHON, "-c", script))

    assert isinstance(reply, SpawnCompleted)
    assert reply.exit_code == 3
    assert _same_directory(Path(reply.stdout.strip()), tmp_path)


async def test_a_command_gets_exactly_its_environment(
    launcher: SubprocessLauncher, me: Account, tmp_path: Path
) -> None:
    # Not Python: it would add LC_CTYPE itself, which is the leak this checks for.
    reply = await launcher.run(_plan(me, tmp_path, "env", env={"ONLY": "this"}))

    assert isinstance(reply, SpawnCompleted)
    names = {line.partition("=")[0] for line in reply.stdout.splitlines()}
    # macOS adds __CF_USER_TEXT_ENCODING to every process; nothing else may appear.
    assert names - {"__CF_USER_TEXT_ENCODING"} == {"ONLY"}


async def test_a_requested_locale_is_kept(
    launcher: SubprocessLauncher, me: Account, tmp_path: Path
) -> None:
    script = "import os; print(os.environ['LC_CTYPE'])"

    reply = await launcher.run(
        _plan(me, tmp_path, PYTHON, "-c", script, env={"LC_CTYPE": "en_US.UTF-8"})
    )

    assert isinstance(reply, SpawnCompleted)
    assert reply.stdout == "en_US.UTF-8\n"


async def test_stdin_and_stderr_pass_through(
    launcher: SubprocessLauncher, me: Account, tmp_path: Path
) -> None:
    script = "import sys; sys.stderr.write(sys.stdin.read().upper())"

    reply = await launcher.run(_plan(me, tmp_path, PYTHON, "-c", script, stdin="conflict"))

    assert isinstance(reply, SpawnCompleted)
    assert reply.stderr == "CONFLICT"


async def test_output_is_capped_to_its_tail(
    launcher: SubprocessLauncher, me: Account, tmp_path: Path
) -> None:
    script = "print('x' * 5000 + 'END', end='')"

    reply = await launcher.run(_plan(me, tmp_path, PYTHON, "-c", script, limit=10))

    assert isinstance(reply, SpawnCompleted)
    assert reply.stdout.endswith("xxxxxxxEND")
    assert "4993 earlier bytes dropped" in reply.stdout


async def test_a_missing_program_is_a_spawn_failure(
    launcher: SubprocessLauncher, me: Account, tmp_path: Path
) -> None:
    reply = await launcher.run(_plan(me, tmp_path, "gm-no-such-program"))

    assert isinstance(reply, SpawnFailed)
    assert reply.code is SpawnErrorCode.START_FAILED
    assert "No such file" in reply.message


async def test_a_missing_directory_is_a_spawn_failure(
    launcher: SubprocessLauncher, me: Account, tmp_path: Path
) -> None:
    reply = await launcher.run(_plan(me, tmp_path / "gone", PYTHON, "-c", "pass"))

    assert isinstance(reply, SpawnFailed)
    assert "gone" in reply.message


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def test_a_timeout_kills_the_whole_process_group(
    launcher: SubprocessLauncher, me: Account, tmp_path: Path
) -> None:
    pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time; "
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        f"open({str(pid_file)!r}, 'w').write(str(child.pid)); print('started', flush=True); "
        "time.sleep(60)"
    )

    reply = await launcher.run(
        _plan(me, tmp_path, PYTHON, "-c", script, timeout=timedelta(seconds=2))
    )

    assert isinstance(reply, SpawnTimedOut)
    assert reply.stdout == "started\n"
    child = int(pid_file.read_text(encoding="utf-8"))
    for _ in range(50):
        if not _alive(child):
            break
        await asyncio.sleep(0.05)
    assert not _alive(child)


async def test_a_command_that_ignores_sigterm_is_killed_after_the_grace(
    me: Account, tmp_path: Path
) -> None:
    launcher = SubprocessLauncher(entry=ENTER_COMMAND, terminate_grace=0.5)
    script = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready', flush=True); time.sleep(60)"
    )

    reply = await launcher.run(
        _plan(me, tmp_path, PYTHON, "-c", script, timeout=timedelta(seconds=1))
    )

    assert isinstance(reply, SpawnTimedOut)
    assert reply.stdout == "ready\n"
    assert reply.duration_s < 10


async def test_a_command_that_stops_on_sigterm_ends_within_the_grace(
    me: Account, tmp_path: Path
) -> None:
    launcher = SubprocessLauncher(entry=ENTER_COMMAND, terminate_grace=30)
    script = "import time; print('ready', flush=True); time.sleep(60)"

    reply = await launcher.run(
        _plan(me, tmp_path, PYTHON, "-c", script, timeout=timedelta(seconds=1))
    )

    assert isinstance(reply, SpawnTimedOut)
    assert reply.duration_s < 10


async def test_cancelling_a_run_kills_the_command(
    launcher: SubprocessLauncher, me: Account, tmp_path: Path
) -> None:
    pid_file = tmp_path / "self.pid"
    script = (
        f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
    )
    running = asyncio.create_task(launcher.run(_plan(me, tmp_path, PYTHON, "-c", script)))
    pid = await _wait_for_pid(pid_file)

    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    for _ in range(50):
        if not _alive(pid):
            break
        await asyncio.sleep(0.05)
    assert not _alive(pid)


async def test_the_daemon_runs_until_signalled(me: Account) -> None:
    daemon = await SubprocessDaemonStarter().start(
        (PYTHON, "-c", "import time; time.sleep(60)"), account=me, env={}
    )

    daemon.signal(signal.SIGTERM)

    assert await daemon.wait() == -signal.SIGTERM
    daemon.signal(signal.SIGTERM)  # after exit: no error
