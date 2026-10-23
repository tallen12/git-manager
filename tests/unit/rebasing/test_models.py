import pytest
from pydantic import ValidationError

from git_manager.branches import BranchState
from git_manager.rebasing import Run
from tests.conftest import START, make_run


def test_run_round_trips_through_json() -> None:
    run = make_run()

    assert Run.model_validate_json(run.model_dump_json()) == run


def test_an_unfinished_run_shows_its_current_state() -> None:
    run = make_run(outcome=BranchState.VERIFYING, finished_at=None)

    assert run.finished_at is None
    assert run.outcome is BranchState.VERIFYING


def test_run_times_carry_a_timezone() -> None:
    with pytest.raises(ValidationError):
        make_run(started_at=START.replace(tzinfo=None))
