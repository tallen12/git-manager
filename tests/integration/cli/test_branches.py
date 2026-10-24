"""Local mode end to end: the real CLI wiring against a throwaway remote."""

import json
import os
from pathlib import Path

import pytest
from cyclopts import App

from git_manager.cli.main import build_app, local_connector
from git_manager.config import CheckoutRepoConfig, YamlConfigFile
from git_manager.store import FileDataDirectoryLock
from tests.conftest import TEST_VERSION, run_cli
from tests.integration.rebasing.conftest import Remote, commit, git


@pytest.fixture
def app() -> App:
    """The CLI as ``main`` wires it, with the test's environment."""
    environ = dict(os.environ)
    repo_config = CheckoutRepoConfig()

    def read_config(path: Path) -> YamlConfigFile:
        return YamlConfigFile(path, environ=environ, repo_config=repo_config)

    connect = local_connector(environ=environ, repo_config=repo_config, version=TEST_VERSION)
    return build_app(connect=connect, read_config=read_config, version=TEST_VERSION)


def test_track_sync_and_inspect_the_run(
    app: App, remote: Remote, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = ["--config", str(config_file)]
    new_base = commit(remote.teammate, "other.txt", "base work\n", "main moves")
    git(remote.teammate, "push", "--quiet", "origin", "main")

    assert run_cli(app, ["track", "feature/one", "--base", "main", *target]) == 0
    assert capsys.readouterr().out == (
        f"tracked feature/one on main: idle, fork point {remote.fork_point[:12]}\n"
    )

    assert run_cli(app, ["sync", "feature/one", *target]) == 0
    pushed = git(remote.bare, "rev-parse", "refs/heads/feature/one")
    assert git(remote.bare, "rev-parse", "refs/heads/feature/one~1") == new_base
    assert capsys.readouterr().out.splitlines()[1] == (
        f"feature/one {remote.feature_head[:12]} -> {pushed[:12]} on {new_base[:12]}"
    )

    assert run_cli(app, ["runs", *target]) == 0
    [row] = capsys.readouterr().out.splitlines()[1:]
    run_id, branch, trigger, outcome, *_ = row.split()
    assert (branch, trigger, outcome) == ("feature/one", "manual", "idle")

    assert run_cli(app, ["show", run_id, *target]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["base_to"], report["heads"][0]["new_head"]) == (new_base, pushed)
    assert [result["outcome"] for result in report["tests"]] == ["passed"]

    assert run_cli(app, ["diff", run_id, *target]) == 0
    assert "+++ b/feature.txt" in capsys.readouterr().out
    assert run_cli(app, ["logs", run_id, *target]) == 0
    assert capsys.readouterr().out.startswith("== test: true (passed, exit 0")

    assert run_cli(app, ["status", *target]) == 0
    status = capsys.readouterr().out.splitlines()
    assert status[0] == f"repo {remote.bare}"
    assert status[2].split()[:3] == ["feature/one", "main", "idle"]


def test_a_held_data_directory_points_to_api_mode(
    app: App, config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    daemon = FileDataDirectoryLock(tmp_path / "data")
    daemon.acquire()
    try:
        status = run_cli(app, ["status", "--config", str(config_file)])
    finally:
        daemon.release()

    assert status == 1
    err = capsys.readouterr().err
    assert err.startswith("error: a daemon is using this data directory; use API mode")
    assert err.count("\n") == 1


def test_pause_blocks_sync_until_resume(
    app: App, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = ["--config", str(config_file)]
    assert run_cli(app, ["track", "feature/one", "--base", "main", *target]) == 0

    assert run_cli(app, ["pause", "feature/one", *target]) == 0
    assert run_cli(app, ["sync", "feature/one", *target]) == 1
    assert run_cli(app, ["resume", "feature/one", *target]) == 0
    assert run_cli(app, ["untrack", "feature/one", *target]) == 0

    captured = capsys.readouterr()
    assert "feature/one on main: paused (paused_by_user)\n" in captured.out
    assert "paused; resume it first" in captured.err
    assert captured.out.endswith("feature/one on main: idle\nuntracked feature/one\n")
