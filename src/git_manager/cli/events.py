"""Event commands: ``watch``."""

import sys
from collections.abc import AsyncIterable, Callable, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from typing import Annotated, assert_never

from cyclopts import App, Parameter

from git_manager.cli.output import fail, reported
from git_manager.config.models import NotifyOn, RepoConfig
from git_manager.core import (
    Connector,
    HttpTarget,
    LocalTarget,
    OperationError,
    Settings,
    SocketTarget,
)
from git_manager.events import Event, Notifier
from git_manager.events.errors import NotificationError
from git_manager.events.notifications import notification_for, should_notify

# Opens the host's desktop notifier, or ``None`` when this platform has none.
type NotifierFactory = Callable[[], Notifier | None]

WATCH_NEEDS_API = (
    "watch follows a running daemon's events: give it --url or --socket, not --config "
    "(local-mode commands print their own events as they run)"
)
NO_DESKTOP_NOTIFIER = f"--notify has no desktop notifier on this platform ({sys.platform})"


@dataclass(frozen=True, slots=True)
class BranchView:
    """What ``watch`` knows about tracked branches: names by id and their config."""

    names: Mapping[str, str]
    config: RepoConfig

    def name(self, event: Event) -> str:
        """The event's branch name, or its id for a branch tracked after ``watch`` began."""
        return self.names.get(event.branch_id, event.branch_id)

    def notify_on(self, event: Event) -> tuple[NotifyOn, ...]:
        """The ``notify.on`` of the event's branch, else of ``defaults``."""
        branch = self.config.branch(self.names.get(event.branch_id, ""))
        return (branch or self.config.defaults).notify.on


def event_line(event: Event, *, branch: str) -> str:
    """One event as a line: id, when, which branch, what happened and why."""
    parts = [str(event.id), event.at.isoformat(timespec="seconds"), branch, event.kind]
    if event.state is not None:
        parts.append(event.state)
    if event.reason is not None:
        parts.append(f"({event.reason})")
    if event.run_id is not None:
        parts.append(f"run {event.run_id}")
    return "  ".join(parts)


async def follow(
    events: AsyncIterable[Event], *, view: BranchView, notifier: Notifier | None
) -> None:
    """Print each event and, with a notifier, notify those its branch's ``notify.on`` selects.

    A notification that cannot be shown is reported on stderr; the watch goes on.
    """
    async for event in events:
        branch = view.name(event)
        # Flushed per line, so a pipe sees each event as it happens.
        print(event_line(event, branch=branch), flush=True)
        if notifier is None or not should_notify(event, view.notify_on(event)):
            continue
        try:
            await notifier.notify(notification_for(event.model_copy(update={"branch_id": branch})))
        except NotificationError as error:
            print(f"warning: notification not shown: {error}", file=sys.stderr)


def register(app: App, *, connect: Connector, notifier: NotifierFactory) -> None:
    """Add ``watch`` to ``app``."""

    @app.command
    async def watch(
        *,
        notify: bool = False,
        after: int | None = None,
        settings: Annotated[Settings, Parameter(parse=False)],
    ) -> None:
        """Print a running daemon's events as they happen, until it stops or Ctrl-C.

        Parameters
        ----------
        notify
            Also show a desktop notification for each event its branch's notify.on
            selects (osascript on macOS, notify-send on Linux).
        after
            First replay the recorded events after this event id.
        """
        match settings.target:
            case LocalTarget():
                fail(OperationError(WATCH_NEEDS_API))
            case HttpTarget() | SocketTarget():
                pass
            case _:
                assert_never(settings.target)
        desktop = notifier() if notify else None
        if notify and desktop is None:
            fail(OperationError(NO_DESKTOP_NOTIFIER))
        with reported():
            async with connect(settings.target) as operations:
                status = await operations.branches.status()
                view = BranchView(
                    names={branch.id: branch.name for branch in status.branches},
                    config=await operations.config.show(),
                )
                async with aclosing(operations.events.stream(after=after)) as events:
                    await follow(events, view=view, notifier=desktop)
