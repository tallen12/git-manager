import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from git_manager.cli.main import build_app
from git_manager.core import HttpTarget, LocalTarget, Operations, SocketTarget, build_connector
from tests.conftest import TEST_VERSION, run_cli


def test_doctor_runs_in_process_with_config(
    service: Operations, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("repo: {}\n", encoding="utf-8")
    app = build_app(
        connect=build_connector(local=lambda _target: service),
        version=TEST_VERSION,
    )

    status = run_cli(app, ["doctor", "--config", str(config)])

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
    monkeypatch.setenv("GM_TARGET__URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("GM_TARGET__TOKEN", "env-token")
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["doctor"])

    assert status == 0
    assert [type(target) for target in connector.targets] == [HttpTarget]
    assert "env-token" not in capsys.readouterr().out


def test_doctor_without_target_explains_how_to_set_one(
    service: Operations, capsys: pytest.CaptureFixture[str]
) -> None:
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["doctor"])

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
    monkeypatch.setenv("GM_TARGET__URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("GM_TARGET__TOKEN", "env-token")
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["doctor", "--config", str(config)])

    assert status == 2
    assert connector.targets == []
    assert "choose one target" in capsys.readouterr().err


def test_target_flag_before_the_command_applies_to_it(service: Operations, tmp_path: Path) -> None:
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["--socket", str(tmp_path / "api.sock"), "doctor"])

    assert status == 0
    assert connector.targets == [SocketTarget(socket=tmp_path / "api.sock")]


@pytest.mark.parametrize("command", [["serve"], ["mcp", "stdio"]], ids=["serve", "mcp-stdio"])
def test_server_commands_need_a_target_too(
    service: Operations, command: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, command)

    assert status == 2
    assert connector.targets == []
    assert "no target" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("tokens", "message"),
    [
        (["doctor", "--url", "not a url"], "error: invalid --url"),
        (["doctor", "--bogus"], "error: Unknown option: --bogus"),
        (["doctor", "--config", "missing.yaml"], "error: --config missing.yaml: Path does not"),
        (["--socket", "api.sock", "doctor", "--http.port", "x"], "error: http.port: Input should"),
    ],
    ids=["invalid-flag-value", "unknown-flag", "missing-config", "invalid-section-flag"],
)
def test_invalid_flags_print_one_line_errors(
    service: Operations,
    tokens: list[str],
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GM_TARGET__TOKEN", "env-token")
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, tokens)

    assert status == 2
    assert connector.targets == []
    assert capsys.readouterr().err.startswith(message)


def test_doctor_reads_target_from_settings_file(
    service: Operations, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("git-manager.yaml").write_text(
        f"target:\n  socket: {tmp_path / 'api.sock'}\nhttp:\n  prot: 1\n", encoding="utf-8"
    )
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["doctor"])

    assert status == 2
    assert connector.targets == []
    assert capsys.readouterr().err == "error: http.prot: Extra inputs are not permitted\n"
