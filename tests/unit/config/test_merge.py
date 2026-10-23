from git_manager.config.merge import deep_merge, env_overrides, layer


def test_deep_merge_merges_mappings_and_replaces_everything_else() -> None:
    lower: dict[str, object] = {"verify": {"test": "a", "lint": "b"}, "on": ["x", "y"], "n": 1}
    higher: dict[str, object] = {"verify": {"test": "c"}, "on": ["z"]}

    assert deep_merge(lower, higher) == {"verify": {"test": "c", "lint": "b"}, "on": ["z"], "n": 1}


def test_deep_merge_does_not_change_its_inputs() -> None:
    lower: dict[str, object] = {"verify": {"test": "a"}}

    deep_merge(lower, {"verify": {"test": "b"}})

    assert lower == {"verify": {"test": "a"}}


def test_deep_merge_lets_null_replace_a_section() -> None:
    assert deep_merge({"cadence": {"cron": "* * * * *"}}, {"cadence": None}) == {"cadence": None}


def test_env_overrides_nest_variables_by_double_underscore() -> None:
    environ = {
        "GM_DEFAULTS__CLAUDE__MAX_TURNS": "5",
        "GM_REPO__URL": "git@example.com:o/r.git",
        "gm_budget__daily_usd": "3",
    }

    assert env_overrides(environ) == {
        "defaults": {"claude": {"max_turns": "5"}},
        "repo": {"url": "git@example.com:o/r.git"},
        "budget": {"daily_usd": "3"},
    }


def test_env_overrides_ignore_settings_and_other_variables() -> None:
    environ = {
        "GM_TARGET__CONFIG": "config.yaml",
        "GM_HTTP__PORT": "1",
        "GM_SETTINGS_FILE": "x.yaml",
        "GM_REPO": "no key",
        "GM_REPO____URL": "empty segment",
        "HOME": "/home/gm",
    }

    assert env_overrides(environ) == {}


def test_env_overrides_read_json_lists_and_mappings() -> None:
    environ = {
        "GM_DEFAULTS__NOTIFY__ON": '["pushed"]',
        "GM_DEFAULTS__COMMITS__GIT_CONFIG": '{"merge.renames": "true"}',
        "GM_DEFAULTS__CLAUDE__RESOLUTION_PROMPT_EXTRA": "[not json",
    }

    assert env_overrides(environ) == {
        "defaults": {
            "notify": {"on": ["pushed"]},
            "commits": {"git_config": {"merge.renames": "true"}},
            "claude": {"resolution_prompt_extra": "[not json"},
        }
    }


def test_layer_puts_defaults_under_each_branch_block() -> None:
    document: dict[str, object] = {
        "repo": {"url": "u"},
        "defaults": {"verify": {"test": "just test", "lint": "just lint"}, "max_restarts": 2},
        "branches": [
            {"name": "a", "base": "main", "verify": {"test": "make test"}},
            {"name": "b", "base": "main"},
        ],
    }

    merged = layer(document, repo_defaults={}, overrides={})

    assert merged["branches"] == [
        {
            "name": "a",
            "base": "main",
            "max_restarts": 2,
            "verify": {"test": "make test", "lint": "just lint"},
        },
        {
            "name": "b",
            "base": "main",
            "max_restarts": 2,
            "verify": {"test": "just test", "lint": "just lint"},
        },
    ]
    assert merged["defaults"] == document["defaults"]


def test_layer_puts_the_repo_file_above_defaults_and_below_branch_blocks() -> None:
    document: dict[str, object] = {
        "defaults": {"max_restarts": 1, "rebase_merges": False},
        "branches": [{"name": "a", "base": "main", "max_restarts": 5}],
    }

    merged = layer(document, repo_defaults={"max_restarts": 3, "rebase_merges": True}, overrides={})

    assert merged["defaults"] == {"max_restarts": 3, "rebase_merges": True}
    assert merged["branches"] == [
        {"name": "a", "base": "main", "max_restarts": 5, "rebase_merges": True}
    ]


def test_layer_applies_environment_defaults_over_every_branch_block() -> None:
    document: dict[str, object] = {
        "repo": {"url": "u", "data_dir": "/data"},
        "branches": [{"name": "a", "base": "main", "max_restarts": 5}],
    }
    overrides: dict[str, object] = {
        "defaults": {"max_restarts": "9"},
        "repo": {"data_dir": "/srv"},
        "budget": {"daily_usd": "1"},
    }

    merged = layer(document, repo_defaults={}, overrides=overrides)

    assert merged["repo"] == {"url": "u", "data_dir": "/srv"}
    assert merged["budget"] == {"daily_usd": "1"}
    assert merged["defaults"] == {"max_restarts": "9"}
    assert merged["branches"] == [{"name": "a", "base": "main", "max_restarts": "9"}]


def test_layer_leaves_malformed_sections_for_validation_to_report() -> None:
    document: dict[str, object] = {"defaults": "oops", "repo": 1, "branches": ["not a mapping"]}

    merged = layer(document, repo_defaults={}, overrides={"repo": {"url": "u"}})

    assert merged == document
