import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import override

import pytest

from git_manager.branches import BranchHeads, BranchState, Reason
from git_manager.config.models import ApprovalPolicy, BranchOptions, RepoConfig, VerifyConfig
from git_manager.core.errors import NotFoundError
from git_manager.events import EventKind
from git_manager.rebasing import (
    PushOutcome,
    RebaseCompleted,
    RebaseStopped,
    RemoteBranchMissingError,
    Run,
    RunExecutor,
    RunTrigger,
)
from git_manager.rebasing.runner import (
    attempt_branch,
    needs_approval,
    run_worktree,
    worktree_head,
)
from git_manager.verification import (
    StepOutcome,
    TestResult,
    VerifyCommands,
    VerifyFailed,
    VerifyOutcome,
    VerifyStep,
)
from tests.conftest import FakeGit, FakeVerifier, sha
from tests.unit.rebasing.conftest import (
    BRANCH,
    HEAD,
    NEW_BASE,
    OLD_BASE,
    REBASED,
    Harness,
    make_harness,
    repo_config,
)

FAILED = TestResult(
    step=VerifyStep.TEST,
    command="just test",
    outcome=StepOutcome.FAILED,
    exit_code=1,
    attempts=1,
    duration_s=1.0,
    output_tail="1 failed",
)


async def sync(harness: Harness, config: RepoConfig | None = None) -> Run:
    executor: RunExecutor = harness.runner
    return await executor.run(
        "branch-1", trigger=RunTrigger.POLL, config=config or repo_config(harness.data_dir)
    )


def transitions(harness: Harness) -> list[tuple[EventKind, BranchState | None]]:
    return [(event.kind, event.state) for event in harness.events.events]


@dataclass(slots=True)
class MovingVerifier:
    """``Verifier`` during which a teammate pushes the next of ``heads`` to the branch."""

    git: FakeGit
    heads: list[str]
    inner: FakeVerifier = field(default_factory=FakeVerifier)

    async def verify(
        self, *, worktree: Path, commands: VerifyCommands, config: VerifyConfig, run_id: str
    ) -> VerifyOutcome:
        if self.heads:
            self.git.remote[BRANCH] = self.heads.pop(0)
        return await self.inner.verify(
            worktree=worktree, commands=commands, config=config, run_id=run_id
        )


@dataclass(slots=True)
class RacingGit(FakeGit):
    """``FakeGit`` where a teammate pushes ``racer`` just before our push."""

    racer: str = sha(99)

    @override
    async def push_with_lease(
        self, worktree: Path, *, branch: str, head: str, expected: str
    ) -> PushOutcome:
        self.remote[branch] = self.racer
        return await FakeGit.push_with_lease(
            self, worktree, branch=branch, head=head, expected=expected
        )


def test_names_of_the_attempt_branch_and_worktree(tmp_path: Path) -> None:
    config = repo_config(tmp_path)

    assert attempt_branch("feature/one", "run-7") == "gm/attempt/feature/one/run-7"
    assert run_worktree(config, "run-7") == tmp_path / "worktrees" / "run-7"
    assert worktree_head(tmp_path / "worktrees" / "run-7") == "worktrees/run-7/HEAD"


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (BranchOptions(), False),
        (BranchOptions(approval_policy=ApprovalPolicy.ALWAYS), True),
        (BranchOptions(auto_push_clean=False), True),
    ],
)
def test_needs_approval_follows_policy_and_auto_push(
    options: BranchOptions, *, expected: bool
) -> None:
    assert needs_approval(options) is expected


async def test_clean_rebase_is_verified_pushed_and_recorded(harness: Harness) -> None:
    harness.git.rebase_outcomes.append(RebaseCompleted(head=REBASED))

    run = await sync(harness)

    worktree = harness.data_dir / "worktrees" / "run-1"
    assert run.outcome is BranchState.IDLE
    assert run.reason is None
    assert run.finished_at is not None
    assert run.base_from == OLD_BASE
    assert run.base_to == NEW_BASE
    assert run.heads == (BranchHeads(branch=BRANCH, old_head=HEAD, new_head=REBASED),)
    assert run.commands is not None
    assert run.commands.test == "just test"
    assert harness.runs.rows["run-1"] == run
    assert harness.git.remote[BRANCH] == REBASED
    assert harness.git.fetched[0] == ("main", BRANCH)
    assert harness.git.worktrees == {}
    assert isinstance(harness.verifier, FakeVerifier)
    assert [call.worktree for call in harness.verifier.calls] == [worktree]
    branch = harness.branches.rows["branch-1"]
    assert (branch.fork_point, branch.last_base_sha, branch.last_head_sha) == (
        NEW_BASE,
        NEW_BASE,
        REBASED,
    )
    assert (branch.state, branch.reason) == (BranchState.IDLE, None)
    assert transitions(harness) == [
        (EventKind.RUN_STARTED, BranchState.IDLE),
        (EventKind.STATE_CHANGED, BranchState.REBASING),
        (EventKind.STATE_CHANGED, BranchState.VERIFYING),
        (EventKind.STATE_CHANGED, BranchState.PUSHING),
        (EventKind.PUSHED, BranchState.PUSHING),
        (EventKind.STATE_CHANGED, BranchState.IDLE),
        (EventKind.RUN_FINISHED, BranchState.IDLE),
    ]
    pushed = harness.events.events[4]
    assert pushed.data == {"from": HEAD, "to": REBASED}
    assert {event.run_id for event in harness.events.events} == {"run-1"}
    assert not harness.locks.held("branch-1")


async def test_rebase_uses_the_fork_point_and_rebase_merges(tmp_path: Path) -> None:
    calls: list[tuple[str, str, bool]] = []

    @dataclass(slots=True)
    class RecordingGit(FakeGit):
        @override
        async def rebase_onto(
            self, worktree: Path, *, new_base: str, fork_point: str, rebase_merges: bool
        ) -> RebaseCompleted | RebaseStopped:
            calls.append((new_base, fork_point, rebase_merges))
            return await FakeGit.rebase_onto(
                self,
                worktree,
                new_base=new_base,
                fork_point=fork_point,
                rebase_merges=rebase_merges,
            )

    harness = make_harness(tmp_path, git=RecordingGit())
    harness.git.rebase_outcomes.append(RebaseCompleted(head=REBASED))

    await sync(harness, repo_config(tmp_path, rebase_merges=True))

    assert calls == [(NEW_BASE, OLD_BASE, True)]


async def test_conflict_stops_in_needs_human_and_keeps_the_attempt(harness: Harness) -> None:
    harness.git.rebase_outcomes.append(RebaseStopped(commit=sha(5), conflicted_paths=("a.py",)))

    run = await sync(harness)

    worktree = harness.data_dir / "worktrees" / "run-1"
    assert (run.outcome, run.reason) == (BranchState.NEEDS_HUMAN, Reason.CONFLICT)
    assert run.finished_at is not None
    assert harness.git.local_branches == {"gm/attempt/feature/one/run-1": "worktrees/run-1/HEAD"}
    assert harness.git.aborted == [worktree]
    assert harness.git.worktrees == {}
    assert harness.git.remote[BRANCH] == HEAD
    assert isinstance(harness.verifier, FakeVerifier)
    assert harness.verifier.calls == []
    branch = harness.branches.rows["branch-1"]
    assert (branch.state, branch.reason) == (BranchState.NEEDS_HUMAN, Reason.CONFLICT)
    assert branch.last_base_sha == OLD_BASE
    assert transitions(harness)[-2:] == [
        (EventKind.STATE_CHANGED, BranchState.NEEDS_HUMAN),
        (EventKind.RUN_FINISHED, BranchState.NEEDS_HUMAN),
    ]


async def test_conflict_keeps_no_attempt_when_turned_off(harness: Harness) -> None:
    harness.git.rebase_outcomes.append(RebaseStopped(commit=sha(5), conflicted_paths=("a.py",)))

    await sync(harness, repo_config(harness.data_dir, keep_failed_attempts=False))

    assert harness.git.local_branches == {}
    assert harness.git.worktrees == {}


async def test_failed_verification_stops_in_tests_failed_with_results(tmp_path: Path) -> None:
    verifier = FakeVerifier(outcomes=[VerifyFailed(results=(FAILED,), failed_step=VerifyStep.TEST)])
    harness = make_harness(tmp_path, verifier=verifier)
    harness.git.rebase_outcomes.append(RebaseCompleted(head=REBASED))

    run = await sync(harness)

    assert (run.outcome, run.reason) == (BranchState.TESTS_FAILED, Reason.VERIFY_FAILED)
    assert run.tests == (FAILED,)
    assert run.heads[0].new_head == REBASED
    assert harness.git.remote[BRANCH] == HEAD
    assert harness.git.worktrees == {}
    branch = harness.branches.rows["branch-1"]
    assert (branch.state, branch.last_head_sha) == (BranchState.TESTS_FAILED, HEAD)


@pytest.mark.parametrize(
    ("verify", "reason"),
    [
        (VerifyConfig(), Reason.MISSING_COMMANDS),
        (VerifyConfig(test='just "test'), Reason.INVALID_COMMANDS),
    ],
)
async def test_unusable_verify_commands_stop_in_needs_config_before_rebasing(
    harness: Harness, verify: VerifyConfig, reason: Reason
) -> None:
    run = await sync(harness, repo_config(harness.data_dir, verify=verify))

    assert (run.outcome, run.reason) == (BranchState.NEEDS_CONFIG, reason)
    assert run.commands is None
    assert harness.git.remote[BRANCH] == HEAD
    branch = harness.branches.rows["branch-1"]
    assert (branch.state, branch.reason) == (BranchState.NEEDS_CONFIG, reason)


async def test_rejected_lease_goes_to_diverged_remote(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, git=RacingGit())
    harness.git.rebase_outcomes.append(RebaseCompleted(head=REBASED))

    run = await sync(harness)

    assert (run.outcome, run.reason) == (BranchState.DIVERGED_REMOTE, Reason.LEASE_REJECTED)
    assert harness.git.remote[BRANCH] == sha(99)
    assert harness.git.worktrees == {}
    branch = harness.branches.rows["branch-1"]
    assert (branch.state, branch.last_head_sha) == (BranchState.DIVERGED_REMOTE, HEAD)
    assert EventKind.PUSHED not in {event.kind for event in harness.events.events}


async def test_head_moving_mid_run_restarts_from_the_new_tip(tmp_path: Path) -> None:
    moved, rebased_again = sha(7), sha(8)
    git = FakeGit()
    harness = make_harness(tmp_path, git=git, verifier=MovingVerifier(git=git, heads=[moved]))
    git.rebase_outcomes.extend([RebaseCompleted(head=REBASED), RebaseCompleted(head=rebased_again)])

    run = await sync(harness)

    assert run.outcome is BranchState.IDLE
    assert run.restarts == 1
    assert run.heads == (BranchHeads(branch=BRANCH, old_head=moved, new_head=rebased_again),)
    assert git.remote[BRANCH] == rebased_again
    assert git.worktrees == {}
    assert harness.branches.rows["branch-1"].last_head_sha == rebased_again
    states = [state for kind, state in transitions(harness) if kind is EventKind.STATE_CHANGED]
    assert states == [
        BranchState.REBASING,
        BranchState.VERIFYING,
        BranchState.REBASING,
        BranchState.VERIFYING,
        BranchState.PUSHING,
        BranchState.IDLE,
    ]


async def test_too_many_restarts_pause_the_branch(tmp_path: Path) -> None:
    git = FakeGit()
    verifier = MovingVerifier(git=git, heads=[sha(7), sha(8), sha(9)])
    harness = make_harness(tmp_path, git=git, verifier=verifier)
    git.rebase_outcomes.extend([RebaseCompleted(head=REBASED)] * 3)

    run = await sync(harness, repo_config(tmp_path, max_restarts=1))

    assert (run.outcome, run.reason) == (BranchState.PAUSED, Reason.MAX_RESTARTS)
    assert run.restarts == 1
    assert run.finished_at is not None
    assert git.remote[BRANCH] == sha(8)
    assert git.worktrees == {}
    branch = harness.branches.rows["branch-1"]
    assert (branch.state, branch.reason) == (BranchState.PAUSED, Reason.MAX_RESTARTS)


async def test_rewritten_base_stops_in_needs_human_without_a_worktree(harness: Harness) -> None:
    harness.git.ancestry.clear()

    run = await sync(harness)

    assert (run.outcome, run.reason) == (BranchState.NEEDS_HUMAN, Reason.REWRITTEN_BASE)
    assert run.rewritten_base
    assert harness.git.worktrees == {}
    assert harness.git.remote[BRANCH] == HEAD
    assert harness.branches.rows["branch-1"].reason is Reason.REWRITTEN_BASE


@pytest.mark.parametrize(
    "options",
    [{"approval_policy": ApprovalPolicy.ALWAYS}, {"auto_push_clean": False}],
)
async def test_run_needing_approval_stops_at_the_gate(
    harness: Harness, options: dict[str, object]
) -> None:
    harness.git.rebase_outcomes.append(RebaseCompleted(head=REBASED))

    run = await sync(harness, repo_config(harness.data_dir, **options))

    assert run.outcome is BranchState.AWAITING_APPROVAL
    assert run.finished_at is None
    assert harness.git.remote[BRANCH] == HEAD
    assert harness.git.worktrees == {}
    [request] = harness.approvals.requests
    assert (request.run_id, request.base_sha) == ("run-1", NEW_BASE)
    assert request.heads == (BranchHeads(branch=BRANCH, old_head=HEAD, new_head=REBASED),)
    branch = harness.branches.rows["branch-1"]
    assert (branch.state, branch.last_base_sha) == (BranchState.AWAITING_APPROVAL, OLD_BASE)
    assert transitions(harness)[-1] == (EventKind.STATE_CHANGED, BranchState.AWAITING_APPROVAL)


@dataclass(slots=True)
class BrokenVerifier:
    """``Verifier`` that fails unexpectedly."""

    async def verify(
        self, *, worktree: Path, commands: VerifyCommands, config: VerifyConfig, run_id: str
    ) -> VerifyOutcome:
        msg = "verifier crashed"
        raise RuntimeError(msg)


async def test_unexpected_error_removes_the_worktree_and_stops_in_needs_human(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path, verifier=BrokenVerifier())
    harness.git.rebase_outcomes.append(RebaseCompleted(head=REBASED))

    with pytest.raises(RuntimeError, match="verifier crashed"):
        await sync(harness)

    assert harness.git.worktrees == {}
    run = harness.runs.rows["run-1"]
    assert (run.outcome, run.reason) == (BranchState.NEEDS_HUMAN, None)
    assert run.finished_at is not None
    branch = harness.branches.rows["branch-1"]
    assert (branch.state, branch.reason) == (BranchState.NEEDS_HUMAN, None)
    assert not harness.locks.held("branch-1")


async def test_unknown_branch_raises_not_found(harness: Harness) -> None:
    with pytest.raises(NotFoundError):
        await harness.runner.run(
            "gone", trigger=RunTrigger.MANUAL, config=repo_config(harness.data_dir)
        )


@pytest.mark.parametrize(
    ("missing", "state"), [("main", BranchState.BASE_MISSING), (BRANCH, BranchState.IDLE)]
)
async def test_missing_remote_branch_records_no_run(
    harness: Harness, missing: str, state: BranchState
) -> None:
    del harness.git.remote[missing]

    with pytest.raises(RemoteBranchMissingError, match=missing):
        await sync(harness)

    assert harness.runs.rows == {}
    assert harness.git.fetched == []
    assert harness.branches.rows["branch-1"].state is state
    assert transitions(harness) == [(EventKind.STATE_CHANGED, state)]


async def test_a_run_waits_for_the_branch_lock(harness: Harness) -> None:
    harness.git.rebase_outcomes.append(RebaseCompleted(head=REBASED))

    async with harness.locks.hold("branch-1"):
        task = asyncio.create_task(sync(harness))
        await asyncio.sleep(0)
        assert not task.done()
        assert harness.runs.rows == {}

    run = await task
    assert run.outcome is BranchState.IDLE
