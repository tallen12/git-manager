import pytest

from git_manager.branches import BranchState
from git_manager.core import ConflictError, NotFoundError
from git_manager.events import EventDraft, EventKind
from git_manager.store import BranchRepository, EventRepository, RunRepository
from tests.conftest import (
    START,
    InMemoryBranches,
    InMemoryEvents,
    InMemoryRuns,
    make_branch,
    make_run,
)


async def test_branch_repository_round_trip() -> None:
    branches: BranchRepository = InMemoryBranches()
    branch = make_branch()

    await branches.add(branch)
    await branches.update(branch.model_copy(update={"state": BranchState.PAUSED}))

    stored = await branches.find("feature/one")
    assert stored is not None
    assert stored.state is BranchState.PAUSED
    assert await branches.get(branch.id) == stored


async def test_branch_names_are_unique() -> None:
    branches: BranchRepository = InMemoryBranches()
    await branches.add(make_branch(id="a"))

    with pytest.raises(ConflictError):
        await branches.add(make_branch(id="b"))


async def test_branches_are_listed_by_name() -> None:
    branches: BranchRepository = InMemoryBranches()
    await branches.add(make_branch(id="z", name="zeta"))
    await branches.add(make_branch(id="a", name="alpha"))

    assert [branch.name for branch in await branches.list()] == ["alpha", "zeta"]


async def test_changing_a_missing_branch_is_not_found() -> None:
    branches: BranchRepository = InMemoryBranches()

    with pytest.raises(NotFoundError):
        await branches.update(make_branch())
    with pytest.raises(NotFoundError):
        await branches.remove("branch-1")


async def test_runs_are_listed_newest_first_and_filtered_by_branch() -> None:
    runs: RunRepository = InMemoryRuns()
    for run_id, branch_id in [("r1", "a"), ("r2", "b"), ("r3", "a")]:
        await runs.add(make_run(id=run_id, branch_id=branch_id))

    assert [run.id for run in await runs.list()] == ["r3", "r2", "r1"]
    assert [run.id for run in await runs.list(branch_id="a", limit=1)] == ["r3"]


async def test_updating_a_missing_run_is_not_found() -> None:
    runs: RunRepository = InMemoryRuns()

    with pytest.raises(NotFoundError):
        await runs.update(make_run())


async def test_events_resume_after_the_last_id_seen() -> None:
    events: EventRepository = InMemoryEvents()
    for kind in [EventKind.TRACKED, EventKind.RUN_STARTED, EventKind.PUSHED]:
        await events.append(EventDraft(kind=kind, branch_id="b"), at=START)

    assert [event.kind for event in await events.list(after=1)] == [
        EventKind.RUN_STARTED,
        EventKind.PUSHED,
    ]
