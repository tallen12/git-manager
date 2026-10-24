from git_manager.events import SubscriberLaggedError


def test_lagged_error_names_the_last_delivered_event() -> None:
    error = SubscriberLaggedError(last_id=41)

    assert error.last_id == 41
    assert "41" in str(error)
