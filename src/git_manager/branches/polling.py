"""What one poll of a branch means: a pure function from remote hashes to a decision.

The poller remembers what it last saw of each branch in a ``Watch``. That memory lives
in the process: after a restart the first poll counts any base change as made then.

Git Manager's own pushes are not human pushes: a run records the head it pushed as
``last_head_sha``, so a remote head that matches a ``last_head_sha`` changed since the
previous poll is ours and is not reported as ``head_moved``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import assert_never

from pydantic import JsonValue

from git_manager.branches.cadence import DetectOnly, RunAt, cadence_decision
from git_manager.branches.models import BranchState, CommitSha, Reason, TrackedBranch
from git_manager.config.models import CadenceConfig
from git_manager.events.models import EventDraft, EventKind
from git_manager.rebasing.models import RunTrigger

# A run owns the branch: polling only reports what moved.
ACTIVE_STATES = frozenset(
    {
        BranchState.RETARGETING,
        BranchState.REBASING,
        BranchState.RESOLVING,
        BranchState.VERIFYING,
        BranchState.AWAITING_APPROVAL,
        BranchState.PUSHING,
    }
)

# Stop states another action leaves ("Leaving stop states" in the spec): a base change
# is recorded but starts no run, so a stuck branch does not burn the Claude budget.
HOLD_STATES = frozenset(
    {
        BranchState.NEEDS_HUMAN,
        BranchState.NEEDS_CONFIG,
        BranchState.DIVERGED_REMOTE,
        BranchState.PAUSED,
        BranchState.STACK_PARTIAL_PUSH,
        BranchState.WAITING_BUDGET,
        BranchState.WAITING_QUOTA,
    }
)


def may_start(state: BranchState, trigger: RunTrigger) -> bool:
    """Whether a run with ``trigger`` may start on a branch in ``state``.

    A branch can enter a hold state while its run waits in the queue (a human pauses it,
    or another run stopped it), so the runner asks again once it holds the branch lock.
    A poll never starts a run on a held branch; a human action (``sync``, ``retry``,
    ``retarget``) is how a branch leaves most hold states, so only ``paused`` blocks it.
    """
    match trigger:
        case RunTrigger.POLL:
            return state not in HOLD_STATES
        case RunTrigger.MANUAL | RunTrigger.RETRY | RunTrigger.RETARGET:
            return state is not BranchState.PAUSED
        case _:
            assert_never(trigger)


# States the poller moves between: a base change may (re)schedule a run from here.
READY_STATES = frozenset(
    {
        BranchState.IDLE,
        BranchState.BEHIND,
        BranchState.SCHEDULED,
        BranchState.TESTS_FAILED,
        BranchState.BASE_MISSING,
    }
)


@dataclass(frozen=True, slots=True)
class Watch:
    """What the poller last saw of one branch on the remote (``None``: not there)."""

    base_sha: CommitSha | None
    head_sha: CommitSha | None
    # When the remote base first showed ``base_sha``: the start of the quiet period.
    base_changed_at: datetime
    polled_at: datetime
    # The branch's ``last_head_sha`` at that poll; a change since means a run pushed.
    recorded_head_sha: CommitSha


@dataclass(frozen=True, slots=True)
class Enqueue:
    """Put the branch in the run queue."""


@dataclass(frozen=True, slots=True)
class Dequeue:
    """Take the branch's waiting run out of the queue."""


@dataclass(frozen=True, slots=True)
class LeaveQueue:
    """Leave the queue as it is."""


type QueueAction = Enqueue | Dequeue | LeaveQueue


@dataclass(frozen=True, slots=True)
class Observation:
    """The outcome of one poll: what to remember, record and do."""

    watch: Watch
    state: BranchState
    reason: Reason | None
    events: tuple[EventDraft, ...]
    queue: QueueAction


def _moved(
    kind: EventKind, branch: TrackedBranch, before: CommitSha | None, after: CommitSha | None
) -> EventDraft:
    data: dict[str, JsonValue] = {"from": before, "to": after}
    return EventDraft(kind=kind, branch_id=branch.id, data=data)


def _ready_target(
    branch: TrackedBranch,
    *,
    base: CommitSha | None,
    base_is_new: bool,
    base_changed_at: datetime,
    cadence: CadenceConfig,
    now: datetime,
) -> tuple[BranchState, QueueAction]:
    # Only a scheduled branch has a waiting run to cancel.
    cancel: QueueAction = Dequeue() if branch.state is BranchState.SCHEDULED else LeaveQueue()
    if base is None:
        return BranchState.BASE_MISSING, cancel
    if base == branch.last_base_sha:
        # Nothing to rebase onto; a base that moved back cancels a pending run.
        if branch.state is BranchState.TESTS_FAILED:
            return BranchState.TESTS_FAILED, LeaveQueue()
        return BranchState.IDLE, cancel
    if branch.state is BranchState.TESTS_FAILED and not base_is_new:
        # The failed run already tried this base; only a further move starts a new one.
        return BranchState.TESTS_FAILED, LeaveQueue()
    if branch.state is BranchState.SCHEDULED:
        # The run fetches the base when it starts, so later moves ride along.
        return BranchState.SCHEDULED, LeaveQueue()
    match cadence_decision(cadence, base_changed_at=base_changed_at):
        case DetectOnly():
            return BranchState.BEHIND, LeaveQueue()
        case RunAt(at=at) if at <= now:
            return BranchState.SCHEDULED, Enqueue()
        case RunAt():
            return BranchState.BEHIND, LeaveQueue()
        case unreachable:
            assert_never(unreachable)


def observe(
    branch: TrackedBranch,
    *,
    remote: Mapping[str, CommitSha],
    watch: Watch | None,
    cadence: CadenceConfig,
    now: datetime,
) -> Observation:
    """Decide what one poll of ``branch`` means, given ``ls-remote`` of its base and itself.

    Base movement is measured against ``last_base_sha`` (what the branch sits on) and
    reported once per new hash; feature-branch movement is reported once per new hash
    against ``last_head_sha``, except a push of Git Manager's own (see the module doc).
    Only ready states change state or touch the queue, and only while the feature branch
    exists on the remote.
    """
    base = remote.get(branch.base)
    head = remote.get(branch.name)
    seen_base = watch.base_sha if watch is not None else branch.last_base_sha
    seen_head = watch.head_sha if watch is not None else branch.last_head_sha
    base_is_new = watch is not None and base != watch.base_sha
    base_changed_at = watch.base_changed_at if watch is not None and not base_is_new else now
    new_watch = Watch(
        base_sha=base,
        head_sha=head,
        base_changed_at=base_changed_at,
        polled_at=now,
        recorded_head_sha=branch.last_head_sha,
    )
    own_push = (
        watch is not None
        and branch.last_head_sha != watch.recorded_head_sha
        and head == branch.last_head_sha
    )

    events: list[EventDraft] = []
    if base != seen_base:
        events.append(_moved(EventKind.BASE_MOVED, branch, seen_base, base))
    if head != seen_head and not own_push:
        events.append(_moved(EventKind.HEAD_MOVED, branch, seen_head, head))

    state, reason, queue = branch.state, branch.reason, LeaveQueue()
    if branch.state in READY_STATES and head is not None:
        state, queue = _ready_target(
            branch,
            base=base,
            base_is_new=base_is_new,
            base_changed_at=base_changed_at,
            cadence=cadence,
            now=now,
        )
        if state is not branch.state:
            reason = None
            events.append(
                EventDraft(kind=EventKind.STATE_CHANGED, branch_id=branch.id, state=state)
            )
    return Observation(
        watch=new_watch, state=state, reason=reason, events=tuple(events), queue=queue
    )


def poll_due(watch: Watch | None, *, interval: timedelta, now: datetime) -> bool:
    """Whether a branch last polled per ``watch`` is due again after ``interval``."""
    return watch is None or now - watch.polled_at >= interval
