import pytest
from pydantic import ValidationError

from git_manager.branches import BranchHeads, BranchState, TrackedBranch
from tests.conftest import make_branch, sha


def test_new_branch_starts_idle_without_a_reason() -> None:
    branch = make_branch()

    assert branch.state is BranchState.IDLE
    assert branch.reason is None


@pytest.mark.parametrize("bad", ["abc123", "g" * 40, "A" * 40])
def test_commit_hashes_must_be_full_lowercase_hex(bad: str) -> None:
    with pytest.raises(ValidationError):
        make_branch(fork_point=bad)


def test_sha256_hashes_are_accepted() -> None:
    assert make_branch(fork_point="a" * 64).fork_point == "a" * 64


def test_branch_round_trips_through_json() -> None:
    branch = make_branch(state=BranchState.PAUSED, reason="paused_by_user")

    assert TrackedBranch.model_validate_json(branch.model_dump_json()) == branch


def test_heads_have_no_new_head_until_the_run_produces_one() -> None:
    assert BranchHeads(branch="feature/one", old_head=sha(2)).new_head is None
