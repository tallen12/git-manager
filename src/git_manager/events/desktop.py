"""Desktop notifiers for the host CLI: ``osascript`` on macOS, ``notify-send`` on Linux.

Both run through the injected ``ProcessRunner`` with argument lists. The title and
message are passed as separate arguments, never spliced into a script or shell line, so
a branch name cannot inject AppleScript or shell syntax.
"""

from datetime import timedelta
from pathlib import Path
from typing import assert_never

from git_manager.events.errors import NotificationError
from git_manager.events.models import Notification
from git_manager.events.protocols import Notifier
from git_manager.runtime.models import Command, ProcessCompleted, ProcessTimedOut
from git_manager.runtime.protocols import ProcessRunner

NOTIFY_TIMEOUT = timedelta(seconds=10)
# ``on run argv`` reads the title and message from the arguments after the script.
_OSASCRIPT_SCRIPT = (
    "on run argv",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "end run",
)


def osascript_argv(notification: Notification) -> tuple[str, ...]:
    """The ``osascript`` command line that shows ``notification`` on macOS."""
    lines = tuple(arg for line in _OSASCRIPT_SCRIPT for arg in ("-e", line))
    return ("osascript", *lines, notification.title, notification.message)


def notify_send_argv(notification: Notification) -> tuple[str, ...]:
    """The ``notify-send`` command line that shows ``notification`` on Linux."""
    # ``--`` keeps a message starting with ``-`` from being read as an option.
    return ("notify-send", "--", notification.title, notification.message)


async def _show(runner: ProcessRunner, argv: tuple[str, ...], *, cwd: Path) -> None:
    command = Command(argv=argv, cwd=cwd, timeout=NOTIFY_TIMEOUT)
    try:
        result = await runner.run(command)
    except OSError as error:
        msg = f"cannot run {argv[0]}: {error}"
        raise NotificationError(msg) from error
    match result:
        case ProcessCompleted(exit_code=0):
            return
        case ProcessCompleted(exit_code=code, stderr=stderr):
            msg = f"{argv[0]} exited {code}: {stderr.strip()}"
            raise NotificationError(msg)
        case ProcessTimedOut():
            msg = f"{argv[0]} timed out after {NOTIFY_TIMEOUT.total_seconds():g}s"
            raise NotificationError(msg)
        case _:
            assert_never(result)


class OsascriptNotifier:
    """``Notifier`` showing macOS notifications through ``osascript``."""

    def __init__(self, *, runner: ProcessRunner, cwd: Path) -> None:
        self._runner = runner
        self._cwd = cwd

    async def notify(self, notification: Notification) -> None:
        await _show(self._runner, osascript_argv(notification), cwd=self._cwd)


class NotifySendNotifier:
    """``Notifier`` showing freedesktop notifications through ``notify-send``."""

    def __init__(self, *, runner: ProcessRunner, cwd: Path) -> None:
        self._runner = runner
        self._cwd = cwd

    async def notify(self, notification: Notification) -> None:
        await _show(self._runner, notify_send_argv(notification), cwd=self._cwd)


def desktop_notifier(platform: str, *, runner: ProcessRunner, cwd: Path) -> Notifier | None:
    """The desktop notifier for ``platform`` (a ``sys.platform`` value), if there is one.

    Only composition roots call this, passing ``sys.platform``. ``None`` means this
    platform has no desktop notifier yet (Windows toast is not built).
    """
    if platform == "darwin":
        return OsascriptNotifier(runner=runner, cwd=cwd)
    if platform.startswith("linux"):
        return NotifySendNotifier(runner=runner, cwd=cwd)
    return None
