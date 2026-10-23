from git_manager.config import ConfigOperations
from git_manager.core.unavailable import UnavailableConfig


def test_unavailable_config_satisfies_the_protocol() -> None:
    # The annotation is the contract: the type checker rejects a non-conforming class.
    operations: ConfigOperations = UnavailableConfig("later")

    assert operations is not None
