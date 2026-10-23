from pathlib import Path

import pytest
from pydantic import ValidationError

from git_manager.core import HttpTarget, LocalTarget, Settings, SocketTarget


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
    settings = Settings.model_validate({"target": {"config": config_file}})

    assert settings.target == LocalTarget(config=config_file)


def test_nested_environment_selects_http_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GM_TARGET__URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("GM_TARGET__TOKEN", "env-token")

    target = Settings().target

    assert isinstance(target, HttpTarget)
    assert target.url == "http://127.0.0.1:8765"
    assert target.bearer_token().get_secret_value() == "env-token"


def test_url_reads_and_strips_token_file(token_file: Path) -> None:
    target = Settings.model_validate(
        {"target": {"url": "http://gm.test", "token_file": token_file}}
    ).target

    assert isinstance(target, HttpTarget)
    assert target.bearer_token().get_secret_value() == "file-token"


def test_socket_selects_socket_mode(tmp_path: Path) -> None:
    socket = tmp_path / "api.sock"

    target = Settings.model_validate({"target": {"socket": socket}}).target

    assert target == SocketTarget(socket=socket)


def test_init_argument_overrides_environment_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GM_TARGET__SOCKET", str(tmp_path / "from-env.sock"))

    target = Settings.model_validate({"target": {"socket": tmp_path / "from-flag.sock"}}).target

    assert target == SocketTarget(socket=tmp_path / "from-flag.sock")


def test_init_argument_merges_with_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GM_TARGET__TOKEN", "env-token")

    target = Settings.model_validate({"target": {"url": "http://gm.test"}}).target

    assert isinstance(target, HttpTarget)
    assert target.bearer_token().get_secret_value() == "env-token"


def test_token_never_appears_in_repr(token_file: Path) -> None:
    settings = Settings.model_validate(
        {"target": {"url": "http://gm.test", "token_file": token_file}}
    )

    assert "file-token" not in repr(settings)
    assert "file-token" not in repr(settings.target)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (None, "no target"),
        ({"token_file": "token"}, "choose one target"),
        ({"url": "http://gm.test"}, "--url needs a token"),
        ({"url": "not a url", "token": "t"}, "invalid --url"),
        ({"socket": "api.sock", "url": "http://gm.test"}, "choose one target"),
        ({"socket": "api.sock", "token": "t"}, "Extra inputs are not permitted"),
    ],
    ids=[
        "nothing",
        "token-without-url",
        "url-without-token",
        "bad-url",
        "socket-and-url",
        "socket-with-token",
    ],
)
def test_invalid_targets_fail_validation(target: dict[str, str] | None, message: str) -> None:
    data = {} if target is None else {"target": target}

    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(data)


def test_config_flag_and_url_variable_together_fail_validation(
    monkeypatch: pytest.MonkeyPatch, config_file: Path
) -> None:
    monkeypatch.setenv("GM_TARGET__URL", "http://gm.test")

    with pytest.raises(ValidationError, match="choose one target"):
        Settings.model_validate({"target": {"config": config_file}})


def test_token_and_token_file_together_fail_validation(
    monkeypatch: pytest.MonkeyPatch, token_file: Path
) -> None:
    monkeypatch.setenv("GM_TARGET__TOKEN", "env-token")

    with pytest.raises(ValidationError, match="only one of GM_TARGET__TOKEN and --token-file"):
        Settings.model_validate({"target": {"url": "http://gm.test", "token_file": token_file}})


def test_empty_token_file_fails_validation(tmp_path: Path) -> None:
    empty = tmp_path / "token"
    empty.write_text("\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="is empty"):
        Settings.model_validate({"target": {"url": "http://gm.test", "token_file": empty}})


def test_missing_config_file_fails_validation(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"target": {"config": tmp_path / "missing.yaml"}})


@pytest.mark.parametrize("variant", ["local", "http", "socket"])
def test_built_targets_are_accepted_as_is(variant: str, config_file: Path, tmp_path: Path) -> None:
    target = {
        "local": LocalTarget(config=config_file),
        "http": HttpTarget.model_validate({"url": "http://gm.test", "token": "t"}),
        "socket": SocketTarget(socket=tmp_path / "api.sock"),
    }[variant]

    assert Settings(target=target).target == target
