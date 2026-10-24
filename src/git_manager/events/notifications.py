"""Which events reach notification sinks, per ``notify.on``."""

from collections.abc import Callable, Collection
from typing import assert_never

from git_manager.config.models import NotifyOn
from git_manager.events.models import Event, EventKind

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
