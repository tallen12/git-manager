"""SQLite-only behavior; the shared contract is in ``test_protocols``."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from git_manager.core import ConflictError
from git_manager.events import EventDraft, EventKind
from git_manager.store import (
    Database,
    SqlBranchRepository,
    SqlEventRepository,
    SqlRunRepository,
)
from git_manager.store.repositories import _microseconds
from tests.conftest import START, make_branch, make_run


def test_microseconds_are_exact_for_any_offset() -> None:
    utc = datetime(2026, 1, 5, 9, 0, 0, 123456, tzinfo=UTC)
    shifted = utc.astimezone(timezone(timedelta(hours=5, minutes=30)))

    assert _microseconds(utc) == _microseconds(shifted)
    assert _microseconds(datetime(1970, 1, 1, tzinfo=UTC)) == 0
    assert _microseconds(utc + timedelta(microseconds=1)) == _microseconds(utc) + 1


async def test_runs_are_ordered_by_start_time_not_insertion(database: Database) -> None:
    runs = SqlRunRepository(database)
    await runs.add(make_run(id="late", started_at=START + timedelta(hours=1)))
    await runs.add(make_run(id="early", started_at=START))
    # Earlier wall-clock time, but a later instant than ``early``.
    await runs.add(
        make_run(
            id="middle",
            started_at=(START + timedelta(minutes=30)).astimezone(timezone(timedelta(hours=-8))),
        )
    )

    assert [run.id for run in await runs.list()] == ["late", "middle", "early"]


async def test_updating_a_run_start_time_reorders_it(database: Database) -> None:
    runs = SqlRunRepository(database)
    await runs.add(make_run(id="first", started_at=START))
    await runs.add(make_run(id="second", started_at=START + timedelta(minutes=1)))

    await runs.update(make_run(id="first", started_at=START + timedelta(minutes=2)))

    assert [run.id for run in await runs.list()] == ["first", "second"]


async def test_renaming_onto_a_tracked_name_conflicts(database: Database) -> None:
    branches = SqlBranchRepository(database)
    one = make_branch(id="a", name="one")
    await branches.add(one)
    await branches.add(make_branch(id="b", name="two"))

    with pytest.raises(ConflictError):
        await branches.update(make_branch(id="b", name="one"))

    assert await branches.find("one") == one


async def test_renaming_frees_the_old_name(database: Database) -> None:
    branches = SqlBranchRepository(database)
    await branches.add(make_branch(id="a", name="one"))

    await branches.update(make_branch(id="a", name="renamed"))

    assert await branches.find("one") is None
    await branches.add(make_branch(id="b", name="one"))


async def test_removing_a_branch_keeps_its_runs_and_events(database: Database) -> None:
    branches = SqlBranchRepository(database)
    runs = SqlRunRepository(database)
    events = SqlEventRepository(database)
    await branches.add(make_branch())
    await runs.add(make_run())
    await events.append(EventDraft(kind=EventKind.TRACKED, branch_id="branch-1"), at=START)

    await branches.remove("branch-1")

    assert [run.id for run in await runs.list(branch_id="branch-1")] == ["run-1"]
    assert [event.branch_id for event in await events.list()] == ["branch-1"]
