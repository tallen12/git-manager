import pytest

from git_manager.config import RepoConfig, is_sensitive


@pytest.mark.parametrize(
    "path",
    [
        ("defaults", "claude", "model"),
        ("defaults", "claude", "limits", "memory"),
        ("defaults", "verify", "test"),
        ("defaults", "stack", "mode"),
        ("defaults", "approval_policy"),
        ("defaults", "auto_push_clean"),
        ("defaults", "notify", "webhooks"),
        ("defaults", "notify", "webhooks", 0, "url"),
        ("budget", "daily_usd"),
        ("repo", "signing_key"),
        ("repo", "trust_repo_config"),
        ("branches", 0, "verify", "test"),
        ("branches", 2, "claude", "extra_allowed_tools"),
    ],
)
def test_keys_the_spec_lists_need_the_approve_scope(path: tuple[str | int, ...]) -> None:
    assert is_sensitive(RepoConfig, path)


@pytest.mark.parametrize(
    "path",
    [
        ("defaults", "poll_interval"),
        ("defaults", "cadence", "mode"),
        ("defaults", "stack", "scope"),
        ("defaults", "notify", "on"),
        ("defaults", "commits", "committer", "email"),
        ("branches", 0, "cadence"),
        ("branches", 0, "base"),
        ("repo", "url"),
    ],
)
def test_other_keys_need_only_the_operate_scope(path: tuple[str | int, ...]) -> None:
    assert not is_sensitive(RepoConfig, path)


def test_unknown_keys_count_as_sensitive() -> None:
    assert is_sensitive(RepoConfig, ("defaults", "claud", "model"))
