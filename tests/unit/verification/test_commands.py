import pytest

from git_manager.config import VerifyConfig
from git_manager.verification import (
    CommandsInvalid,
    CommandsMissing,
    CommandSource,
    InvalidCommandError,
    VerifyCommands,
    config_commands,
    split_command,
)


def test_commands_split_with_shell_quoting_but_no_shell() -> None:
    assert split_command("uv run pytest -q -k 'slow and not db'") == (
        "uv",
        "run",
        "pytest",
        "-q",
        "-k",
        "slow and not db",
    )
    assert split_command("make test && rm -rf /") == ("make", "test", "&&", "rm", "-rf", "/")


@pytest.mark.parametrize("command", ["", "   ", "pytest 'unbalanced"])
def test_unparseable_commands_are_rejected(command: str) -> None:
    with pytest.raises(InvalidCommandError):
        split_command(command)


def test_config_without_a_test_command_means_needs_config() -> None:
    assert config_commands(VerifyConfig(setup="just setup")) == CommandsMissing()


def test_config_with_a_bad_command_means_needs_config() -> None:
    result = config_commands(VerifyConfig(test="pytest 'oops"))

    assert isinstance(result, CommandsInvalid)
    assert "cannot parse" in result.message


def test_config_commands_come_from_config_with_a_stable_hash() -> None:
    config = VerifyConfig(setup="just setup", test="just test")

    first = config_commands(config)
    second = config_commands(VerifyConfig(setup="just setup", test="just test"))
    changed = config_commands(VerifyConfig(setup="just setup", test="just test", lint="ruff"))

    assert isinstance(first, VerifyCommands)
    assert isinstance(changed, VerifyCommands)
    assert first == second
    assert first.source is CommandSource.CONFIG
    assert first.confirmed_by is None
    assert (first.setup, first.test, first.lint) == ("just setup", "just test", None)
    assert first.source_hash != changed.source_hash
