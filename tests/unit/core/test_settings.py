import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from git_manager.core import HttpTarget, LocalTarget, Settings, SocketTarget
from git_manager.core.targets import PlainHttp


@pytest.fixture
def config_file() -> Path:
    # Tests run in an empty working directory (see the isolated_settings fixture).
    path = Path("config.yaml")
    path.write_text("repo: {}\n", encoding="utf-8")
    return path


@pytest.fixture
def secrets_dir() -> Path:
    return Path(os.environ["GM_SECRETS_DIR"])


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_defaults_fill_the_http_and_mcp_sections(config_file: Path) -> None:
    settings = Settings.model_validate({"target": {"config": config_file}})

    assert (settings.http.host, settings.http.port) == ("127.0.0.1", 8765)
    assert (settings.mcp.name, settings.mcp.path) == ("git-manager", "/mcp")


def test_reads_git_manager_yaml_in_the_working_directory(config_file: Path) -> None:
    write(Path("git-manager.yaml"), "target:\n  config: config.yaml\nhttp:\n  port: 9000\n")

    settings = Settings()

    assert settings.target == LocalTarget(config=config_file)
    assert settings.http.port == 9000


def test_settings_file_variable_picks_another_file(
    config_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "elsewhere.yaml"
    write(other, f"target:\n  config: {config_file.resolve()}\nmcp:\n  name: other\n")
    monkeypatch.setenv("GM_SETTINGS_FILE", str(other))

    assert Settings().mcp.name == "other"


def test_sources_override_in_order(
    config_file: Path, secrets_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Highest wins: init arguments, environment, .env, secrets directory, YAML file.
    write(Path("git-manager.yaml"), "target:\n  config: config.yaml\nhttp:\n  port: 1001\n")
    write(secrets_dir / "gm_http__port", "1002\n")
    assert Settings().http.port == 1002

    write(Path(".env"), "GM_HTTP__PORT=1003\nUNRELATED=ignored\n")
    assert Settings().http.port == 1003

    monkeypatch.setenv("GM_HTTP__PORT", "1004")
    assert Settings().http.port == 1004

    assert Settings.model_validate({"http": {"port": 1005}}).http.port == 1005


def test_nested_values_merge_across_sources(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(Path("git-manager.yaml"), "target:\n  config: config.yaml\nhttp:\n  host: 0.0.0.0\n")
    monkeypatch.setenv("GM_HTTP__PORT", "9100")

    settings = Settings()

    assert (settings.http.host, settings.http.port) == ("0.0.0.0", 9100)


def test_token_is_read_from_the_secrets_directory(secrets_dir: Path) -> None:
    write(secrets_dir / "gm_target__token", "file-token\n")

    target = Settings.model_validate({"target": {"url": "https://gm.test"}}).target

    assert isinstance(target, HttpTarget)
    assert target.token.get_secret_value() == "file-token"


def test_token_from_environment_and_url_from_a_flag_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GM_TARGET__TOKEN", "env-token")

    target = Settings.model_validate({"target": {"url": "https://gm.test"}}).target

    assert isinstance(target, HttpTarget)
    assert target.token.get_secret_value() == "env-token"


def test_local_and_socket_targets_ignore_a_token(
    config_file: Path, secrets_dir: Path, tmp_path: Path
) -> None:
    write(secrets_dir / "gm_target__token", "file-token\n")

    local = Settings.model_validate({"target": {"config": config_file}}).target
    socket = Settings.model_validate({"target": {"socket": tmp_path / "api.sock"}}).target

    assert local == LocalTarget(config=config_file)
    assert socket == SocketTarget(socket=tmp_path / "api.sock")


def test_local_and_socket_targets_ignore_the_plain_http_policy(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GM_TARGET__PLAIN_HTTP", "allowed")

    target = Settings.model_validate({"target": {"config": config_file}}).target

    assert target == LocalTarget(config=config_file)


def test_plain_http_policy_stays_with_the_url_it_was_written_for() -> None:
    write(Path("git-manager.yaml"), "target:\n  url: http://gm.test\n  plain_http: allowed\n")

    with pytest.raises(ValidationError, match="would send the token unencrypted"):
        Settings.model_validate({"target": {"url": "http://other.test", "token": "t"}})


def test_standalone_plain_http_policy_applies_to_a_url_flag() -> None:
    write(Path("git-manager.yaml"), "target:\n  token: t\n  plain_http: allowed\n")

    target = Settings.model_validate({"target": {"url": "http://gm.test"}}).target

    assert isinstance(target, HttpTarget)
    assert target.plain_http is PlainHttp.ALLOWED


def test_plain_http_policy_from_the_url_source_applies() -> None:
    write(
        Path("git-manager.yaml"),
        "target:\n  url: http://gm.test\n  token: t\n  plain_http: allowed\n",
    )

    target = Settings().target

    assert isinstance(target, HttpTarget)
    assert target.plain_http is PlainHttp.ALLOWED


def test_plain_http_policy_from_a_higher_source_applies_to_a_lower_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write(Path("git-manager.yaml"), "target:\n  url: http://gm.test\n  token: t\n")
    monkeypatch.setenv("GM_TARGET__PLAIN_HTTP", "allowed")

    target = Settings().target

    assert isinstance(target, HttpTarget)
    assert target.plain_http is PlainHttp.ALLOWED


def test_flag_target_replaces_a_variable_target(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GM_TARGET__URL", "https://gm.test")

    target = Settings.model_validate({"target": {"config": config_file}}).target

    assert target == LocalTarget(config=config_file)


def test_flag_target_replaces_a_settings_file_target(tmp_path: Path) -> None:
    write(Path("git-manager.yaml"), "target:\n  url: https://gm.test\n  token: t\n")

    target = Settings.model_validate({"target": {"socket": tmp_path / "api.sock"}}).target

    assert target == SocketTarget(socket=tmp_path / "api.sock")


def test_variable_target_replaces_a_settings_file_target(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(Path("git-manager.yaml"), "target:\n  url: https://gm.test\n")
    monkeypatch.setenv("GM_TARGET__CONFIG", str(config_file))

    assert Settings().target == LocalTarget(config=config_file)


def test_token_from_settings_file_joins_a_url_flag() -> None:
    write(Path("git-manager.yaml"), "target:\n  socket: api.sock\n  token: file-token\n")

    target = Settings.model_validate({"target": {"url": "https://gm.test"}}).target

    assert isinstance(target, HttpTarget)
    assert target.token.get_secret_value() == "file-token"


def test_two_targets_in_one_source_still_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GM_TARGET__URL", "https://gm.test")
    monkeypatch.setenv("GM_TARGET__SOCKET", "api.sock")

    with pytest.raises(ValidationError, match="choose one target"):
        Settings()


@pytest.mark.parametrize(
    ("yaml", "message"),
    [
        ("http:\n  port: 1\n", "no target"),
        ("target:\n  config: config.yaml\nhttp:\n  prot: 1\n", "Extra inputs"),
        ("target:\n  config: config.yaml\nsurprise: 1\n", "Extra inputs"),
    ],
    ids=["no-target", "typo-in-section", "unknown-section"],
)
def test_invalid_settings_files_fail_validation(config_file: Path, yaml: str, message: str) -> None:
    write(Path("git-manager.yaml"), yaml)

    with pytest.raises(ValidationError, match=message):
        Settings()
