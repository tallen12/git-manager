import os
import subprocess
from pathlib import Path

import pytest
from cyclopts import App

from git_manager.cli.main import run
from git_manager.core import Operations, Service
from git_manager.health import HealthReporter, StaticHealthReporter

TEST_VERSION = "0.0.0-test"


def run_cli(app: App, tokens: list[str]) -> int:
    """Run the CLI through its meta app, as ``git-manager`` does, and return the exit status."""
    try:
        run(app, tokens)
    except SystemExit as exit_:
        return exit_.code if isinstance(exit_.code, int) else 0
    return 0


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide the developer's global and system git config from every git call in tests.

    Hooks, signing and rebase defaults from ``~/.gitconfig`` would otherwise make git tests
    pass in CI and fail locally (or the reverse).
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture(autouse=True)
def isolated_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Hide every settings source the developer may have, so settings come only from tests.

    Clears ``GM_*`` variables and runs each test in an empty directory (no
    ``git-manager.yaml`` or ``.env``) with an empty secrets directory.
    """
    for name in [name for name in os.environ if name.startswith("GM_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
    monkeypatch.setenv("GM_SECRETS_DIR", str(tmp_path_factory.mktemp("secrets")))


@pytest.fixture
def reporter() -> HealthReporter:
    return StaticHealthReporter(version=TEST_VERSION)


@pytest.fixture
def service(reporter: HealthReporter) -> Operations:
    return Service(reporter=reporter)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """An empty git repository with a deterministic identity and no signing."""
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    for key, value in (
        ("user.name", "Test User"),
        ("user.email", "test@example.com"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(["git", "-C", str(tmp_path), "config", key, value], check=True)
    return tmp_path
