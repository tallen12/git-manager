"""``serve`` end to end: the daemon as the supervisor starts it, in its own process."""

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
import pytest
from cyclopts import App

from git_manager.cli.main import build_app, local_connector, local_runtime
from git_manager.config import CheckoutRepoConfig, YamlConfigFile
from git_manager.events import Event, EventKind
from git_manager.store import DataDirectoryLockedError, FileDataDirectoryLock
from git_manager.store.database import open_database, state_db_path
from git_manager.store.repositories import SqlEventRepository
from tests.conftest import TEST_VERSION, run_cli
from tests.integration.rebasing.conftest import Remote, commit, git

# The installed ``git-manager`` script, run by the test's interpreter.
ENTRY_POINT = (sys.executable, "-c", "from git_manager import main; main()")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        address: object = probe.getsockname()
    assert isinstance(address, tuple)
    port = address[1]
    assert isinstance(port, int)
    return port


def eventually(check: Callable[[], bool]) -> None:
    """Wait up to 30 seconds for ``check`` to pass."""
    for _ in range(600):
        if check():
            return
        time.sleep(0.05)
    msg = "condition never held"
    raise AssertionError(msg)


def healthy(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/healthz").status_code == httpx.codes.OK
    except httpx.ConnectError:
        return False


def locked(data_dir: Path) -> bool:
    lock = FileDataDirectoryLock(data_dir)
    try:
        lock.acquire()
    except DataDirectoryLockedError:
        return True
    lock.release()
    return False


async def stored_events(data_dir: Path) -> Sequence[Event]:
    async with open_database(state_db_path(data_dir)) as database:
        return await SqlEventRepository(database).list(limit=1000)


@pytest.fixture
def config_file(remote: Remote, tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"repo:\n  url: {remote.bare}\n  data_dir: {tmp_path / 'data'}\n"
        "defaults:\n  poll_interval: 100ms\n  cadence: {mode: immediate}\n"
        "  verify:\n    test: 'true'\n    docker: {mode: none}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def app() -> App:
    environ = dict(os.environ)
    repo_config = CheckoutRepoConfig()

    def read_config(path: Path) -> YamlConfigFile:
        return YamlConfigFile(path, environ=environ, repo_config=repo_config)

    return build_app(
        connect=local_connector(environ=environ, repo_config=repo_config, version=TEST_VERSION),
        open_runtime=local_runtime(environ=environ, repo_config=repo_config, version=TEST_VERSION),
        read_config=read_config,
        version=TEST_VERSION,
    )


def test_serve_rebases_a_base_change_and_stops_on_sigterm(
    app: App,
    remote: Remote,
    config_file: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "data"
    assert (
        run_cli(app, ["track", "feature/one", "--base", "main", "--config", str(config_file)]) == 0
    )
    port = free_port()
    daemon = subprocess.Popen(
        [*ENTRY_POINT, "serve", "--config", str(config_file), "--http.port", str(port)],
        env=dict(os.environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        eventually(lambda: healthy(port))
        assert locked(data_dir)

        new_base = commit(remote.teammate, "other.txt", "base work\n", "main moves")
        git(remote.teammate, "push", "--quiet", "origin", "main")
        eventually(lambda: git(remote.bare, "rev-parse", "refs/heads/feature/one~1") == new_base)

        # Let the poller (1s tick) look at the pushed branch a few times before stopping.
        time.sleep(3)
        daemon.send_signal(signal.SIGTERM)
        output, _ = daemon.communicate(timeout=30)
    finally:
        if daemon.poll() is None:
            daemon.kill()
            daemon.communicate()

    assert daemon.returncode == 0, output
    assert not locked(data_dir)
    assert not list((data_dir / "worktrees").glob("*"))
    # Polls after the run saw the daemon's own push, which is not reported as a human's.
    kinds = [event.kind for event in asyncio.run(stored_events(data_dir))]
    assert EventKind.RUN_FINISHED in kinds
    assert EventKind.HEAD_MOVED not in kinds
    capsys.readouterr()
    assert run_cli(app, ["status", "--config", str(config_file)]) == 0
    assert capsys.readouterr().out.splitlines()[2].split()[:3] == ["feature/one", "main", "idle"]
