import sys

import pytest

from git_manager.supervisor.main import (
    DEFAULT_DAEMON_ARGV,
    ENTER_COMMAND,
    WRONG_PLATFORM,
    build_supervisor,
    main,
)
from git_manager.supervisor.settings import SupervisorSettings
from git_manager.supervisor.supervise import Supervisor


def test_the_supervisor_refuses_to_run_outside_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")

    with pytest.raises(SystemExit) as exit_:
        main(["git-manager", "serve"])

    assert exit_.value.code == WRONG_PLATFORM


def test_the_composition_root_builds_a_supervisor() -> None:
    supervisor = build_supervisor(SupervisorSettings(), {"PATH": "/bin"})

    assert isinstance(supervisor, Supervisor)


def test_the_daemon_is_serve_by_default_and_commands_enter_through_the_helper() -> None:
    assert DEFAULT_DAEMON_ARGV == ("git-manager", "serve")
    assert ENTER_COMMAND[0] == sys.executable
    assert ENTER_COMMAND[-1] == "git_manager.supervisor.enter"
