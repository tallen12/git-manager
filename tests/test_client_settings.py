from pathlib import Path

import pytest
from pydantic import ValidationError

from git_manager.cli.settings import ClientSettings, HttpTarget, LocalTarget, SocketTarget


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text("repo: {}\n", encoding="utf-8")
    return path


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "token"
    path.write_text("file-token\n", encoding="utf-8")
    return path


def test_config_selects_local_mode(config_file: Path) -> None:
    assert ClientSettings(config=config_file).target() == LocalTarget(config=config_file)


def test_url_with_token_from_environment_selects_http_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GM_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("GM_TOKEN", "env-token")

    target = ClientSettings().target()

    assert isinstance(target, HttpTarget)
    assert str(target.url) == "http://127.0.0.1:8765/"
    assert target.token.get_secret_value() == "env-token"


def test_url_reads_and_strips_token_file(token_file: Path) -> None:
    target = ClientSettings(url="http://gm.test", token_file=token_file).target()

    assert isinstance(target, HttpTarget)
    assert target.token.get_secret_value() == "file-token"


def test_socket_selects_socket_mode(tmp_path: Path) -> None:
    socket = tmp_path / "api.sock"

    assert ClientSettings(socket=socket).target() == SocketTarget(socket=socket)


def test_flag_overrides_environment_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GM_SOCKET", str(tmp_path / "from-env.sock"))

    target = ClientSettings(socket=tmp_path / "from-flag.sock").target()

    assert target == SocketTarget(socket=tmp_path / "from-flag.sock")


def test_token_never_appears_in_repr(token_file: Path) -> None:
    settings = ClientSettings(url="http://gm.test", token_file=token_file)

    assert "file-token" not in repr(settings)
    assert "file-token" not in repr(settings.target())


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({}, "no target"),
        ({"url": "http://gm.test"}, "--url needs a token"),
        ({"socket": "api.sock", "url": "http://gm.test"}, "choose one target"),
    ],
    ids=["nothing", "url-without-token", "socket-and-url"],
)
def test_invalid_combinations_fail_validation(options: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ClientSettings.model_validate(options)


def test_config_and_url_together_fail_validation(
    monkeypatch: pytest.MonkeyPatch, config_file: Path
) -> None:
    monkeypatch.setenv("GM_URL", "http://gm.test")
    monkeypatch.setenv("GM_TOKEN", "env-token")

    with pytest.raises(ValidationError, match="choose one target"):
        ClientSettings(config=config_file)


def test_token_and_token_file_together_fail_validation(
    monkeypatch: pytest.MonkeyPatch, token_file: Path
) -> None:
    monkeypatch.setenv("GM_TOKEN", "env-token")

    with pytest.raises(ValidationError, match="only one of GM_TOKEN and --token-file"):
        ClientSettings(url="http://gm.test", token_file=token_file)


def test_empty_token_file_fails_validation(tmp_path: Path) -> None:
    empty = tmp_path / "token"
    empty.write_text("\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="is empty"):
        ClientSettings(url="http://gm.test", token_file=empty)


def test_missing_config_file_fails_validation(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ClientSettings(config=tmp_path / "missing.yaml")
