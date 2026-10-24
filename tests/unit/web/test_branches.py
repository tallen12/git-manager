from collections.abc import Awaitable, Callable

import pytest
from fastapi import APIRouter

from git_manager.branches import BranchState
from git_manager.branches.protocols import BranchOperations
from git_manager.branches.results import SyncCompleted, SyncQueued
from git_manager.errors import NotFoundError
from git_manager.web.api_client import ApiError
from git_manager.web.auth import Access
from git_manager.web.branches import (
    SYNC_TIMEOUT,
    HttpBranchOperations,
    branch_path,
    branches_router,
)
from tests.conftest import make_branch, make_run
from tests.unit.cli.conftest import FakeBranchOperations
from tests.unit.web.conftest import serving


def branches_of(fake: FakeBranchOperations) -> Callable[[Access], APIRouter]:
    return lambda access: branches_router(fake, access=access)


async def test_status_and_track_round_trip() -> None:
    fake = FakeBranchOperations()
    async with serving(branches_of(fake)) as api:
        operations: BranchOperations = HttpBranchOperations(api)
        tracked = await operations.track(name="feature/x", base="main")
        status = await operations.status()

    assert tracked == make_branch(name="feature/x", base="main")
    assert status.branches == (tracked,)
    assert fake.calls == ["track feature/x main", "status"]


async def test_branch_actions_reach_a_branch_whose_name_has_slashes() -> None:
    branch = make_branch(name="feature/x/sync")
    fake = FakeBranchOperations(branches={branch.name: branch})
    async with serving(branches_of(fake)) as api:
        operations = HttpBranchOperations(api)
        paused = await operations.pause(branch.name)
        resumed = await operations.resume(branch.name)
        outcome = await operations.sync(branch.name)
        await operations.untrack(branch.name)

    assert paused.state is BranchState.PAUSED
    assert resumed.state is BranchState.IDLE
    assert outcome == SyncCompleted(run=make_run())
    assert fake.calls == [
        f"{action} feature/x/sync" for action in ("pause", "resume", "sync", "untrack")
    ]
    assert fake.branches == {}


async def test_sync_returns_a_queued_outcome_as_is() -> None:
    branch = make_branch()
    queued = SyncQueued(branch_id=branch.id, position=2)
    fake = FakeBranchOperations(branches={branch.name: branch}, sync_outcome=queued)
    async with serving(branches_of(fake)) as api:
        outcome = await HttpBranchOperations(api).sync(branch.name)

    assert outcome == queued


async def test_an_unknown_branch_raises_not_found() -> None:
    async with serving(branches_of(FakeBranchOperations())) as api:
        with pytest.raises(NotFoundError, match="branch not found: nope"):
            await HttpBranchOperations(api).pause("nope")


CHANGES: list[Callable[[BranchOperations], Awaitable[object]]] = [
    lambda operations: operations.track(name="b", base="main"),
    lambda operations: operations.untrack("feature/one"),
    lambda operations: operations.sync("feature/one"),
    lambda operations: operations.pause("feature/one"),
    lambda operations: operations.resume("feature/one"),
]


@pytest.mark.parametrize("change", CHANGES, ids=["track", "untrack", "sync", "pause", "resume"])
async def test_changes_need_the_operate_scope(
    change: Callable[[BranchOperations], Awaitable[object]],
) -> None:
    branch = make_branch()
    fake = FakeBranchOperations(branches={branch.name: branch})
    async with serving(branches_of(fake), as_token="reader") as api:
        operations = HttpBranchOperations(api)
        await operations.status()
        with pytest.raises(ApiError) as raised:
            await change(operations)

    assert raised.value.status_code == 403
    assert fake.calls == ["status"]


def test_branch_path_escapes_everything_but_slashes() -> None:
    assert branch_path("feature/a#1") == "/api/v1/branches/feature/a%231"
    assert branch_path("f", "sync") == "/api/v1/branches/f/sync"


def test_sync_waits_for_a_foreground_run_without_a_read_timeout() -> None:
    assert SYNC_TIMEOUT.read is None
    assert SYNC_TIMEOUT.connect is not None
