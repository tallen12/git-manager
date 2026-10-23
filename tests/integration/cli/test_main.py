from pathlib import Path

import pytest

from git_manager.cli.main import build_app
from git_manager.config import CheckoutRepoConfig, YamlConfigFile
from git_manager.core import Operations, build_connector
from tests.conftest import TEST_VERSION, run_cli


def read_config(path: Path) -> YamlConfigFile:
    return YamlConfigFile(path, environ={}, repo_config=CheckoutRepoConfig())


def test_doctor_reports_unreachable_daemon(
    service: Operations, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = build_app(
        read_config=read_config,
        connect=build_connector(local=lambda _target: service),
        version=TEST_VERSION,
    )

    status = run_cli(app, ["doctor", "--socket", str(tmp_path / "missing.sock")])

    assert status == 1
    assert capsys.readouterr().err.startswith("error: ")
