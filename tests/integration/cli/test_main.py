from pathlib import Path

import pytest

from git_manager.cli.main import build_app
from git_manager.core import Operations, build_connector
from tests.conftest import TEST_VERSION, run_cli


def test_doctor_reports_unreachable_daemon(
    service: Operations, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = build_app(
        connect=build_connector(local=lambda _target: service),
        version=TEST_VERSION,
    )

    status = run_cli(app, ["doctor", "--socket", str(tmp_path / "missing.sock")])

    assert status == 1
    assert capsys.readouterr().err.startswith("error: ")
