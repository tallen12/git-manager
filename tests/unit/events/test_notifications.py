import logging
from collections.abc import AsyncIterator

import pytest

from git_manager.branches import BranchState, Reason
from git_manager.config.models import NotifyConfig, NotifyOn
from git_manager.events import Event, EventKind, Notification
from git_manager.events.notifications import (
    NOTIFICATION_TITLE,
    forward_notifications,
    notification_filter,
    notification_for,
    notification_topics,
    should_notify,
)
from tests.conftest import START, RecordingNotifier


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


@pytest.mark.parametrize(
    ("happened", "message"),
    [
        (event(EventKind.PUSHED), "branch b: pushed"),
        (
            event(EventKind.STATE_CHANGED, state=BranchState.NEEDS_HUMAN, reason=Reason.CONFLICT),
            "branch b: needs_human (conflict)",
        ),
        (event(EventKind.STATE_CHANGED, state=BranchState.BASE_MISSING), "branch b: base_missing"),
        (event(EventKind.TRACKED), "branch b: tracked"),
    ],
)
def test_notification_names_the_branch_and_what_happened(happened: Event, message: str) -> None:
    assert notification_for(happened) == Notification(title=NOTIFICATION_TITLE, message=message)


async def events_of(*events: Event) -> AsyncIterator[Event]:
    for item in events:
        yield item


async def test_forwarding_shows_only_the_events_notify_on_selects() -> None:
    notifier = RecordingNotifier()
    pushed = event(EventKind.PUSHED)
    failed = event(EventKind.STATE_CHANGED, state=BranchState.TESTS_FAILED)

    await forward_notifications(
        events_of(event(EventKind.RUN_STARTED), pushed, failed),
        notifier=notifier,
        on=[NotifyOn.PUSHED],
    )

    assert notifier.shown == [notification_for(pushed)]


async def test_a_failed_notification_is_logged_and_the_rest_still_shown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    notifier = RecordingNotifier(failing=True)
    first = event(EventKind.PUSHED)

    async def flaky() -> AsyncIterator[Event]:
        yield first
        notifier.failing = False
        yield first.model_copy(update={"id": 2})

    with caplog.at_level(logging.WARNING):
        await forward_notifications(flaky(), notifier=notifier, on=tuple(NotifyOn))

    assert len(notifier.shown) == 1
    assert "event 1" in caplog.text
