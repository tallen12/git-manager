"""Branches over REST: the routes and their client mirror.

Routes take a tracked branch's name or id, like ``BranchOperations``. Branch names contain
slashes (``feature/x``), so the path parameter matches them whole.
"""

from dataclasses import dataclass
from urllib.parse import quote

import httpx
from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from git_manager.approvals import Scope
from git_manager.branches.models import RepoStatus, TrackedBranch
from git_manager.branches.protocols import BranchOperations
from git_manager.branches.results import SyncOutcome
from git_manager.web.api_client import API_PREFIX, ApiClient
from git_manager.web.auth import Access
from git_manager.web.errors import ERROR_RESPONSES

REPO_PATH = f"{API_PREFIX}/repo"
BRANCHES_PATH = f"{API_PREFIX}/branches"
_BRANCH_PATH = f"{BRANCHES_PATH}/{{branch:path}}"
# The daemon only queues a sync, but REST served over a local target (``web.app.serve``)
# runs it while the request waits: as long as its tests take.
SYNC_TIMEOUT = httpx.Timeout(10.0, read=None)

_STATUS = TypeAdapter(RepoStatus)
_BRANCH = TypeAdapter(TrackedBranch)
_SYNC = TypeAdapter[SyncOutcome](SyncOutcome)


class TrackRequest(BaseModel):
    """``POST /branches``: start tracking ``name`` on ``base``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    base: str = Field(min_length=1)


def branch_path(branch: str, action: str | None = None) -> str:
    """The URL path of a branch (name or id), or of one of its actions."""
    path = f"{BRANCHES_PATH}/{quote(branch, safe='/')}"
    return path if action is None else f"{path}/{action}"


def branches_router(operations: BranchOperations, *, access: Access) -> APIRouter:
    """Routes for ``BranchOperations``."""
    router = APIRouter(tags=["branches"], responses=ERROR_RESPONSES)
    read = [access.requires(Scope.READ)]
    operate = [access.requires(Scope.OPERATE)]

    @router.get(REPO_PATH, dependencies=read)
    async def repo_status() -> RepoStatus:
        """The repository and every tracked branch with its state."""
        return await operations.status()

    @router.post(BRANCHES_PATH, status_code=status.HTTP_201_CREATED, dependencies=operate)
    async def track(request: TrackRequest) -> TrackedBranch:
        return await operations.track(name=request.name, base=request.base)

    @router.delete(_BRANCH_PATH, status_code=status.HTTP_204_NO_CONTENT, dependencies=operate)
    async def untrack(branch: str) -> None:
        await operations.untrack(branch)

    @router.post(f"{_BRANCH_PATH}/sync", dependencies=operate)
    async def sync(branch: str) -> SyncOutcome:
        return await operations.sync(branch)

    @router.post(f"{_BRANCH_PATH}/pause", dependencies=operate)
    async def pause(branch: str) -> TrackedBranch:
        return await operations.pause(branch)

    @router.post(f"{_BRANCH_PATH}/resume", dependencies=operate)
    async def resume(branch: str) -> TrackedBranch:
        return await operations.resume(branch)

    return router


@dataclass(frozen=True, slots=True)
class HttpBranchOperations:
    """``BranchOperations`` through the REST API."""

    api: ApiClient

    async def status(self) -> RepoStatus:
        """Return the repository and every tracked branch."""
        return await self.api.get(REPO_PATH, _STATUS)

    async def track(self, *, name: str, base: str) -> TrackedBranch:
        """Start tracking ``name`` on ``base``."""
        request = TrackRequest(name=name, base=base)
        return await self.api.post(BRANCHES_PATH, _BRANCH, body=request)

    async def untrack(self, branch: str) -> None:
        """Stop tracking a branch."""
        await self.api.delete(branch_path(branch))

    async def sync(self, branch: str) -> SyncOutcome:
        """Rebase now; waits for the run when the daemon runs it in the foreground."""
        return await self.api.post(branch_path(branch, "sync"), _SYNC, timeouts=SYNC_TIMEOUT)

    async def pause(self, branch: str) -> TrackedBranch:
        """Stop polling and syncing a branch."""
        return await self.api.post(branch_path(branch, "pause"), _BRANCH)

    async def resume(self, branch: str) -> TrackedBranch:
        """Leave ``paused`` or a settled stop state."""
        return await self.api.post(branch_path(branch, "resume"), _BRANCH)
