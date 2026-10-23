"""Records written to a ``state.db`` file read back exactly after reopening it."""

from datetime import timedelta, timezone
from pathlib import Path

from git_manager.branches import BranchHeads, BranchState, Reason
from git_manager.events import EventDraft, EventKind
from git_manager.store import (
    SqlBranchRepository,
    SqlEventRepository,
    SqlRunRepository,
    open_database,
    state_db_path,
)
from tests.conftest import START, make_branch, make_run, sha


async def test_records_round_trip_through_the_file(tmp_path: Path) -> None:
    path = state_db_path(tmp_path)
    branch = make_branch(state=BranchState.DIVERGED_REMOTE, reason=Reason.LEASE_REJECTED)
    run = make_run(
        heads=(BranchHeads(branch="feature/one", old_head=sha(2)),),
        started_at=START.astimezone(timezone(timedelta(hours=9))),
        finished_at=None,
    )
    draft = EventDraft(kind=EventKind.PUSHED, branch_id=branch.id, data={"head": sha(4)})

    async with open_database(path) as database:
        await SqlBranchRepository(database).add(branch)
        await SqlRunRepository(database).add(run)
        event = await SqlEventRepository(database).append(draft, at=START)

    async with open_database(path) as database:
        assert await SqlBranchRepository(database).list() == [branch]
        assert await SqlRunRepository(database).get(run.id) == run
        assert await SqlEventRepository(database).list() == [event]


async def test_event_ids_continue_after_reopening(tmp_path: Path) -> None:
    path = state_db_path(tmp_path)
    draft = EventDraft(kind=EventKind.TRACKED, branch_id="b")

    async with open_database(path) as database:
        await SqlEventRepository(database).append(draft, at=START)
    async with open_database(path) as database:
        second = await SqlEventRepository(database).append(draft, at=START)

    assert second.id == 2
