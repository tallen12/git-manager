from git_manager.verification import (
    DockerCleanupError,
    InvalidCommandError,
    UnsupportedDockerModeError,
)


def test_config_problems_are_value_errors_and_cleanup_is_not() -> None:
    assert issubclass(InvalidCommandError, ValueError)
    assert issubclass(UnsupportedDockerModeError, ValueError)
    assert not issubclass(DockerCleanupError, ValueError)
