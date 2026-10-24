from datetime import timedelta

import pytest
from pydantic import ValidationError

from git_manager.config import RepoConfig
from git_manager.config.models import ApprovalPolicy, CadenceMode, NotifyOn


def test_a_minimal_config_is_just_a_url() -> None:
    config = RepoConfig.model_validate({"repo": {"url": "git@github.com:acme/app.git"}})

    assert config.defaults.poll_interval == timedelta(seconds=60)
    assert config.defaults.cadence.mode is CadenceMode.DEBOUNCE
    assert config.defaults.cadence.debounce == timedelta(minutes=10)
    assert config.defaults.approval_policy is ApprovalPolicy.ON_AI_CHANGE
    assert config.defaults.claude.max_turns == 30
    assert config.defaults.verify.timeout == timedelta(minutes=30)
    assert config.defaults.verify.test is None
    assert set(config.defaults.notify.on) == set(NotifyOn)
    assert config.repo.trust_repo_config is False
    assert config.branches == ()


def test_branch_entries_carry_their_effective_options() -> None:
    config = RepoConfig.model_validate(
        {
            "repo": {"url": "u"},
            "branches": [
                {"name": "feature/a", "base": "main", "verify": {"test": "just test"}},
            ],
        }
    )

    branch = config.branch("feature/a")
    assert branch is not None
    assert branch.verify.test == "just test"
    assert config.branch("feature/missing") is None


def test_typos_fail_instead_of_being_ignored() -> None:
    with pytest.raises(ValidationError, match="poll_intervall"):
        RepoConfig.model_validate({"repo": {"url": "u"}, "defaults": {"poll_intervall": "5s"}})


def test_branches_are_listed_once() -> None:
    entry = {"name": "feature/a", "base": "main"}
    with pytest.raises(ValidationError, match="more than once: feature/a"):
        RepoConfig.model_validate({"repo": {"url": "u"}, "branches": [entry, entry]})


def test_cron_cadence_needs_a_valid_expression() -> None:
    with pytest.raises(ValidationError, match=r"cadence\.cron is required"):
        RepoConfig.model_validate({"repo": {"url": "u"}, "defaults": {"cadence": {"mode": "cron"}}})
    with pytest.raises(ValidationError, match="not a valid cron expression"):
        RepoConfig.model_validate(
            {"repo": {"url": "u"}, "defaults": {"cadence": {"mode": "cron", "cron": "daily"}}}
        )

    config = RepoConfig.model_validate(
        {"repo": {"url": "u"}, "defaults": {"cadence": {"mode": "cron", "cron": "0 6 * * 1-5"}}}
    )
    assert config.defaults.cadence.cron == "0 6 * * 1-5"


def test_auto_retarget_cannot_be_turned_on_in_v1() -> None:
    with pytest.raises(ValidationError):
        RepoConfig.model_validate({"repo": {"url": "u"}, "defaults": {"allow_auto_retarget": True}})


def test_sizes_read_like_the_spec_example() -> None:
    config = RepoConfig.model_validate(
        {"repo": {"url": "u"}, "defaults": {"claude": {"limits": {"memory": "4GiB"}}}}
    )

    assert config.defaults.claude.limits.memory == 4 * 1024**3


def test_config_round_trips_through_json() -> None:
    config = RepoConfig.model_validate(
        {"repo": {"url": "u"}, "branches": [{"name": "f", "base": "main", "max_restarts": 1}]}
    )

    assert RepoConfig.model_validate_json(config.model_dump_json()) == config
