import pytest
from pydantic import ValidationError

from git_manager.branches import BranchState
from git_manager.events import Event, EventDraft, EventKind
from tests.conftest import START


def test_event_keeps_the_draft_and_adds_id_and_time() -> None:
    draft = EventDraft(
        kind=EventKind.STATE_CHANGED,
        branch_id="branch-1",
        state=BranchState.TESTS_FAILED,
        data={"failed_step": "test", "attempts": 2},
    )

    event = Event(**draft.model_dump(), id=1, at=START)

    assert Event.model_validate_json(event.model_dump_json()) == event
    assert event.data == {"failed_step": "test", "attempts": 2}


def test_event_times_carry_a_timezone() -> None:
    with pytest.raises(ValidationError):
        Event(kind=EventKind.PUSHED, branch_id="b", id=1, at=START.replace(tzinfo=None))
