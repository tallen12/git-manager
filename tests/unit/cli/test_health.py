from contextlib import nullcontext
from pathlib import Path

import pytest
from cyclopts import App

from git_manager.cli import health
from git_manager.cli.main import build_app
from git_manager.core import Operations, Service, UnavailableError, build_connector
from git_manager.core.unavailable import UnavailableBranches, UnavailableConfig, UnavailableRuns
from git_manager.health import HealthStatus
from tests.conftest import TEST_VERSION, run_cli
from tests.unit.cli.conftest import no_runtime, read_config


class DownHealth:
    """Health that is not available, like a domain that has not landed yet."""

    async def status(self) -> HealthStatus:
        raise UnavailableError("doctor", reason="test")


def test_register_adds_doctor() -> None:
    app = App(name="git-manager")

    health.register(app, connect=build_connector(local=lambda _target: nullcontext(_unused())))

    assert "doctor" in app


def _unused() -> Operations:
    msg = "not connected in this test"
    raise AssertionError(msg)


def test_doctor_reports_operation_errors_on_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reason = "not built in this test"
    operations = Service(
        health=DownHealth(),
        config=UnavailableConfig(reason),
        branches=UnavailableBranches(reason),
        runs=UnavailableRuns(reason),
    )

    config = tmp_path / "config.yaml"
    config.write_text("repo: {}\n", encoding="utf-8")
    app = build_app(
        open_runtime=no_runtime,
        read_config=read_config,
        connect=build_connector(local=lambda _target: nullcontext(operations)),
        version=TEST_VERSION,
    )

    status = run_cli(app, ["doctor", "--config", str(config)])

    assert status == 1
    assert capsys.readouterr().err == "error: doctor is not available: test\n"
