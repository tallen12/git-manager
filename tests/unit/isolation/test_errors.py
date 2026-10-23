from git_manager.isolation import (
    SupervisorError,
    SupervisorProtocolError,
    SupervisorUnavailableError,
)


def test_channel_failures_share_one_base_type() -> None:
    assert issubclass(SupervisorUnavailableError, SupervisorError)
    assert issubclass(SupervisorProtocolError, SupervisorError)
    assert not issubclass(SupervisorError, OSError)
