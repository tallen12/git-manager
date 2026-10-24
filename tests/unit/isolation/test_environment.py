from git_manager.isolation import (
    INHERITED_VARIABLES,
    SUPERVISED_INHERITED_VARIABLES,
    scrubbed_environment,
)

ORCHESTRATOR_ENV = {
    "PATH": "/usr/bin",
    "HOME": "/home/gm",
    "LANG": "C.UTF-8",
    "GH_TOKEN": "ghp_secret",
    "GM_TARGET__TOKEN": "secret",
    "SSH_AUTH_SOCK": "/tmp/agent.sock",
    "ANTHROPIC_API_KEY": "sk-secret",
}


def test_only_allowlisted_variables_are_inherited() -> None:
    env = scrubbed_environment({}, inherited=ORCHESTRATOR_ENV)

    assert env == {"PATH": "/usr/bin", "HOME": "/home/gm", "LANG": "C.UTF-8"}


def test_the_command_env_is_added_and_wins() -> None:
    env = scrubbed_environment(
        {"PATH": "/opt/bin", "GM_RUN_ID": "run-1"}, inherited=ORCHESTRATOR_ENV
    )

    assert env["PATH"] == "/opt/bin"
    assert env["GM_RUN_ID"] == "run-1"


def test_supervised_commands_do_not_inherit_the_orchestrator_home() -> None:
    env = scrubbed_environment(
        {}, inherited=ORCHESTRATOR_ENV, allowed=SUPERVISED_INHERITED_VARIABLES
    )

    assert "HOME" not in env
    assert SUPERVISED_INHERITED_VARIABLES < INHERITED_VARIABLES
