import pytest

from git_manager.branches import BranchState, Reason
from git_manager.config.models import NotifyConfig, NotifyOn
from git_manager.events import Event, EventKind
from git_manager.events.notifications import (
    notification_filter,
    notification_topics,
    should_notify,
)
from tests.conftest import START


def event(
    kind: EventKind,
    *,
    state: BranchState | None = None,
    reason: Reason | None = None,
) -> Event:
    return Event(id=1, at=START, kind=kind, branch_id="b", state=state, reason=reason)


@pytest.mark.parametrize(
    ("state", "topic"),
    [
        (BranchState.AWAITING_APPROVAL, NotifyOn.AWAITING_APPROVAL),
        (BranchState.NEEDS_HUMAN, NotifyOn.NEEDS_HUMAN),
        (BranchState.NEEDS_CONFIG, NotifyOn.NEEDS_CONFIG),
        (BranchState.TESTS_FAILED, NotifyOn.TESTS_FAILED),
        (BranchState.BASE_MISSING, NotifyOn.BASE_MISSING),
        (BranchState.STACK_PARTIAL_PUSH, NotifyOn.STACK_PARTIAL_PUSH),
        (BranchState.WAITING_BUDGET, NotifyOn.WAITING_BUDGET),
        (BranchState.WAITING_QUOTA, NotifyOn.WAITING_QUOTA),
    ],
)
def test_state_changes_match_their_new_state(state: BranchState, topic: NotifyOn) -> None:
    assert notification_topics(event(EventKind.STATE_CHANGED, state=state)) == {topic}


@pytest.mark.parametrize(
    "state",
    [BranchState.IDLE, BranchState.BEHIND, BranchState.SCHEDULED, BranchState.REBASING],
)
def test_routine_states_never_notify(state: BranchState) -> None:
    assert notification_topics(event(EventKind.STATE_CHANGED, state=state)) == frozenset()


def test_a_push_matches_pushed() -> None:
    assert notification_topics(event(EventKind.PUSHED)) == {NotifyOn.PUSHED}


@pytest.mark.parametrize(
    "kind",
    [
        EventKind.TRACKED,
        EventKind.UNTRACKED,
        EventKind.RUN_STARTED,
        EventKind.RUN_FINISHED,
        EventKind.BASE_MOVED,
        EventKind.HEAD_MOVED,
    ],
)
def test_other_kinds_never_notify(kind: EventKind) -> None:
    assert notification_topics(event(kind, state=BranchState.NEEDS_HUMAN)) == frozenset()


def test_a_reason_without_a_topic_adds_nothing() -> None:
    # Reasons match by name too (``stack_removed`` arrives as a reason with stacks in M4).
    matched = notification_topics(
        event(EventKind.STATE_CHANGED, state=BranchState.NEEDS_HUMAN, reason=Reason.CONFLICT)
    )

    assert matched == {NotifyOn.NEEDS_HUMAN}


def test_should_notify_respects_notify_on() -> None:
    needs_human = event(EventKind.STATE_CHANGED, state=BranchState.NEEDS_HUMAN)

    assert should_notify(needs_human, [NotifyOn.NEEDS_HUMAN, NotifyOn.PUSHED])
    assert not should_notify(needs_human, [NotifyOn.PUSHED])
    assert not should_notify(needs_human, [])


def test_default_notify_on_accepts_every_topic() -> None:
    accept = notification_filter(NotifyConfig().on)

    assert accept(event(EventKind.PUSHED))
    assert accept(event(EventKind.STATE_CHANGED, state=BranchState.BASE_MISSING))
    assert not accept(event(EventKind.RUN_STARTED))


def test_filter_is_a_subscription_predicate() -> None:
    accept = notification_filter([NotifyOn.PUSHED])

    assert accept(event(EventKind.PUSHED))
    assert not accept(event(EventKind.STATE_CHANGED, state=BranchState.TESTS_FAILED))
