import asyncio

import pytest

from git_manager.branches import BranchState, Reason, TrackedBranch
from git_manager.branches.protocols import BranchOperations
from git_manager.branches.results import SyncCompleted
from git_manager.branches.service import resume_refusal
from git_manager.errors import ConflictError, NotFoundError
from git_manager.events import EventKind
from tests.conftest import make_branch, sha
from tests.unit.branches.conftest import FORK, HEAD, URL, BranchHarness


def tracked(harness: BranchHarness, **overrides: object) -> TrackedBranch:
    """Store ``feature/one`` (id ``branch-1``) and return it."""
    branch = make_branch(**overrides)
    harness.branches.rows[branch.id] = branch
    return branch


def test_service_implements_branch_operations(harness: BranchHarness) -> None:
    operations: BranchOperations = harness.service
    assert operations is harness.service


async def test_status_lists_the_repo_and_its_branches(harness: BranchHarness) -> None:
    branch = tracked(harness)

    status = await harness.service.status()

    assert (status.repo_id, status.url, status.branches) == ("repo", URL, (branch,))


async def test_track_starts_from_the_merge_base(harness: BranchHarness) -> None:
    branch = await harness.service.track(name="feature/one", base="main")

    assert branch == TrackedBranch(
        id="branch-1",
        repo_id="repo",
        name="feature/one",
        base="main",
        fork_point=FORK,
        last_base_sha=FORK,
        last_head_sha=HEAD,
    )
    assert harness.branches.rows["branch-1"] == branch
    assert harness.git.fetched == [("main", "feature/one")]
    [event] = harness.events.events
    assert (event.kind, event.branch_id, event.data) == (
        EventKind.TRACKED,
        "branch-1",
        {"base": "main"},
    )


async def test_track_refuses_a_tracked_branch(harness: BranchHarness) -> None:
    tracked(harness)

    with pytest.raises(ConflictError, match="already tracked: feature/one"):
        await harness.service.track(name="feature/one", base="main")


@pytest.mark.parametrize("missing", ["main", "feature/one"])
async def test_track_needs_both_branches_on_the_remote(
    harness: BranchHarness, missing: str
) -> None:
    del harness.git.remote[missing]

    with pytest.raises(NotFoundError, match=f"remote branch not found: {missing}"):
        await harness.service.track(name="feature/one", base="main")

    assert harness.branches.rows == {}
    assert harness.git.fetched == []


async def test_untrack_removes_the_branch_by_name_or_id(harness: BranchHarness) -> None:
    tracked(harness)
    await harness.service.untrack("feature/one")
    tracked(harness)
    await harness.service.untrack("branch-1")

    assert harness.branches.rows == {}
    assert [event.kind for event in harness.events.events] == [EventKind.UNTRACKED] * 2


async def test_unknown_branches_are_not_found(harness: BranchHarness) -> None:
    for call in (
        harness.service.untrack,
        harness.service.sync,
        harness.service.pause,
        harness.service.resume,
    ):
        with pytest.raises(NotFoundError, match="branch not found: feature/x"):
            await call("feature/x")


async def test_sync_hands_the_branch_to_the_syncer(harness: BranchHarness) -> None:
    branch = tracked(harness, state=BranchState.NEEDS_HUMAN)

    outcome = await harness.service.sync("feature/one")

    assert isinstance(outcome, SyncCompleted)
    assert harness.syncer.synced == [branch]


async def test_sync_refuses_a_paused_branch(harness: BranchHarness) -> None:
    tracked(harness, state=BranchState.PAUSED, reason=Reason.PAUSED_BY_USER)

    with pytest.raises(ConflictError, match="paused; resume it first"):
        await harness.service.sync("feature/one")

    assert harness.syncer.synced == []


async def test_pause_keeps_everything_but_the_state(harness: BranchHarness) -> None:
    branch = tracked(harness, state=BranchState.TESTS_FAILED, reason=Reason.VERIFY_FAILED)

    paused = await harness.service.pause("feature/one")

    assert paused == branch.model_copy(
        update={"state": BranchState.PAUSED, "reason": Reason.PAUSED_BY_USER}
    )
    assert harness.branches.rows["branch-1"] == paused
    [event] = harness.events.events
    assert (event.kind, event.state, event.reason) == (
        EventKind.STATE_CHANGED,
        BranchState.PAUSED,
        Reason.PAUSED_BY_USER,
    )


async def test_pausing_a_paused_branch_changes_nothing(harness: BranchHarness) -> None:
    branch = tracked(harness, state=BranchState.PAUSED, reason=Reason.MAX_RESTARTS)

    assert await harness.service.pause("feature/one") == branch
    assert harness.events.events == []


async def test_pause_refuses_a_branch_awaiting_approval(harness: BranchHarness) -> None:
    tracked(harness, state=BranchState.AWAITING_APPROVAL)

    with pytest.raises(ConflictError, match="awaiting approval"):
        await harness.service.pause("feature/one")


async def test_pause_waits_for_a_run_and_sees_its_result(harness: BranchHarness) -> None:
    tracked(harness, state=BranchState.REBASING)
    async with harness.locks.hold("branch-1"):
        pausing = asyncio.create_task(harness.service.pause("feature/one"))
        await asyncio.sleep(0)
        assert not pausing.done()
        # The run ends while pause waits for the lock.
        harness.branches.rows["branch-1"] = make_branch(last_head_sha=sha(9))

    paused = await pausing

    assert (paused.state, paused.last_head_sha) == (BranchState.PAUSED, sha(9))


@pytest.mark.parametrize(
    "state", [BranchState.PAUSED, BranchState.NEEDS_HUMAN, BranchState.DIVERGED_REMOTE]
)
async def test_resume_starts_again_from_the_remote_branch(
    harness: BranchHarness, state: BranchState
) -> None:
    tracked(
        harness,
        state=state,
        reason=Reason.LEASE_REJECTED,
        fork_point=sha(7),
        last_base_sha=sha(7),
        last_head_sha=sha(8),
    )

    resumed = await harness.service.resume("feature/one")

    assert (resumed.state, resumed.reason) == (BranchState.IDLE, None)
    assert (resumed.fork_point, resumed.last_base_sha, resumed.last_head_sha) == (
        FORK,
        FORK,
        HEAD,
    )
    assert harness.branches.rows["branch-1"] == resumed
    [event] = harness.events.events
    assert (event.kind, event.state) == (EventKind.STATE_CHANGED, BranchState.IDLE)


async def test_resume_names_the_way_out_of_other_states(harness: BranchHarness) -> None:
    branch = tracked(harness, state=BranchState.NEEDS_CONFIG, reason=Reason.MISSING_COMMANDS)

    with pytest.raises(ConflictError, match=r"cannot resume feature/one: .*config"):
        await harness.service.resume("feature/one")

    assert harness.branches.rows["branch-1"] == branch
    assert harness.events.events == []


async def test_resume_keeps_the_state_when_the_branch_left_the_remote(
    harness: BranchHarness,
) -> None:
    branch = tracked(harness, state=BranchState.PAUSED)
    del harness.git.remote["feature/one"]

    with pytest.raises(NotFoundError, match="remote branch not found: feature/one"):
        await harness.service.resume("feature/one")

    assert harness.branches.rows["branch-1"] == branch


@pytest.mark.parametrize("state", list(BranchState))
def test_resume_refusal_follows_the_leaving_stop_states_table(state: BranchState) -> None:
    resumable = {BranchState.PAUSED, BranchState.NEEDS_HUMAN, BranchState.DIVERGED_REMOTE}

    assert (resume_refusal(state) is None) == (state in resumable)
