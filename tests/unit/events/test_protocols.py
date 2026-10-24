from datetime import timedelta

import pytest

from git_manager.events import (
    EventDraft,
    EventHistory,
    EventKind,
    EventSink,
    Notification,
    NotificationError,
    Notifier,
)
from tests.conftest import START, FixedClock, InMemoryEvents, RecordingEventSink, RecordingNotifier


async def test_recording_sink_numbers_events_and_stamps_the_clock_time() -> None:
    clock = FixedClock()
    fake = RecordingEventSink(clock=clock)
    sink: EventSink = fake

    first = await sink.emit(EventDraft(kind=EventKind.TRACKED, branch_id="b"))
    clock.advance(timedelta(seconds=5))
    second = await sink.emit(EventDraft(kind=EventKind.RUN_STARTED, branch_id="b", run_id="r"))

    assert [(event.id, event.at) for event in fake.events] == [
        (1, START),
        (2, START + timedelta(seconds=5)),
    ]
    assert (first.kind, second.run_id) == (EventKind.TRACKED, "r")


async def test_recording_notifier_records_or_fails() -> None:
    fake = RecordingNotifier()
    notifier: Notifier = fake
    shown = Notification(title="t", message="m")

    await notifier.notify(shown)
    fake.failing = True
    with pytest.raises(NotificationError):
        await notifier.notify(Notification(title="t", message="lost"))

    assert fake.shown == [shown]


async def test_in_memory_history_lists_after_an_id_in_pages() -> None:
    log = InMemoryEvents()
    history: EventHistory = log
    for _ in range(3):
        await log.append(EventDraft(kind=EventKind.TRACKED, branch_id="b"), at=START)

    assert [event.id for event in await history.list(after=1, limit=1)] == [2]
