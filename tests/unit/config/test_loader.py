from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.config import ConfigError
from git_manager.config.loader import REPO_CONFIG_SOURCE, build_config, parse_yaml, plain
from git_manager.config.models import CadenceMode
from tests.unit.config.conftest import StaticRepoConfig

MINIMAL = """
repo:
  url: git@example.com:o/r.git
branches:
  - name: feature/a
    base: main
"""


def test_plain_copies_yaml_containers_into_dicts_and_lists() -> None:
    assert plain({1: [{"a": None}], "b": (1,)}) == {"1": [{"a": None}], "b": (1,)}


def test_parse_yaml_reads_an_empty_document_as_an_empty_mapping() -> None:
    assert parse_yaml("# nothing yet\n", source="c.yaml") == {}


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("- just\n- a list\n", "must be a mapping"),
        ("repo: [unclosed\n", "expected"),
        ("repo: {}\nrepo: {}\n", "duplicate key"),
    ],
)
def test_parse_yaml_rejects_documents_that_are_not_config(text: str, problem: str) -> None:
    with pytest.raises(ConfigError) as caught:
        parse_yaml(text, source="c.yaml")

    assert caught.value.source == "c.yaml"
    assert problem in caught.value.problems[0]


def test_build_config_fills_every_default_from_a_minimal_file(
    repo_config: StaticRepoConfig,
) -> None:
    config = build_config(
        parse_yaml(MINIMAL, source="c.yaml"), source="c.yaml", environ={}, repo_config=repo_config
    )

    branch = config.branch("feature/a")
    assert branch is not None
    assert branch.base == "main"
    assert branch.poll_interval == timedelta(seconds=60)
    assert config.repo.trust_repo_config is False


def test_build_config_merges_defaults_and_branch_blocks_before_validation(
    repo_config: StaticRepoConfig,
) -> None:
    # The cron mode and its expression come from different layers; the branch block on
    # its own would fail validation.
    document = parse_yaml(
        MINIMAL.replace("    base: main", "    base: main\n    cadence: {mode: cron}")
        + "defaults:\n  cadence: {cron: '0 6 * * 1-5'}\n"
        + "  verify: {test: just test, lint: just lint}\n",
        source="c.yaml",
    )

    config = build_config(document, source="c.yaml", environ={}, repo_config=repo_config)

    branch = config.branch("feature/a")
    assert branch is not None
    assert branch.cadence.mode is CadenceMode.CRON
    assert branch.cadence.cron == "0 6 * * 1-5"
    assert branch.verify.lint == "just lint"


def test_build_config_applies_environment_overrides_last(repo_config: StaticRepoConfig) -> None:
    document = parse_yaml(MINIMAL + "    max_restarts: 1\n", source="c.yaml")
    environ = {"GM_DEFAULTS__MAX_RESTARTS": "7", "GM_BUDGET__DAILY_USD": "2.5"}

    config = build_config(document, source="c.yaml", environ=environ, repo_config=repo_config)

    assert config.defaults.max_restarts == 7
    assert config.branches[0].max_restarts == 7
    assert config.budget.daily_usd == 2.5


def test_build_config_reports_every_problem_with_its_branch_name(
    repo_config: StaticRepoConfig,
) -> None:
    document = parse_yaml(
        MINIMAL + "    poll_interval: soon\n    verify: {tset: x}\nbudget: {daily_usd: 0}\n",
        source="c.yaml",
    )

    with pytest.raises(ConfigError) as caught:
        build_config(document, source="c.yaml", environ={}, repo_config=repo_config)

    problems = caught.value.problems
    assert len(problems) == 3
    assert problems[0].startswith("budget.daily_usd: ")
    assert problems[1].startswith("branches[feature/a].poll_interval: invalid duration 'soon'")
    assert problems[2].startswith("branches[feature/a].verify.tset: ")


def test_build_config_reports_an_invalid_environment_override(
    repo_config: StaticRepoConfig,
) -> None:
    document = parse_yaml(MINIMAL, source="c.yaml")

    with pytest.raises(ConfigError) as caught:
        build_config(
            document,
            source="c.yaml",
            environ={"GM_DEFAULTS__MAX_RESTARTS": "many"},
            repo_config=repo_config,
        )

    assert caught.value.problems[0].startswith("defaults.max_restarts: ")


def test_build_config_reports_model_level_problems_without_a_path(
    repo_config: StaticRepoConfig,
) -> None:
    document = parse_yaml(MINIMAL + "  - name: feature/a\n    base: dev\n", source="c.yaml")

    with pytest.raises(ConfigError) as caught:
        build_config(document, source="c.yaml", environ={}, repo_config=repo_config)

    assert caught.value.problems == ("branches listed more than once: feature/a",)


def test_build_config_ignores_the_repo_file_unless_trusted(
    repo_config: StaticRepoConfig,
) -> None:
    repo_config.text = "defaults: {max_restarts: 9}\n"

    config = build_config(
        parse_yaml(MINIMAL, source="c.yaml"), source="c.yaml", environ={}, repo_config=repo_config
    )

    assert repo_config.reads == []
    assert config.defaults.max_restarts == 3


def test_build_config_layers_a_trusted_repo_file_under_branch_blocks(
    repo_config: StaticRepoConfig,
) -> None:
    repo_config.text = "defaults: {max_restarts: 9, rebase_merges: true}\n"
    document = parse_yaml(
        MINIMAL.replace("repo:\n", "repo:\n  trust_repo_config: true\n  data_dir: /srv/gm\n")
        + "    rebase_merges: false\n"
        + "defaults: {max_restarts: 1}\n",
        source="c.yaml",
    )

    config = build_config(document, source="c.yaml", environ={}, repo_config=repo_config)

    assert repo_config.reads == [Path("/srv/gm")]
    assert config.defaults.max_restarts == 9
    assert config.branches[0].max_restarts == 9
    assert config.branches[0].rebase_merges is False


def test_build_config_trusts_the_repo_through_an_environment_override(
    repo_config: StaticRepoConfig,
) -> None:
    repo_config.text = "defaults: {max_restarts: 9}\n"

    config = build_config(
        parse_yaml(MINIMAL, source="c.yaml"),
        source="c.yaml",
        environ={"GM_REPO__TRUST_REPO_CONFIG": "true"},
        repo_config=repo_config,
    )

    assert config.defaults.max_restarts == 9


def test_build_config_skips_the_repo_file_when_the_repo_section_is_invalid(
    repo_config: StaticRepoConfig,
) -> None:
    repo_config.text = "defaults: {max_restarts: 9}\n"
    document = parse_yaml("repo: {trust_repo_config: true}\n", source="c.yaml")

    with pytest.raises(ConfigError) as caught:
        build_config(document, source="c.yaml", environ={}, repo_config=repo_config)

    assert repo_config.reads == []
    assert caught.value.problems[0].startswith("repo.url: ")


def test_build_config_works_when_a_trusted_repo_has_no_file(
    repo_config: StaticRepoConfig,
) -> None:
    document = parse_yaml(
        MINIMAL.replace("repo:\n", "repo:\n  trust_repo_config: true\n"), source="c"
    )

    config = build_config(document, source="c", environ={}, repo_config=repo_config)

    assert repo_config.reads == [Path("/data")]
    assert config.defaults.max_restarts == 3


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("repo: {url: evil}\nbudget: {daily_usd: 1000}\n", "budget: only defaults: may be set"),
        ("defaults: [1]\n", "defaults: must be a mapping"),
        ("- 1\n", "must be a mapping"),
    ],
)
def test_build_config_rejects_a_repo_file_that_sets_more_than_defaults(
    repo_config: StaticRepoConfig, text: str, problem: str
) -> None:
    repo_config.text = text
    document = parse_yaml(
        MINIMAL.replace("repo:\n", "repo:\n  trust_repo_config: true\n"), source="c"
    )

    with pytest.raises(ConfigError) as caught:
        build_config(document, source="c", environ={}, repo_config=repo_config)

    assert caught.value.source == REPO_CONFIG_SOURCE
    assert problem in caught.value.problems[0]


def test_build_config_accepts_an_empty_trusted_repo_file(repo_config: StaticRepoConfig) -> None:
    repo_config.text = "defaults:\n"
    document = parse_yaml(
        MINIMAL.replace("repo:\n", "repo:\n  trust_repo_config: true\n"), source="c"
    )

    config = build_config(document, source="c", environ={}, repo_config=repo_config)

    assert config.defaults.max_restarts == 3
