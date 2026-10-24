from git_manager.supervisor.errors import StartupError


def test_a_startup_error_carries_its_message() -> None:
    assert str(StartupError("missing gm")) == "missing gm"
