"""``serve`` end to end: the daemon as the supervisor starts it, in its own process."""

import asyncio
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Generator, Sequence
from pathlib import Path

import httpx
import pytest
from cyclopts import App

from git_manager.branches.sync import SyncMode
from git_manager.cli.main import build_app, local_connector, local_runtime
from git_manager.cli.output import EXIT_FAILED
from git_manager.config import CheckoutRepoConfig, YamlConfigFile
from git_manager.events import Event, EventKind
from git_manager.store import DataDirectoryLockedError, FileDataDirectoryLock
from git_manager.store.database import open_database, state_db_path
from git_manager.store.repositories import SqlEventRepository
from git_manager.web.app import NO_TOKENS_FILE
from tests.conftest import AUTH_HEADERS, TEST_TOKEN, TEST_VERSION, run_cli
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


def health_status(port: int, headers: dict[str, str]) -> int | None:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/api/v1/healthz", headers=headers).status_code
    except httpx.ConnectError:
        return None


def healthy(port: int) -> bool:
    return health_status(port, AUTH_HEADERS) == httpx.codes.OK


def healthy_over_socket(path: Path) -> bool:
    """Whether the daemon answers over its socket without a token."""
    transport = httpx.HTTPTransport(uds=str(path))
    with httpx.Client(transport=transport, base_url="http://git-manager") as client:
        return client.get("/api/v1/healthz").status_code == httpx.codes.OK


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
def tokens_file(tmp_path: Path) -> Path:
    path = tmp_path / "tokens.yaml"
    path.write_text(
        f"tokens:\n  - name: operator\n    token: {TEST_TOKEN}\n    scopes: [read]\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def api_socket() -> Generator[Path]:
    # Unix socket paths are limited to about 100 bytes; pytest's tmp_path can be longer.
    with tempfile.TemporaryDirectory(prefix="gm-") as directory:
        yield Path(directory) / "api.sock"


@pytest.fixture
def app() -> App:
    environ = dict(os.environ)
    repo_config = CheckoutRepoConfig()

    def read_config(path: Path) -> YamlConfigFile:
        return YamlConfigFile(path, environ=environ, repo_config=repo_config)

    return build_app(
        connect=local_connector(environ=environ, repo_config=repo_config, version=TEST_VERSION),
        open_runtime=local_runtime(
            environ=environ, repo_config=repo_config, version=TEST_VERSION, sync=SyncMode.QUEUED
        ),
        read_config=read_config,
        version=TEST_VERSION,
    )


def test_serve_rebases_a_base_change_and_stops_on_sigterm(
    app: App,
    remote: Remote,
    config_file: Path,
    tokens_file: Path,
    api_socket: Path,
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
        env={
            **os.environ,
            "GM_HTTP__TOKENS_FILE": str(tokens_file),
            "GM_HTTP__SOCKET": str(api_socket),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        eventually(lambda: healthy(port))
        assert health_status(port, {}) == httpx.codes.UNAUTHORIZED
        assert healthy_over_socket(api_socket)
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
    assert not api_socket.exists()
    assert not list((data_dir / "worktrees").glob("*"))
    # Polls after the run saw the daemon's own push, which is not reported as a human's.
    kinds = [event.kind for event in asyncio.run(stored_events(data_dir))]
    assert EventKind.RUN_FINISHED in kinds
    assert EventKind.HEAD_MOVED not in kinds
    capsys.readouterr()
    assert run_cli(app, ["status", "--config", str(config_file)]) == 0
    assert capsys.readouterr().out.splitlines()[2].split()[:3] == ["feature/one", "main", "idle"]


def test_serve_without_a_tokens_file_fails_and_releases_the_data_directory(
    app: App, config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = run_cli(app, ["serve", "--config", str(config_file)])

    assert status == EXIT_FAILED
    assert capsys.readouterr().err == f"error: {NO_TOKENS_FILE}\n"
    assert not locked(tmp_path / "data")


def test_sync_through_the_daemon_queues_the_run(
    app: App,
    remote: Remote,
    tokens_file: Path,
    api_socket: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file = tmp_path / "manual.yaml"
    config_file.write_text(
        f"repo:\n  url: {remote.bare}\n  data_dir: {tmp_path / 'data'}\n"
        "defaults:\n  poll_interval: 100ms\n  cadence: {mode: manual}\n"
        "  verify:\n    test: 'true'\n    docker: {mode: none}\n",
        encoding="utf-8",
    )
    assert (
        run_cli(app, ["track", "feature/one", "--base", "main", "--config", str(config_file)]) == 0
    )
    old_parent = git(remote.bare, "rev-parse", "refs/heads/feature/one~1")
    port = free_port()
    daemon = subprocess.Popen(
        [*ENTRY_POINT, "serve", "--config", str(config_file), "--http.port", str(port)],
        env={
            **os.environ,
            "GM_HTTP__TOKENS_FILE": str(tokens_file),
            "GM_HTTP__SOCKET": str(api_socket),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        eventually(lambda: healthy(port))
        new_base = commit(remote.teammate, "other.txt", "base work\n", "main moves")
        git(remote.teammate, "push", "--quiet", "origin", "main")
        # Manual cadence: the poller sees the base move but never runs on its own.
        time.sleep(2)
        assert git(remote.bare, "rev-parse", "refs/heads/feature/one~1") == old_parent
        capsys.readouterr()

        status = run_cli(app, ["sync", "feature/one", "--socket", str(api_socket)])

        assert status == 0
        assert re.fullmatch(r"queued \S+ behind 0 other run\(s\)\n", capsys.readouterr().out)
        eventually(lambda: git(remote.bare, "rev-parse", "refs/heads/feature/one~1") == new_base)
        daemon.send_signal(signal.SIGTERM)
        output, _ = daemon.communicate(timeout=30)
    finally:
        if daemon.poll() is None:
            daemon.kill()
            daemon.communicate()

    assert daemon.returncode == 0, output
