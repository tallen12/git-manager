"""The individual rebase run: fetch, ``rebase --onto``, verify, push with a lease.

See "Rebase run" in the spec's sync lifecycle. M1 has no Resolver, so a conflict stops in
``needs_human``; a rewritten base stops there too until retargeting lands in M4.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from pydantic import JsonValue

from git_manager.approvals.protocols import ApprovalGate
from git_manager.branches.models import BranchHeads, BranchState, CommitSha, Reason, TrackedBranch
from git_manager.branches.poller import branch_options
from git_manager.config.models import ApprovalPolicy, BranchOptions, RepoConfig
from git_manager.errors import NotFoundError
from git_manager.events.models import EventDraft, EventKind
from git_manager.events.protocols import EventSink
from git_manager.rebasing.errors import RemoteBranchMissingError
from git_manager.rebasing.models import (
    LeaseRejected,
    Pushed,
    RebaseCompleted,
    RebaseStopped,
    Run,
    RunTrigger,
)
from git_manager.rebasing.protocols import BranchLocks, Git
from git_manager.runtime.protocols import Clock, IdGenerator
from git_manager.store.protocols import BranchRepository, RunRepository
from git_manager.verification.commands import CommandsInvalid, CommandsMissing, config_commands
from git_manager.verification.models import VerifyCommands, VerifyFailed, VerifyPassed
from git_manager.verification.protocols import Verifier


def attempt_branch(branch: str, run_id: str) -> str:
    """The local branch that keeps a failed attempt of ``run_id`` (never pushed)."""
    return f"gm/attempt/{branch}/{run_id}"


def run_worktree(config: RepoConfig, run_id: str) -> Path:
    """Where ``run_id`` checks out the branch it rebases."""
    return config.repo.data_dir / "worktrees" / run_id


def worktree_head(worktree: Path) -> str:
    """The revision naming ``worktree``'s HEAD from the clone or any other worktree."""
    # git names a linked worktree's private refs by its folder name.
    return f"worktrees/{worktree.name}/HEAD"


def needs_approval(options: BranchOptions) -> bool:
    """Whether a clean, verified rebase waits for a human before it is pushed."""
    return options.approval_policy is ApprovalPolicy.ALWAYS or not options.auto_push_clean


@dataclass(frozen=True, slots=True)
class _Tips:
    """The remote base and feature branch an attempt starts from, both fetched."""

    base: CommitSha
    head: CommitSha


@dataclass(frozen=True, slots=True)
class _Restart:
    """The feature branch moved on the remote; start again from ``tips``."""

    tips: _Tips


@dataclass(frozen=True, slots=True)
class _Stop:
    """The run ends in ``state`` without pushing."""

    state: BranchState
    reason: Reason | None = None


@dataclass(frozen=True, slots=True)
class _Pushed:
    """The rebased branch is on the remote at ``head``, on top of ``base``."""

    base: CommitSha
    head: CommitSha


type _AttemptEnd = _Restart | _Stop | _Pushed


@dataclass(slots=True)
class _Progress:
    """The branch and run records as last stored; one run's working state."""

    branch: TrackedBranch
    run: Run


class RebaseRunner:
    """``RunExecutor`` over the ``Git``, store, ``Verifier`` and ``ApprovalGate`` protocols.

    Every state change is stored on both the branch and the run before its event is
    emitted. The run worktree under ``<data_dir>/worktrees`` is removed after every
    attempt, whatever happened in it.
    """

    def __init__(
        self,
        *,
        git: Git,
        branches: BranchRepository,
        runs: RunRepository,
        events: EventSink,
        verifier: Verifier,
        approvals: ApprovalGate,
        locks: BranchLocks,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._git = git
        self._branches = branches
        self._runs = runs
        self._events = events
        self._verifier = verifier
        self._approvals = approvals
        self._locks = locks
        self._clock = clock
        self._ids = ids

    async def run(self, branch_id: str, *, trigger: RunTrigger, config: RepoConfig) -> Run:
        async with self._locks.hold(branch_id):
            branch = await self._branches.get(branch_id)
            if branch is None:
                raise NotFoundError(kind="branch", key=branch_id)
            tips = await self._start_tips(branch)
            run = Run(
                id=self._ids.new_id(),
                branch_id=branch.id,
                trigger=trigger,
                base_from=branch.last_base_sha,
                base_to=tips.base,
                heads=(BranchHeads(branch=branch.name, old_head=tips.head),),
                outcome=BranchState.REBASING,
                started_at=self._clock.now(),
            )
            await self._runs.add(run)
            progress = _Progress(branch=branch, run=run)
            await self._emit(progress, EventKind.RUN_STARTED)
            try:
                await self._move(progress, BranchState.REBASING)
                await self._execute(progress, tips, config)
            except Exception:
                # Whatever broke, a human looks before the branch is touched again.
                await self._finish(progress, BranchState.NEEDS_HUMAN)
                raise
            return progress.run

    async def _start_tips(self, branch: TrackedBranch) -> _Tips:
        remote = await self._git.ls_remote([branch.base, branch.name])
        base, head = remote.get(branch.base), remote.get(branch.name)
        if base is None or head is None:
            # The poller handles both: a missing base waits in base_missing, a missing
            # feature branch is never scheduled.
            state, missing = (
                (BranchState.BASE_MISSING, branch.base)
                if base is None
                else (BranchState.IDLE, branch.name)
            )
            await self._branches.update(branch.model_copy(update={"state": state, "reason": None}))
            await self._events.emit(
                EventDraft(kind=EventKind.STATE_CHANGED, branch_id=branch.id, state=state)
            )
            raise RemoteBranchMissingError(branch=branch.name, missing=missing)
        await self._git.fetch([branch.base, branch.name])
        return _Tips(base=base, head=head)

    async def _execute(self, progress: _Progress, tips: _Tips, config: RepoConfig) -> None:
        options = branch_options(config, progress.branch.name)
        match config_commands(options.verify):
            case VerifyCommands() as commands:
                await self._update_run(progress, commands=commands)
            case CommandsMissing():
                await self._finish(progress, BranchState.NEEDS_CONFIG, Reason.MISSING_COMMANDS)
                return
            case CommandsInvalid():
                await self._finish(progress, BranchState.NEEDS_CONFIG, Reason.INVALID_COMMANDS)
                return
            case unreachable:
                assert_never(unreachable)
        worktree = run_worktree(config, progress.run.id)
        while True:
            if not await self._git.is_ancestor(progress.branch.last_base_sha, tips.base):
                await self._update_run(progress, rewritten_base=True)
                await self._finish(progress, BranchState.NEEDS_HUMAN, Reason.REWRITTEN_BASE)
                return
            await self._git.add_worktree(worktree, tips.head)
            try:
                end = await self._attempt(progress, tips, options, commands, worktree)
            finally:
                await self._git.remove_worktree(worktree)
            match end:
                case _Restart(tips=moved):
                    if progress.run.restarts >= options.max_restarts:
                        await self._finish(progress, BranchState.PAUSED, Reason.MAX_RESTARTS)
                        return
                    tips = moved
                    await self._update_run(
                        progress,
                        restarts=progress.run.restarts + 1,
                        base_to=tips.base,
                        heads=(BranchHeads(branch=progress.branch.name, old_head=tips.head),),
                        tests=(),
                    )
                    if progress.branch.state is not BranchState.REBASING:
                        await self._move(progress, BranchState.REBASING)
                case _Stop(state=state, reason=reason):
                    await self._finish(progress, state, reason)
                    return
                case _Pushed():
                    await self._pushed(progress, end)
                    return
                case unreachable:
                    assert_never(unreachable)

    async def _attempt(
        self,
        progress: _Progress,
        tips: _Tips,
        options: BranchOptions,
        commands: VerifyCommands,
        worktree: Path,
    ) -> _AttemptEnd:
        name = progress.branch.name
        outcome = await self._git.rebase_onto(
            worktree,
            new_base=tips.base,
            fork_point=progress.branch.fork_point,
            rebase_merges=options.rebase_merges,
        )
        match outcome:
            case RebaseStopped():
                if (moved := await self._head_moved(progress.branch, tips)) is not None:
                    return _Restart(moved)
                if options.keep_failed_attempts:
                    await self._git.create_branch(
                        attempt_branch(name, progress.run.id), worktree_head(worktree)
                    )
                await self._git.abort_rebase(worktree)
                return _Stop(BranchState.NEEDS_HUMAN, Reason.CONFLICT)
            case RebaseCompleted(head=head):
                pass
            case unreachable:
                assert_never(unreachable)
        heads = (BranchHeads(branch=name, old_head=tips.head, new_head=head),)
        await self._update_run(progress, heads=heads)
        if (moved := await self._head_moved(progress.branch, tips)) is not None:
            return _Restart(moved)

        await self._move(progress, BranchState.VERIFYING)
        verified = await self._verifier.verify(
            worktree=worktree, commands=commands, config=options.verify, run_id=progress.run.id
        )
        await self._update_run(progress, tests=verified.results)
        match verified:
            case VerifyFailed():
                return _Stop(BranchState.TESTS_FAILED, Reason.VERIFY_FAILED)
            case VerifyPassed():
                pass
            case unreachable:
                assert_never(unreachable)
        if (moved := await self._head_moved(progress.branch, tips)) is not None:
            return _Restart(moved)

        if needs_approval(options):
            await self._approvals.request(run_id=progress.run.id, base_sha=tips.base, heads=heads)
            return _Stop(BranchState.AWAITING_APPROVAL)
        await self._move(progress, BranchState.PUSHING)
        # The lease is the tip this attempt rebased: anything else on the remote is a
        # push we have not seen.
        match await self._git.push_with_lease(worktree, branch=name, head=head, expected=tips.head):
            case Pushed(head=pushed):
                return _Pushed(base=tips.base, head=pushed)
            case LeaseRejected():
                return _Stop(BranchState.DIVERGED_REMOTE, Reason.LEASE_REJECTED)
            case unreachable:
                assert_never(unreachable)

    async def _head_moved(self, branch: TrackedBranch, tips: _Tips) -> _Tips | None:
        """The fetched new tips if the feature branch moved since ``tips`` were read.

        A branch or base deleted mid-run is not a move: the push lease or the next poll
        deals with it.
        """
        remote = await self._git.ls_remote([branch.base, branch.name])
        base, head = remote.get(branch.base), remote.get(branch.name)
        if base is None or head is None or head == tips.head:
            return None
        await self._git.fetch([branch.base, branch.name])
        return _Tips(base=base, head=head)

    async def _pushed(self, progress: _Progress, pushed: _Pushed) -> None:
        old_head = progress.run.heads[0].old_head
        progress.branch = progress.branch.model_copy(
            update={
                "fork_point": pushed.base,
                "last_base_sha": pushed.base,
                "last_head_sha": pushed.head,
            }
        )
        data: dict[str, JsonValue] = {"from": old_head, "to": pushed.head}
        await self._branches.update(progress.branch)
        await self._emit(progress, EventKind.PUSHED, data=data)
        await self._finish(progress, BranchState.IDLE)

    async def _move(
        self, progress: _Progress, state: BranchState, reason: Reason | None = None
    ) -> None:
        progress.branch = progress.branch.model_copy(update={"state": state, "reason": reason})
        await self._branches.update(progress.branch)
        await self._update_run(progress, outcome=state, reason=reason)
        await self._emit(progress, EventKind.STATE_CHANGED)

    async def _finish(
        self, progress: _Progress, state: BranchState, reason: Reason | None = None
    ) -> None:
        await self._move(progress, state, reason)
        # An approval completes the run later (F19), so it is not finished yet.
        if state is BranchState.AWAITING_APPROVAL:
            return
        await self._update_run(progress, finished_at=self._clock.now())
        await self._emit(progress, EventKind.RUN_FINISHED)

    async def _update_run(self, progress: _Progress, **fields: object) -> None:
        progress.run = progress.run.model_copy(update=fields)
        await self._runs.update(progress.run)

    async def _emit(
        self, progress: _Progress, kind: EventKind, *, data: dict[str, JsonValue] | None = None
    ) -> None:
        await self._events.emit(
            EventDraft(
                kind=kind,
                branch_id=progress.branch.id,
                run_id=progress.run.id,
                state=progress.branch.state,
                reason=progress.branch.reason,
                data=data or {},
            )
        )
