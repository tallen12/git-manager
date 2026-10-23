from datetime import timedelta

from git_manager.events import EventDraft, EventKind, EventSink
from tests.conftest import START, FixedClock, RecordingEventSink


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
