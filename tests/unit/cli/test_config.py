import json
from pathlib import Path

import pytest
from cyclopts import App

from git_manager.cli import config
from git_manager.cli.main import build_app
from git_manager.config import ConfigService
from git_manager.core import LocalTarget, Operations, Service, build_connector
from git_manager.core.unavailable import UnavailableBranches, UnavailableRuns
from git_manager.health import HealthReporter, HealthService
from tests.conftest import TEST_VERSION, run_cli
from tests.unit.cli.conftest import read_config

CONFIG = "repo:\n  url: u\nbranches:\n  - name: a\n    base: main\n"


@pytest.fixture
def app(reporter: HealthReporter) -> App:
    """The CLI with in-process config operations over the target's file."""

    def local(target: LocalTarget) -> Operations:
        reason = "not built in this test"
        return Service(
            health=HealthService(reporter=reporter),
            config=ConfigService(read_config(target.config)),
            branches=UnavailableBranches(reason),
            runs=UnavailableRuns(reason),
        )

    return build_app(
        read_config=read_config, connect=build_connector(local=local), version=TEST_VERSION
    )


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def test_register_adds_the_config_group(service: Operations) -> None:
    app = App(name="git-manager")

    config.register(
        app, connect=build_connector(local=lambda _target: service), read_config=read_config
    )

    assert "show" in app["config"]
    assert "validate" in app["config"]


def test_show_prints_the_effective_config_as_json(
    app: App, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = run_cli(app, ["config", "show", "--config", str(config_file)])

    assert status == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["repo"]["url"] == "u"
    assert shown["branches"][0]["name"] == "a"
    assert shown["branches"][0]["cadence"]["debounce"] == "10m"


def test_show_reports_an_invalid_config(
    app: App, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file.write_text("repo: {}\n", encoding="utf-8")

    status = run_cli(app, ["config", "show", "--config", str(config_file)])

    assert status == 1
    assert capsys.readouterr().err.startswith(f"error: invalid config {config_file}: repo.url")


def test_show_reports_an_unavailable_api(
    service: Operations, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = build_app(
        read_config=read_config,
        connect=build_connector(local=lambda _target: service),
        version=TEST_VERSION,
    )
    config_file = tmp_path / "config.yaml"
    config_file.write_text(CONFIG, encoding="utf-8")

    status = run_cli(app, ["config", "show", "--config", str(config_file)])

    assert status == 1
    assert "config show is not available" in capsys.readouterr().err


def test_validate_accepts_a_valid_config(
    app: App, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = run_cli(app, ["config", "validate", "--config", str(config_file)])

    assert status == 0
    assert capsys.readouterr().out == f"ok: {config_file} (1 branches)\n"


def test_validate_reads_the_target_from_the_environment(
    app: App, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GM_TARGET__CONFIG", str(config_file))

    assert run_cli(app, ["config", "validate"]) == 0


def test_validate_lists_every_problem(
    app: App, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file.write_text(CONFIG + "    poll_interval: soon\nbudget: {daily_usd: 0}\n", "utf-8")

    status = run_cli(app, ["config", "validate", "--config", str(config_file)])

    assert status == 1
    errors = capsys.readouterr().err.splitlines()
    assert len(errors) == 2
    assert errors[0].startswith(f"error: {config_file}: budget.daily_usd: ")
    assert errors[1].startswith(f"error: {config_file}: branches[a].poll_interval: ")


def test_validate_needs_a_config_file_in_api_mode(
    app: App, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = run_cli(app, ["config", "validate", "--socket", str(tmp_path / "api.sock")])

    assert status == 1
    assert "pass --config PATH" in capsys.readouterr().err
