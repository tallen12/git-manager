import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from cyclopts import App

from git_manager.cli.connect import build_connector
from git_manager.cli.main import build_app
from git_manager.cli.settings import HttpTarget, LocalTarget, SocketTarget
from git_manager.core import Operations
from tests.conftest import TEST_VERSION


def run(app: App, tokens: list[str]) -> int:
    """Run the CLI and return its exit status."""
    try:
        app(tokens)
    except SystemExit as exit_:
        return exit_.code if isinstance(exit_.code, int) else 0
    return 0


def test_doctor_runs_in_process_with_config(
    service: Operations, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("repo: {}\n", encoding="utf-8")
    app = build_app(
        operations=service,
        connect=build_connector(local=lambda _target: service),
        version=TEST_VERSION,
    )

    status = run(app, ["doctor", "--config", str(config)])

    assert status == 0
    assert json.loads(capsys.readouterr().out) == {"status": "ok", "version": TEST_VERSION}


class RecordingConnector:
    """Records each target and serves the in-process operations for it."""

    def __init__(self, operations: Operations) -> None:
        self.operations = operations
        self.targets: list[LocalTarget | HttpTarget | SocketTarget] = []

    @asynccontextmanager
    async def __call__(
        self, target: LocalTarget | HttpTarget | SocketTarget
    ) -> AsyncGenerator[Operations]:
        self.targets.append(target)
        yield self.operations


def test_doctor_uses_api_mode_from_environment(
    service: Operations, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GM_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("GM_TOKEN", "env-token")
    connector = RecordingConnector(service)
    app = build_app(operations=service, connect=connector, version=TEST_VERSION)

    status = run(app, ["doctor"])

    assert status == 0
    assert [type(target) for target in connector.targets] == [HttpTarget]
    assert "env-token" not in capsys.readouterr().out


def test_doctor_without_target_explains_how_to_set_one(
    service: Operations, capsys: pytest.CaptureFixture[str]
) -> None:
    connector = RecordingConnector(service)
    app = build_app(operations=service, connect=connector, version=TEST_VERSION)

    status = run(app, ["doctor"])

    assert status == 2
    assert connector.targets == []
    assert "no target" in capsys.readouterr().err


def test_doctor_rejects_config_and_url_together(
    service: Operations,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("repo: {}\n", encoding="utf-8")
    monkeypatch.setenv("GM_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("GM_TOKEN", "env-token")
    connector = RecordingConnector(service)
    app = build_app(operations=service, connect=connector, version=TEST_VERSION)

    status = run(app, ["doctor", "--config", str(config)])

    assert status == 2
    assert connector.targets == []
    assert "choose one target" in capsys.readouterr().err


def test_doctor_reports_unreachable_daemon(
    service: Operations, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = build_app(
        operations=service,
        connect=build_connector(local=lambda _target: service),
        version=TEST_VERSION,
    )

    status = run(app, ["doctor", "--socket", str(tmp_path / "missing.sock")])

    assert status == 1
    assert capsys.readouterr().err.startswith("error: ")
