from pathlib import Path

import pytest
from pydantic import SecretStr, TypeAdapter, ValidationError

from git_manager.core import HttpTarget, LocalTarget, SocketTarget, Target

TARGET: TypeAdapter[LocalTarget | HttpTarget | SocketTarget] = TypeAdapter(Target)


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text("repo: {}\n", encoding="utf-8")
    return path


def test_config_selects_local_mode(config_file: Path) -> None:
    assert TARGET.validate_python({"config": config_file}) == LocalTarget(config=config_file)


def test_url_with_token_selects_http_mode() -> None:
    target = TARGET.validate_python({"url": "http://gm.test", "token": "secret"})

    assert target == HttpTarget(url="http://gm.test", token=SecretStr("secret"))


def test_socket_selects_socket_mode(tmp_path: Path) -> None:
    socket = tmp_path / "api.sock"

    assert TARGET.validate_python({"socket": socket}) == SocketTarget(socket=socket)


def test_built_targets_are_accepted_as_is(config_file: Path) -> None:
    target = LocalTarget(config=config_file)

    assert TARGET.validate_python(target) is target


def test_token_never_appears_in_repr() -> None:
    target = TARGET.validate_python({"url": "http://gm.test", "token": "secret"})

    assert "secret" not in repr(target)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ({}, "choose one target"),
        ({"token": "t"}, "choose one target"),
        ({"socket": "api.sock", "url": "http://gm.test"}, "choose one target"),
        ({"url": "http://gm.test"}, "--url needs a token"),
        ({"url": "http://gm.test", "token": ""}, "--url needs a token"),
        ({"url": "not a url", "token": "t"}, "invalid --url"),
        ({"socket": "api.sock", "port": 1}, "Extra inputs are not permitted"),
        ({"config": "missing.yaml"}, "Path does not point to a file"),
    ],
    ids=[
        "nothing",
        "token-only",
        "socket-and-url",
        "url-without-token",
        "url-with-empty-token",
        "bad-url",
        "unknown-option",
        "missing-config",
    ],
)
def test_invalid_targets_fail_validation(target: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        TARGET.validate_python(target)
