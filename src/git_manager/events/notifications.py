"""Which events reach notification sinks, per ``notify.on``, and how they read."""

import logging
from collections.abc import AsyncIterable, Callable, Collection
from typing import assert_never

from git_manager.config.models import NotifyOn
from git_manager.events.errors import NotificationError
from git_manager.events.models import Event, EventKind, Notification
from git_manager.events.protocols import Notifier

NOTIFICATION_TITLE = "Git Manager"
_LOGGER = logging.getLogger(__name__)

_TOPICS = {topic.value: topic for topic in NotifyOn}


def notification_topics(event: Event) -> frozenset[NotifyOn]:
    """The ``notify.on`` names ``event`` matches; empty if it never notifies.

    A state change matches its new state (``needs_human``, ``base_missing``, ...) and its
    reason (``stack_removed``); a push matches ``pushed``.
    """
    match event.kind:
        case EventKind.PUSHED:
            return frozenset({NotifyOn.PUSHED})
        case EventKind.STATE_CHANGED:
            names = (value.value for value in (event.state, event.reason) if value is not None)
            return frozenset(_TOPICS[name] for name in names if name in _TOPICS)
        case (
            EventKind.TRACKED
            | EventKind.UNTRACKED
            | EventKind.RUN_STARTED
            | EventKind.RUN_FINISHED
            | EventKind.BASE_MOVED
            | EventKind.HEAD_MOVED
        ):
            return frozenset[NotifyOn]()
        case _:
            assert_never(event.kind)


def should_notify(event: Event, on: Collection[NotifyOn]) -> bool:
    """Whether ``event`` reaches sinks configured with ``notify.on``."""
    return not notification_topics(event).isdisjoint(on)


def notification_filter(on: Collection[NotifyOn]) -> Callable[[Event], bool]:
    """An ``accept`` predicate for ``EventSource.subscribe`` from ``notify.on``."""
    topics = frozenset(on)
    return lambda event: should_notify(event, topics)


def notification_for(event: Event) -> Notification:
    """The notification shown for ``event``: its branch, then what happened and why."""
    match event.kind:
        case EventKind.STATE_CHANGED if event.state is not None:
            what = event.state.value
        case _:
            what = event.kind.value
    if event.reason is not None:
        what = f"{what} ({event.reason.value})"
    return Notification(title=NOTIFICATION_TITLE, message=f"branch {event.branch_id}: {what}")


async def forward_notifications(
    events: AsyncIterable[Event],
    *,
    notifier: Notifier,
    on: Collection[NotifyOn],
    logger: logging.Logger = _LOGGER,
) -> None:
    """Show a notification for each event ``notify.on`` selects, until ``events`` ends.

    A notification that cannot be shown is logged and skipped: one failure must not end
    the watch.
    """
    topics = frozenset(on)
    async for event in events:
        if not should_notify(event, topics):
            continue
        try:
            await notifier.notify(notification_for(event))
        except NotificationError:
            logger.warning("could not show the notification for event %d", event.id, exc_info=True)
