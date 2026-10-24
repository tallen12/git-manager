"""In-process branch operations: track, untrack, status, sync, pause and resume."""

from typing import assert_never

from git_manager.branches.models import BranchState, CommitSha, Reason, RepoStatus, TrackedBranch
from git_manager.branches.protocols import BranchSyncer
from git_manager.branches.results import SyncOutcome
from git_manager.config.protocols import ConfigOperations
from git_manager.errors import ConflictError, NotFoundError
from git_manager.events.models import EventDraft, EventKind
from git_manager.events.protocols import EventSink
from git_manager.rebasing.protocols import BranchLocks, Git
from git_manager.runtime.protocols import IdGenerator
from git_manager.store.protocols import BranchRepository


def resume_refusal(state: BranchState) -> str | None:
    """Why ``resume`` cannot leave ``state``, or ``None`` if it can.

    Follows "Leaving stop states" in the spec: ``resume`` leaves ``paused``, and
    ``needs_human`` or ``diverged_remote`` once a human settled the remote branch. Every
    other stop state has its own way out, which the message names.
    """
    match state:
        case BranchState.PAUSED | BranchState.NEEDS_HUMAN | BranchState.DIVERGED_REMOTE:
            return None
        case BranchState.TESTS_FAILED:
            return "it leaves tests_failed when the base moves again, or with retry"
        case BranchState.NEEDS_CONFIG:
            return "it leaves needs_config once its test commands are set in the config"
        case BranchState.BASE_MISSING:
            return "it leaves base_missing when the base reappears, or with retarget"
        case BranchState.STACK_PARTIAL_PUSH:
            return "it leaves stack_partial_push with retry"
        case BranchState.WAITING_BUDGET:
            return "it leaves waiting_budget when the budget resets, or with budget reset"
        case BranchState.WAITING_QUOTA:
            return "it leaves waiting_quota when the usage limit resets"
        case BranchState.AWAITING_APPROVAL:
            return "it is awaiting approval"
        case (
            BranchState.IDLE
            | BranchState.BEHIND
            | BranchState.SCHEDULED
            | BranchState.RETARGETING
            | BranchState.REBASING
            | BranchState.RESOLVING
            | BranchState.VERIFYING
            | BranchState.PUSHING
        ):
            return f"it is {state}, not paused or stopped"
        case _:
            assert_never(state)


class BranchService:
    """``BranchOperations`` over the branch store, ``Git`` and an injected ``BranchSyncer``.

    Pause, resume and untrack hold the branch's lock, so they never interleave with a run:
    with a run in progress they wait for it to end. Every change emits its event.
    """

    def __init__(
        self,
        *,
        repo_id: str,
        config: ConfigOperations,
        git: Git,
        branches: BranchRepository,
        syncer: BranchSyncer,
        events: EventSink,
        locks: BranchLocks,
        ids: IdGenerator,
    ) -> None:
        self._repo_id = repo_id
        self._config = config
        self._git = git
        self._branches = branches
        self._syncer = syncer
        self._events = events
        self._locks = locks
        self._ids = ids

    async def status(self) -> RepoStatus:
        config = await self._config.show()
        branches = await self._branches.list()
        return RepoStatus(repo_id=self._repo_id, url=config.repo.url, branches=tuple(branches))

    async def track(self, *, name: str, base: str) -> TrackedBranch:
        if await self._branches.find(name) is not None:
            msg = f"branch already tracked: {name}"
            raise ConflictError(msg)
        fork_point, head = await self._remote_fork_point(name=name, base=base)
        branch = TrackedBranch(
            id=self._ids.new_id(),
            repo_id=self._repo_id,
            name=name,
            base=base,
            fork_point=fork_point,
            # What the branch sits on: if the base is already further, the next poll sees
            # it as moved and schedules a run by the cadence.
            last_base_sha=fork_point,
            last_head_sha=head,
        )
        await self._branches.add(branch)
        await self._emit(branch, EventKind.TRACKED, data={"base": base})
        return branch

    async def untrack(self, branch: str) -> None:
        found = await self._resolve(branch)
        async with self._locks.hold(found.id):
            await self._branches.remove(found.id)
            await self._emit(found, EventKind.UNTRACKED)

    async def sync(self, branch: str) -> SyncOutcome:
        found = await self._resolve(branch)
        if found.state is BranchState.PAUSED:
            msg = f"cannot sync {found.name}: it is paused; resume it first"
            raise ConflictError(msg)
        return await self._syncer.sync(found)

    async def pause(self, branch: str) -> TrackedBranch:
        found = await self._resolve(branch)
        async with self._locks.hold(found.id):
            current = await self._current(found)
            if current.state is BranchState.PAUSED:
                return current
            if current.state is BranchState.AWAITING_APPROVAL:
                msg = f"cannot pause {current.name}: it is awaiting approval"
                raise ConflictError(msg)
            paused = current.model_copy(
                update={"state": BranchState.PAUSED, "reason": Reason.PAUSED_BY_USER}
            )
            await self._branches.update(paused)
            await self._emit(paused, EventKind.STATE_CHANGED)
            return paused

    async def resume(self, branch: str) -> TrackedBranch:
        found = await self._resolve(branch)
        async with self._locks.hold(found.id):
            current = await self._current(found)
            if (refusal := resume_refusal(current.state)) is not None:
                msg = f"cannot resume {current.name}: {refusal}"
                raise ConflictError(msg)
            # A human may have rebased and pushed the branch meanwhile, so it starts again
            # from where the remote branch sits now, as if tracked afresh.
            fork_point, head = await self._remote_fork_point(name=current.name, base=current.base)
            resumed = current.model_copy(
                update={
                    "state": BranchState.IDLE,
                    "reason": None,
                    "fork_point": fork_point,
                    "last_base_sha": fork_point,
                    "last_head_sha": head,
                }
            )
            await self._branches.update(resumed)
            await self._emit(resumed, EventKind.STATE_CHANGED)
            return resumed

    async def _resolve(self, branch: str) -> TrackedBranch:
        """The tracked branch named ``branch``, or with ``branch`` as its id."""
        found = await self._branches.find(branch) or await self._branches.get(branch)
        if found is None:
            raise NotFoundError(kind="branch", key=branch)
        return found

    async def _current(self, branch: TrackedBranch) -> TrackedBranch:
        """``branch`` as stored now; a run may have changed it while we waited for its lock."""
        current = await self._branches.get(branch.id)
        if current is None:
            raise NotFoundError(kind="branch", key=branch.name)
        return current

    async def _remote_fork_point(self, *, name: str, base: str) -> tuple[CommitSha, CommitSha]:
        """Fetch ``name`` and ``base``; return their ``merge-base`` and the head of ``name``."""
        remote = await self._git.ls_remote([base, name])
        for ref in (name, base):
            if ref not in remote:
                raise NotFoundError(kind="remote branch", key=ref)
        await self._git.fetch([base, name])
        head = remote[name]
        return await self._git.merge_base(remote[base], head), head

    async def _emit(
        self, branch: TrackedBranch, kind: EventKind, *, data: dict[str, str] | None = None
    ) -> None:
        await self._events.emit(
            EventDraft(
                kind=kind,
                branch_id=branch.id,
                state=branch.state,
                reason=branch.reason,
                data=dict(data or {}),
            )
        )
