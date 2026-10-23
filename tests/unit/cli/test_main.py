import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from git_manager.cli.main import build_app
from git_manager.core import (
    ApiResponseError,
    HttpTarget,
    LocalTarget,
    Operations,
    Service,
    SocketTarget,
    build_connector,
)
from git_manager.core.targets import PlainHttp
from git_manager.core.unavailable import UnavailableBranches, UnavailableConfig, UnavailableRuns
from git_manager.health import HealthStatus
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


def test_target_flag_replaces_the_settings_file_target(service: Operations, tmp_path: Path) -> None:
    Path("git-manager.yaml").write_text(
        "target:\n  url: http://127.0.0.1:8765\n  token: t\n", encoding="utf-8"
    )
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["doctor", "--socket", str(tmp_path / "api.sock")])

    assert status == 0
    assert connector.targets == [SocketTarget(socket=tmp_path / "api.sock")]


def test_doctor_rejects_two_target_flags(
    service: Operations, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(
        app, ["doctor", "--socket", str(tmp_path / "api.sock"), "--url", "http://gm.test"]
    )

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
        (
            ["doctor", "--url", "https://gm.test", "--plain-http", "never"],
            "error: --plain-http: Input should be",
        ),
    ],
    ids=[
        "invalid-flag-value",
        "unknown-flag",
        "missing-config",
        "invalid-section-flag",
        "invalid-target-flag",
    ],
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


def test_unknown_target_key_keeps_its_dotted_path(
    service: Operations, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("git-manager.yaml").write_text(
        f"target:\n  socket: {tmp_path / 'api.sock'}\n  tokn: t\n", encoding="utf-8"
    )
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["doctor"])

    assert status == 2
    assert capsys.readouterr().err == "error: target.tokn: Extra inputs are not permitted\n"


class UnexpectedResponseHealth:
    """Answers health like a server that is not Git Manager."""

    async def status(self) -> HealthStatus:
        raise ApiResponseError("unexpected response from http://127.0.0.1:8765/healthz")


def test_doctor_reports_an_unexpected_response_as_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reason = "not built in this test"
    operations = Service(
        health=UnexpectedResponseHealth(),
        config=UnavailableConfig(reason),
        branches=UnavailableBranches(reason),
        runs=UnavailableRuns(reason),
    )
    app = build_app(connect=RecordingConnector(operations), version=TEST_VERSION)

    status = run_cli(app, ["doctor", "--socket", str(tmp_path / "api.sock")])

    assert status == 1
    assert capsys.readouterr().err.startswith("error: unexpected response from")


def test_plain_http_flag_allows_a_remote_url(
    service: Operations, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GM_TARGET__TOKEN", "env-token")
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["doctor", "--url", "http://gm.test", "--plain-http", "allowed"])

    assert status == 0
    assert [
        target.plain_http for target in connector.targets if isinstance(target, HttpTarget)
    ] == [PlainHttp.ALLOWED]


def test_other_flags_keep_the_settings_file_plain_http_policy(service: Operations) -> None:
    Path("git-manager.yaml").write_text(
        "target:\n  url: http://gm.test\n  token: t\n  plain_http: allowed\n",
        encoding="utf-8",
    )
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["doctor", "--http.port", "9000"])

    assert status == 0
    assert [
        target.plain_http for target in connector.targets if isinstance(target, HttpTarget)
    ] == [PlainHttp.ALLOWED]


def test_url_flag_does_not_inherit_the_settings_file_plain_http_policy(
    service: Operations, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("git-manager.yaml").write_text(
        "target:\n  url: http://gm.test\n  token: t\n  plain_http: allowed\n",
        encoding="utf-8",
    )
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["doctor", "--url", "http://other.test"])

    assert status == 2
    assert connector.targets == []
    assert "would send the token unencrypted" in capsys.readouterr().err


def test_url_flag_uses_a_standalone_settings_file_plain_http_policy(service: Operations) -> None:
    Path("git-manager.yaml").write_text(
        "target:\n  token: t\n  plain_http: allowed\n", encoding="utf-8"
    )
    connector = RecordingConnector(service)
    app = build_app(connect=connector, version=TEST_VERSION)

    status = run_cli(app, ["doctor", "--url", "http://gm.test"])

    assert status == 0
    assert [
        target.plain_http for target in connector.targets if isinstance(target, HttpTarget)
    ] == [PlainHttp.ALLOWED]
