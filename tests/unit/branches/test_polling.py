from datetime import timedelta

import pytest

from git_manager.branches import BranchState, Reason
from git_manager.branches.polling import (
    ACTIVE_STATES,
    HOLD_STATES,
    READY_STATES,
    Dequeue,
    Enqueue,
    LeaveQueue,
    Observation,
    QueueAction,
    Watch,
    observe,
    poll_due,
)
from git_manager.config.models import CadenceConfig, CadenceMode
from git_manager.events import EventKind
from tests.conftest import START, make_branch, sha

# make_branch(): feature/one on main, last_base_sha sha(1), last_head_sha sha(2).
OLD_BASE, HEAD = sha(1), sha(2)
NEW_BASE, NEWER_BASE, NEW_HEAD = sha(3), sha(4), sha(5)
IMMEDIATE = CadenceConfig(mode=CadenceMode.IMMEDIATE)
DEBOUNCE = CadenceConfig(mode=CadenceMode.DEBOUNCE, debounce=timedelta(minutes=10))
MANUAL = CadenceConfig(mode=CadenceMode.MANUAL)


def remote(base: str | None = OLD_BASE, head: str | None = HEAD) -> dict[str, str]:
    refs = {"main": base, "feature/one": head}
    return {name: value for name, value in refs.items() if value is not None}


def watch(base: str | None = OLD_BASE, head: str | None = HEAD, *, minutes: int = 0) -> Watch:
    at = START + timedelta(minutes=minutes)
    return Watch(base_sha=base, head_sha=head, base_changed_at=at, polled_at=at)


def kinds(observation: Observation) -> list[EventKind]:
    return [event.kind for event in observation.events]


def test_states_are_partitioned() -> None:
    assert ACTIVE_STATES | HOLD_STATES | READY_STATES == set(BranchState)
    assert not (ACTIVE_STATES & HOLD_STATES or HOLD_STATES & READY_STATES)
    assert not ACTIVE_STATES & READY_STATES


def test_nothing_moved_changes_nothing() -> None:
    observation = observe(make_branch(), remote=remote(), watch=None, cadence=IMMEDIATE, now=START)

    assert (observation.state, observation.events, observation.queue) == (
        BranchState.IDLE,
        (),
        LeaveQueue(),
    )
    assert observation.watch == watch()


def test_immediate_schedules_on_the_detecting_poll() -> None:
    observation = observe(
        make_branch(), remote=remote(NEW_BASE), watch=watch(), cadence=IMMEDIATE, now=START
    )

    assert observation.state is BranchState.SCHEDULED
    assert observation.queue == Enqueue()
    assert kinds(observation) == [EventKind.BASE_MOVED, EventKind.STATE_CHANGED]
    assert observation.events[0].data == {"from": OLD_BASE, "to": NEW_BASE}
    assert observation.events[1].state is BranchState.SCHEDULED


def test_debounce_marks_behind_until_the_base_is_quiet() -> None:
    branch = make_branch()
    first = observe(branch, remote=remote(NEW_BASE), watch=watch(), cadence=DEBOUNCE, now=START)
    assert (first.state, first.queue) == (BranchState.BEHIND, LeaveQueue())

    behind = branch.model_copy(update={"state": BranchState.BEHIND})
    almost = observe(
        behind,
        remote=remote(NEW_BASE),
        watch=first.watch,
        cadence=DEBOUNCE,
        now=START + timedelta(minutes=9, seconds=59),
    )
    assert (almost.state, almost.events) == (BranchState.BEHIND, ())

    quiet = observe(
        behind,
        remote=remote(NEW_BASE),
        watch=almost.watch,
        cadence=DEBOUNCE,
        now=START + timedelta(minutes=10),
    )
    assert (quiet.state, quiet.queue) == (BranchState.SCHEDULED, Enqueue())


def test_debounce_restarts_when_the_base_moves_again() -> None:
    behind = make_branch(state=BranchState.BEHIND)
    moved_again = observe(
        behind,
        remote=remote(NEWER_BASE),
        watch=watch(NEW_BASE),
        cadence=DEBOUNCE,
        now=START + timedelta(minutes=8),
    )
    assert moved_again.watch.base_changed_at == START + timedelta(minutes=8)
    assert kinds(moved_again) == [EventKind.BASE_MOVED]

    later = observe(
        behind,
        remote=remote(NEWER_BASE),
        watch=moved_again.watch,
        cadence=DEBOUNCE,
        now=START + timedelta(minutes=12),
    )
    assert later.state is BranchState.BEHIND


def test_cron_waits_for_the_window() -> None:
    cadence = CadenceConfig(mode=CadenceMode.CRON, cron="0 6 * * 1-5")
    branch = make_branch()
    first = observe(branch, remote=remote(NEW_BASE), watch=watch(), cadence=cadence, now=START)
    assert first.state is BranchState.BEHIND

    next_morning = START + timedelta(hours=21)
    at_window = observe(
        branch.model_copy(update={"state": BranchState.BEHIND}),
        remote=remote(NEW_BASE),
        watch=first.watch,
        cadence=cadence,
        now=next_morning,
    )
    assert (at_window.state, at_window.queue) == (BranchState.SCHEDULED, Enqueue())


def test_manual_detects_and_never_schedules() -> None:
    observation = observe(
        make_branch(),
        remote=remote(NEW_BASE),
        watch=watch(),
        cadence=MANUAL,
        now=START + timedelta(days=30),
    )

    assert (observation.state, observation.queue) == (BranchState.BEHIND, LeaveQueue())
    assert kinds(observation) == [EventKind.BASE_MOVED, EventKind.STATE_CHANGED]


def test_scheduled_stays_scheduled_when_the_base_moves_again() -> None:
    observation = observe(
        make_branch(state=BranchState.SCHEDULED),
        remote=remote(NEWER_BASE),
        watch=watch(NEW_BASE),
        cadence=DEBOUNCE,
        now=START,
    )

    assert (observation.state, observation.queue) == (BranchState.SCHEDULED, LeaveQueue())
    assert kinds(observation) == [EventKind.BASE_MOVED]


@pytest.mark.parametrize(
    ("state", "queue"),
    [(BranchState.BEHIND, LeaveQueue()), (BranchState.SCHEDULED, Dequeue())],
)
def test_a_base_that_moves_back_cancels_the_pending_run(
    state: BranchState, queue: QueueAction
) -> None:
    observation = observe(
        make_branch(state=state),
        remote=remote(OLD_BASE),
        watch=watch(NEW_BASE),
        cadence=IMMEDIATE,
        now=START,
    )

    assert (observation.state, observation.queue) == (BranchState.IDLE, queue)


@pytest.mark.parametrize(
    ("state", "queue"),
    [
        (BranchState.IDLE, LeaveQueue()),
        (BranchState.BEHIND, LeaveQueue()),
        (BranchState.SCHEDULED, Dequeue()),
    ],
)
def test_a_deleted_base_marks_base_missing(state: BranchState, queue: QueueAction) -> None:
    observation = observe(
        make_branch(state=state),
        remote=remote(base=None),
        watch=watch(),
        cadence=IMMEDIATE,
        now=START,
    )

    assert (observation.state, observation.queue) == (BranchState.BASE_MISSING, queue)
    assert observation.events[0].data == {"from": OLD_BASE, "to": None}
    assert observation.events[1].state is BranchState.BASE_MISSING


def test_base_missing_stays_quiet_while_the_base_is_gone() -> None:
    observation = observe(
        make_branch(state=BranchState.BASE_MISSING),
        remote=remote(base=None),
        watch=watch(base=None),
        cadence=IMMEDIATE,
        now=START,
    )

    assert (observation.state, observation.events) == (BranchState.BASE_MISSING, ())


def test_a_reappearing_base_leaves_base_missing() -> None:
    missing = make_branch(state=BranchState.BASE_MISSING)
    same = observe(
        missing, remote=remote(OLD_BASE), watch=watch(None), cadence=IMMEDIATE, now=START
    )
    assert same.state is BranchState.IDLE

    moved = observe(
        missing, remote=remote(NEW_BASE), watch=watch(None), cadence=IMMEDIATE, now=START
    )
    assert (moved.state, moved.queue) == (BranchState.SCHEDULED, Enqueue())


def test_tests_failed_waits_for_a_further_base_move() -> None:
    failed = make_branch(state=BranchState.TESTS_FAILED, reason=Reason.VERIFY_FAILED)
    # The failed run tried NEW_BASE; seeing it again starts nothing.
    same = observe(
        failed, remote=remote(NEW_BASE), watch=watch(NEW_BASE), cadence=IMMEDIATE, now=START
    )
    assert (same.state, same.reason, same.queue) == (
        BranchState.TESTS_FAILED,
        Reason.VERIFY_FAILED,
        LeaveQueue(),
    )

    moved = observe(
        failed, remote=remote(NEWER_BASE), watch=watch(NEW_BASE), cadence=IMMEDIATE, now=START
    )
    assert (moved.state, moved.reason, moved.queue) == (BranchState.SCHEDULED, None, Enqueue())


def test_tests_failed_after_a_restart_does_not_rerun() -> None:
    failed = make_branch(state=BranchState.TESTS_FAILED)

    observation = observe(failed, remote=remote(NEW_BASE), watch=None, cadence=IMMEDIATE, now=START)

    assert (observation.state, observation.queue) == (BranchState.TESTS_FAILED, LeaveQueue())


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (BranchState.NEEDS_HUMAN, Reason.CONFLICT),
        (BranchState.NEEDS_CONFIG, Reason.MISSING_COMMANDS),
        (BranchState.DIVERGED_REMOTE, Reason.LEASE_REJECTED),
        (BranchState.PAUSED, Reason.PAUSED_BY_USER),
    ],
)
def test_a_base_change_in_a_stop_state_is_recorded_without_a_run(
    state: BranchState, reason: Reason
) -> None:
    branch = make_branch(state=state, reason=reason)

    observation = observe(
        branch, remote=remote(NEW_BASE), watch=watch(), cadence=IMMEDIATE, now=START
    )

    assert (observation.state, observation.reason, observation.queue) == (
        state,
        reason,
        LeaveQueue(),
    )
    assert kinds(observation) == [EventKind.BASE_MOVED]
    assert observation.watch.base_sha == NEW_BASE


def test_a_deleted_base_in_a_stop_state_is_only_recorded() -> None:
    observation = observe(
        make_branch(state=BranchState.PAUSED),
        remote=remote(base=None),
        watch=watch(),
        cadence=IMMEDIATE,
        now=START,
    )

    assert (observation.state, kinds(observation)) == (BranchState.PAUSED, [EventKind.BASE_MOVED])


def test_a_stop_state_left_by_a_human_picks_up_the_recorded_change() -> None:
    # Recorded while needs_human 30 minutes ago; resumed to idle since.
    recorded = Watch(base_sha=NEW_BASE, head_sha=HEAD, base_changed_at=START, polled_at=START)

    observation = observe(
        make_branch(),
        remote=remote(NEW_BASE),
        watch=recorded,
        cadence=DEBOUNCE,
        now=START + timedelta(minutes=30),
    )

    assert (observation.state, observation.queue) == (BranchState.SCHEDULED, Enqueue())
    assert kinds(observation) == [EventKind.STATE_CHANGED]


@pytest.mark.parametrize("state", sorted(ACTIVE_STATES))
def test_during_a_run_moves_are_reported_only(state: BranchState) -> None:
    observation = observe(
        make_branch(state=state),
        remote=remote(NEW_BASE, NEW_HEAD),
        watch=watch(),
        cadence=IMMEDIATE,
        now=START,
    )

    assert (observation.state, observation.queue) == (state, LeaveQueue())
    assert kinds(observation) == [EventKind.BASE_MOVED, EventKind.HEAD_MOVED]
    assert observation.events[1].data == {"from": HEAD, "to": NEW_HEAD}


def test_feature_branch_movement_is_reported_once() -> None:
    branch = make_branch()
    first = observe(branch, remote=remote(head=NEW_HEAD), watch=None, cadence=IMMEDIATE, now=START)
    assert kinds(first) == [EventKind.HEAD_MOVED]
    assert first.state is BranchState.IDLE

    again = observe(
        branch, remote=remote(head=NEW_HEAD), watch=first.watch, cadence=IMMEDIATE, now=START
    )
    assert again.events == ()


def test_a_deleted_feature_branch_is_reported_and_never_scheduled() -> None:
    observation = observe(
        make_branch(),
        remote=remote(NEW_BASE, head=None),
        watch=watch(),
        cadence=IMMEDIATE,
        now=START,
    )

    assert (observation.state, observation.queue) == (BranchState.IDLE, LeaveQueue())
    assert observation.events[1].data == {"from": HEAD, "to": None}


def test_first_poll_after_a_restart_counts_the_change_from_now() -> None:
    later = START + timedelta(hours=1)

    observation = observe(
        make_branch(), remote=remote(NEW_BASE), watch=None, cadence=DEBOUNCE, now=later
    )

    assert observation.state is BranchState.BEHIND
    assert observation.watch.base_changed_at == later
    assert kinds(observation) == [EventKind.BASE_MOVED, EventKind.STATE_CHANGED]


def test_poll_due_after_the_interval() -> None:
    last = watch()
    interval = timedelta(seconds=60)

    assert poll_due(None, interval=interval, now=START)
    assert not poll_due(last, interval=interval, now=START + timedelta(seconds=59))
    assert poll_due(last, interval=interval, now=START + timedelta(seconds=60))


def test_tests_failed_stays_when_the_base_moves_back() -> None:
    observation = observe(
        make_branch(state=BranchState.TESTS_FAILED),
        remote=remote(OLD_BASE),
        watch=watch(NEW_BASE),
        cadence=IMMEDIATE,
        now=START,
    )

    assert (observation.state, observation.queue) == (BranchState.TESTS_FAILED, LeaveQueue())
