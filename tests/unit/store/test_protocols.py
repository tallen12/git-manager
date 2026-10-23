"""The store protocol contract, run against every implementation (see ``conftest``)."""

from datetime import timedelta, timezone

import pytest

from git_manager.approvals.models import Actor, ActorType
from git_manager.branches import BranchHeads, BranchState, Reason
from git_manager.core import ConflictError, NotFoundError
from git_manager.events import EventDraft, EventKind
from git_manager.rebasing import RunTrigger
from git_manager.store import BranchRepository, EventRepository, RunRepository
from git_manager.verification.models import (
    CommandSource,
    StepOutcome,
    TestResult,
    VerifyCommands,
    VerifyStep,
)
from tests.conftest import START, make_branch, make_run, sha


async def test_branch_repository_round_trip(branches: BranchRepository) -> None:
    branch = make_branch()

    await branches.add(branch)
    await branches.update(branch.model_copy(update={"state": BranchState.PAUSED}))

    stored = await branches.find("feature/one")
    assert stored is not None
    assert stored.state is BranchState.PAUSED
    assert await branches.get(branch.id) == stored


async def test_branch_round_trips_every_field(branches: BranchRepository) -> None:
    branch = make_branch(
        fork_point=sha(7),
        last_base_sha="ab" * 32,
        state=BranchState.NEEDS_HUMAN,
        reason=Reason.REWRITTEN_BASE,
    )

    await branches.add(branch)

    assert await branches.get(branch.id) == branch
    assert await branches.list() == [branch]


async def test_unknown_branches_are_absent(branches: BranchRepository) -> None:
    assert await branches.get("nope") is None
    assert await branches.find("nope") is None
    assert await branches.list() == []


async def test_branch_names_are_unique(branches: BranchRepository) -> None:
    await branches.add(make_branch(id="a"))

    with pytest.raises(ConflictError):
        await branches.add(make_branch(id="b"))


async def test_branch_ids_are_unique(branches: BranchRepository) -> None:
    await branches.add(make_branch(id="a", name="one"))

    with pytest.raises(ConflictError):
        await branches.add(make_branch(id="a", name="two"))
    assert [branch.name for branch in await branches.list()] == ["one"]


async def test_branches_are_listed_by_name(branches: BranchRepository) -> None:
    await branches.add(make_branch(id="z", name="zeta"))
    await branches.add(make_branch(id="a", name="alpha"))

    assert [branch.name for branch in await branches.list()] == ["alpha", "zeta"]


async def test_removing_a_branch_forgets_it(branches: BranchRepository) -> None:
    branch = make_branch()
    await branches.add(branch)

    await branches.remove(branch.id)

    assert await branches.get(branch.id) is None
    assert await branches.find(branch.name) is None
    await branches.add(branch)


async def test_changing_a_missing_branch_is_not_found(branches: BranchRepository) -> None:
    with pytest.raises(NotFoundError):
        await branches.update(make_branch())
    with pytest.raises(NotFoundError):
        await branches.remove("branch-1")


async def test_runs_are_listed_newest_first_and_filtered_by_branch(runs: RunRepository) -> None:
    for run_id, branch_id in [("r1", "a"), ("r2", "b"), ("r3", "a")]:
        await runs.add(make_run(id=run_id, branch_id=branch_id))

    assert [run.id for run in await runs.list()] == ["r3", "r2", "r1"]
    assert [run.id for run in await runs.list(branch_id="a", limit=1)] == ["r3"]
    assert await runs.list(branch_id="none") == []


async def test_run_round_trips_every_field(runs: RunRepository) -> None:
    run = make_run(
        trigger=RunTrigger.RETRY,
        heads=(
            BranchHeads(branch="feature/one", old_head=sha(2), new_head=sha(4)),
            BranchHeads(branch="feature/two", old_head=sha(5)),
        ),
        rewritten_base=True,
        restarts=2,
        commands=VerifyCommands(
            setup="just setup",
            test="just test",
            source=CommandSource.AGENTS_MD,
            source_hash="abc",
            confirmed_by=Actor(type=ActorType.HUMAN_CLI, identity="tyler"),
        ),
        tests=(
            TestResult(
                step=VerifyStep.TEST,
                command="just test",
                outcome=StepOutcome.TIMED_OUT,
                exit_code=None,
                attempts=2,
                duration_s=12.25,
                output_tail="line one\nüñí ✓\n",
                junit_xml="<testsuite/>",
            ),
        ),
        outcome=BranchState.TESTS_FAILED,
        reason=Reason.VERIFY_FAILED,
        started_at=START.astimezone(timezone(timedelta(hours=-5))),
        finished_at=None,
    )

    await runs.add(run)

    assert await runs.get(run.id) == run
    assert await runs.list() == [run]


async def test_run_ids_are_unique(runs: RunRepository) -> None:
    await runs.add(make_run())

    with pytest.raises(ConflictError):
        await runs.add(make_run(branch_id="other"))


async def test_updating_a_run_replaces_it(runs: RunRepository) -> None:
    run = make_run(outcome=BranchState.REBASING, finished_at=None)
    await runs.add(run)
    finished = run.model_copy(update={"outcome": BranchState.IDLE, "finished_at": START})

    await runs.update(finished)

    assert await runs.get(run.id) == finished
    assert await runs.list() == [finished]


async def test_updating_a_missing_run_is_not_found(runs: RunRepository) -> None:
    assert await runs.get("run-1") is None
    with pytest.raises(NotFoundError):
        await runs.update(make_run())


async def test_events_get_increasing_ids_from_one(events: EventRepository) -> None:
    draft = EventDraft(
        kind=EventKind.STATE_CHANGED,
        branch_id="b",
        run_id="r",
        state=BranchState.TESTS_FAILED,
        reason=Reason.VERIFY_FAILED,
        data={"attempts": 2, "steps": ["test", None], "nested": {"ok": False, "s": 1.5}},
    )

    first = await events.append(draft, at=START)
    second = await events.append(draft, at=START + timedelta(seconds=1))

    assert (first.id, second.id) == (1, 2)
    assert first.model_dump(exclude={"id", "at"}) == draft.model_dump()
    assert first.at == START
    assert await events.list() == [first, second]


async def test_events_resume_after_the_last_id_seen(events: EventRepository) -> None:
    for kind in [EventKind.TRACKED, EventKind.RUN_STARTED, EventKind.PUSHED]:
        await events.append(EventDraft(kind=kind, branch_id="b"), at=START)

    assert [event.kind for event in await events.list(after=1)] == [
        EventKind.RUN_STARTED,
        EventKind.PUSHED,
    ]
    assert [event.id for event in await events.list(limit=2)] == [1, 2]
    assert await events.list(after=3) == []
