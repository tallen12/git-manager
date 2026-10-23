from pydantic import TypeAdapter

from git_manager.branches.results import SyncCompleted, SyncOutcome, SyncQueued
from tests.conftest import make_run

ADAPTER: TypeAdapter[SyncOutcome] = TypeAdapter(SyncOutcome)


def test_sync_outcomes_are_told_apart_by_kind_when_parsed() -> None:
    completed = SyncCompleted(run=make_run())
    queued = SyncQueued(branch_id="branch-1", position=2)

    assert ADAPTER.validate_json(ADAPTER.dump_json(completed)) == completed
    assert ADAPTER.validate_json(ADAPTER.dump_json(queued)) == queued
