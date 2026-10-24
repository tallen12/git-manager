"""Answers one daemon request: checks it, then runs a command or hands over a tree."""

import asyncio
from typing import assert_never

from git_manager.isolation.models import (
    Chowned,
    ChownErrorCode,
    ChownFailed,
    ChownRequest,
    SpawnErrorCode,
    SpawnFailed,
    SpawnRequest,
    SupervisorResponse,
)
from git_manager.runtime import ProcessUser
from git_manager.supervisor.models import Account, LaunchPlan
from git_manager.supervisor.policy import is_inside, plan_run
from git_manager.supervisor.protocols import Accounts, CommandLauncher, Ownership
from git_manager.supervisor.settings import SupervisorSettings


class RequestHandler:
    """Enforces the supervisor policy for requests that arrive on its socket."""

    def __init__(
        self,
        *,
        settings: SupervisorSettings,
        accounts: Accounts,
        ownership: Ownership,
        launcher: CommandLauncher,
    ) -> None:
        self._settings = settings
        self._accounts = accounts
        self._ownership = ownership
        self._launcher = launcher

    async def handle(
        self, request: SpawnRequest | ChownRequest, *, peer_uid: int
    ) -> SupervisorResponse:
        """Answer ``request`` from a peer running as ``peer_uid``; only ``gm`` is served."""
        daemon = self._accounts.user(ProcessUser.ORCHESTRATOR)
        if daemon is None or peer_uid != daemon.uid:
            return refusal(request, f"only {ProcessUser.ORCHESTRATOR} may make requests")
        account = self._accounts.user(request.user)
        if account is None:
            return refusal(request, f"no such user {request.user}")
        match request:
            case SpawnRequest():
                return await self._run(request, account)
            case ChownRequest():
                return await self._chown(request, account)
            case _:
                assert_never(request)

    async def _run(self, request: SpawnRequest, account: Account) -> SupervisorResponse:
        plan = plan_run(
            request,
            account,
            data_root=self._settings.data_root,
            output_limit_bytes=self._settings.output_limit_bytes,
        )
        match plan:
            case LaunchPlan():
                return await self._launcher.run(plan)
            case SpawnFailed():
                return plan

    async def _chown(self, request: ChownRequest, account: Account) -> SupervisorResponse:
        if not is_inside(request.path, self._settings.data_root):
            return refusal(request, f"{request.path} is not inside {self._settings.data_root}")
        try:
            # A worktree walk touches every file; keep it off the event loop.
            skipped = await asyncio.to_thread(
                self._ownership.hand_over, request.path, uid=account.uid, gid=account.gid
            )
        except OSError as error:
            return ChownFailed(code=ChownErrorCode.FAILED, message=str(error))
        return Chowned(skipped=skipped)


def refusal(request: SpawnRequest | ChownRequest, message: str) -> SupervisorResponse:
    """The ``invalid_request`` answer of the kind ``request`` expects."""
    match request:
        case SpawnRequest():
            return SpawnFailed(code=SpawnErrorCode.INVALID_REQUEST, message=message)
        case ChownRequest():
            return ChownFailed(code=ChownErrorCode.INVALID_REQUEST, message=message)
        case _:
            assert_never(request)
