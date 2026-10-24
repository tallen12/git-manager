from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.events import Notification, NotificationError, Notifier
from git_manager.events.desktop import (
    NOTIFY_TIMEOUT,
    NotifySendNotifier,
    OsascriptNotifier,
    desktop_notifier,
    notify_send_argv,
    osascript_argv,
)
from git_manager.runtime import Command, ProcessCompleted, ProcessResult, ProcessTimedOut
from tests.conftest import FakeProcessRunner

# Quotes and shell syntax must arrive as plain arguments, never as script or shell text.
HOSTILE = Notification(title='Git "Manager"', message='-n branch `x"; rm -rf ~`: pushed')


def test_osascript_passes_title_and_message_as_arguments() -> None:
    argv = osascript_argv(HOSTILE)

    assert argv[0] == "osascript"
    assert argv[-2:] == (HOSTILE.title, HOSTILE.message)
    script = " ".join(argv[1:-2])
    assert HOSTILE.message not in script
    assert "on run argv" in script


def test_notify_send_ends_options_before_the_text() -> None:
    assert notify_send_argv(HOSTILE) == ("notify-send", "--", HOSTILE.title, HOSTILE.message)


@pytest.mark.parametrize(
    ("notifier_type", "program"),
    [(OsascriptNotifier, "osascript"), (NotifySendNotifier, "notify-send")],
)
async def test_notifiers_run_their_program_through_the_runner(
    notifier_type: type[OsascriptNotifier | NotifySendNotifier],
    program: str,
    process_runner: FakeProcessRunner,
    tmp_path: Path,
) -> None:
    notifier: Notifier = notifier_type(runner=process_runner, cwd=tmp_path)

    await notifier.notify(HOSTILE)

    [command] = process_runner.commands
    assert command.argv[0] == program
    assert command.argv[-1] == HOSTILE.message
    assert (command.cwd, command.timeout) == (tmp_path, NOTIFY_TIMEOUT)
    assert dict(command.env) == {}


def _failing(_command: Command) -> ProcessResult:
    return ProcessCompleted(
        exit_code=1, stdout="", stderr="no daemon\n", duration=timedelta(seconds=1)
    )


def _timing_out(_command: Command) -> ProcessResult:
    return ProcessTimedOut(stdout="", stderr="", duration=NOTIFY_TIMEOUT)


@pytest.mark.parametrize(
    ("respond", "message"),
    [(_failing, "notify-send exited 1: no daemon"), (_timing_out, "notify-send timed out")],
)
async def test_a_failed_program_raises_notification_error(
    respond: Callable[[Command], ProcessResult], message: str, tmp_path: Path
) -> None:
    notifier = NotifySendNotifier(runner=FakeProcessRunner(respond=respond), cwd=tmp_path)

    with pytest.raises(NotificationError, match=message):
        await notifier.notify(HOSTILE)


class MissingProgramRunner:
    async def run(self, command: Command) -> ProcessResult:
        raise FileNotFoundError(command.argv[0])


async def test_a_missing_program_raises_notification_error(tmp_path: Path) -> None:
    notifier = OsascriptNotifier(runner=MissingProgramRunner(), cwd=tmp_path)

    with pytest.raises(NotificationError, match="cannot run osascript") as raised:
        await notifier.notify(HOSTILE)

    assert isinstance(raised.value.__cause__, FileNotFoundError)


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("darwin", OsascriptNotifier), ("linux", NotifySendNotifier)],
)
def test_desktop_notifier_picks_the_platform_adapter(
    platform: str, expected: type[Notifier], process_runner: FakeProcessRunner, tmp_path: Path
) -> None:
    assert isinstance(desktop_notifier(platform, runner=process_runner, cwd=tmp_path), expected)


def test_platforms_without_a_desktop_notifier_get_none(
    process_runner: FakeProcessRunner, tmp_path: Path
) -> None:
    assert desktop_notifier("win32", runner=process_runner, cwd=tmp_path) is None
