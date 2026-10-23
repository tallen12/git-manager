from git_manager.config import ConfigError
from git_manager.core import OperationError


def test_config_error_lists_every_problem_in_its_message() -> None:
    error = ConfigError("config.yaml", ["repo.url: missing", "budget: bad"])

    assert isinstance(error, OperationError)
    assert error.source == "config.yaml"
    assert error.problems == ("repo.url: missing", "budget: bad")
    assert str(error) == "invalid config config.yaml: repo.url: missing; budget: bad"
