from pathlib import Path

import pytest

from git_manager.config import ConfigError, ConfigStore, YamlConfigFile
from tests.unit.config.conftest import StaticRepoConfig

MINIMAL = "repo:\n  url: u\nbranches:\n  - name: a\n    base: main\n"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL, encoding="utf-8")
    return path


def open_file(path: Path, *, environ: dict[str, str] | None = None) -> YamlConfigFile:
    return YamlConfigFile(path, environ=environ or {}, repo_config=StaticRepoConfig())


def test_load_layers_the_file_with_environment_overrides(config_path: Path) -> None:
    store: ConfigStore = open_file(config_path, environ={"GM_DEFAULTS__MAX_RESTARTS": "8"})

    config = store.load()

    assert config.repo.url == "u"
    assert config.branches[0].max_restarts == 8


def test_load_reports_a_missing_file(tmp_path: Path) -> None:
    store = open_file(tmp_path / "missing.yaml")

    with pytest.raises(ConfigError, match="cannot read the file"):
        store.load()


def test_set_creates_missing_sections_and_returns_the_new_config(config_path: Path) -> None:
    store = open_file(config_path)

    config = store.set(["defaults", "verify", "test"], "just test")

    assert config.branches[0].verify.test == "just test"
    assert store.load() == config


def test_set_edits_a_branch_by_list_index(config_path: Path) -> None:
    store = open_file(config_path)

    config = store.set(["branches", 0, "base"], "develop")

    assert config.branches[0].base == "develop"


def test_set_writes_nested_lists_and_mappings(config_path: Path) -> None:
    store = open_file(config_path)

    config = store.set(
        ["defaults", "notify"], {"webhooks": [{"kind": "ntfy", "url": "https://n.test/gm"}]}
    )

    assert config.defaults.notify.webhooks[0].url == "https://n.test/gm"


def test_set_fills_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("", encoding="utf-8")

    config = open_file(path).set(["repo"], {"url": "u"})

    assert config.repo.url == "u"


@pytest.mark.parametrize(
    ("path", "value", "problem"),
    [
        (["defaults", "max_restarts"], "many", "defaults.max_restarts: "),
        (["defaults", "max_restartz"], 1, "defaults.max_restartz: "),
        (["branches", 3, "base"], "x", "branches.3: no list item 3"),
        (["repo", "url", "deeper"], "x", "repo.url: cannot go into a str"),
        (["branches", "a"], "x", "branches.a: cannot set this key"),
        ([], "x", "(root): name the key to set"),
        (["defaults", "poll_interval"], object(), "object is not plain YAML data"),
        (["defaults", "commits", "git_config"], {1: "x"}, "mapping keys must be strings"),
    ],
)
def test_set_rejects_an_invalid_edit_without_writing(
    config_path: Path, path: list[str | int], value: object, problem: str
) -> None:
    store = open_file(config_path)

    with pytest.raises(ConfigError) as caught:
        store.set(path, value)

    assert problem in caught.value.problems[0]
    assert config_path.read_text(encoding="utf-8") == MINIMAL


def test_set_refuses_a_file_that_does_not_parse(config_path: Path) -> None:
    config_path.write_text("repo: [unclosed\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        open_file(config_path).set(["repo", "url"], "u")


def test_set_refuses_a_document_that_is_not_a_mapping(config_path: Path) -> None:
    config_path.write_text("- 1\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="must be a mapping"):
        open_file(config_path).set(["repo", "url"], "u")


def test_path_is_the_file_it_was_opened_with(config_path: Path) -> None:
    assert open_file(config_path).path == config_path
