import pytest

from git_manager.config.models import RepoConfig, RepoSection
from git_manager.core.compose import git_environment, process_runner
from git_manager.isolation import DEFAULT_SOCKET, LocalProcessRunner

ENVIRON = {
    "PATH": "/bin",
    "HOME": "/home/gm",
    "SSH_AUTH_SOCK": "/agent.sock",
    "GH_TOKEN": "secret",
    "GM_TARGET__TOKEN": "secret",
}


def test_git_gets_the_allowlist_and_the_committer() -> None:
    config = RepoConfig(repo=RepoSection(url="u"))

    env = git_environment(config, ENVIRON)

    assert env == {
        "PATH": "/bin",
        "HOME": "/home/gm",
        "SSH_AUTH_SOCK": "/agent.sock",
        "GIT_COMMITTER_NAME": "Git Manager",
        "GIT_COMMITTER_EMAIL": "git-manager@users.noreply.github.com",
    }


def test_a_credential_file_becomes_the_ssh_key() -> None:
    config = RepoConfig.model_validate({"repo": {"url": "u", "credential": "/run/secrets/my key"}})

    env = git_environment(config, ENVIRON)

    assert env["GIT_SSH_COMMAND"] == "ssh -i '/run/secrets/my key' -o IdentitiesOnly=yes"


@pytest.mark.skipif(DEFAULT_SOCKET.exists(), reason="runs inside the container")
def test_outside_the_container_commands_run_locally() -> None:
    assert isinstance(process_runner(ENVIRON), LocalProcessRunner)
