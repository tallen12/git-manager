"""Runs over REST: the routes and their client mirror."""

from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import TypeAdapter

from git_manager.approvals import Scope
from git_manager.rebasing.models import Run
from git_manager.rebasing.protocols import RunOperations
from git_manager.verification.models import TestResult
from git_manager.web.api_client import API_PREFIX, ApiClient, QueryParams
from git_manager.web.auth import Access
from git_manager.web.errors import ERROR_RESPONSES

RUNS_PATH = f"{API_PREFIX}/runs"
DEFAULT_LIMIT = 50

_RUN = TypeAdapter(Run)
_RUNS = TypeAdapter(tuple[Run, ...])
_TESTS = TypeAdapter(tuple[TestResult, ...])


def run_path(run_id: str, view: str | None = None) -> str:
    """The URL path of a run, or of one of its views (``diff``, ``tests``)."""
    path = f"{RUNS_PATH}/{quote(run_id, safe='')}"
    return path if view is None else f"{path}/{view}"


def runs_router(operations: RunOperations, *, access: Access) -> APIRouter:
    """Routes for ``RunOperations``; every one only reads."""
    router = APIRouter(
        tags=["runs"], responses=ERROR_RESPONSES, dependencies=[access.requires(Scope.READ)]
    )

    @router.get(RUNS_PATH)
    async def list_runs(branch: str | None = None, limit: int = DEFAULT_LIMIT) -> list[Run]:
        """The newest runs first, optionally of one branch (name or id)."""
        return list(await operations.list(branch=branch, limit=limit))

    @router.get(f"{RUNS_PATH}/{{run_id}}")
    async def get_run(run_id: str) -> Run:
        return await operations.get(run_id)

    @router.get(f"{RUNS_PATH}/{{run_id}}/diff", response_class=PlainTextResponse)
    async def run_diff(run_id: str) -> str:
        """The rebased branch against its new base, as ``git diff`` prints it."""
        return await operations.diff(run_id)

    @router.get(f"{RUNS_PATH}/{{run_id}}/tests")
    async def run_tests(run_id: str) -> list[TestResult]:
        return list(await operations.tests(run_id))

    return router


@dataclass(frozen=True, slots=True)
class HttpRunOperations:
    """``RunOperations`` through the REST API."""

    api: ApiClient

    async def list(self, *, branch: str | None = None, limit: int = DEFAULT_LIMIT) -> Sequence[Run]:
        """Return the newest runs first, optionally of one branch."""
        params: QueryParams = (
            {"limit": limit} if branch is None else {"limit": limit, "branch": branch}
        )
        return await self.api.get(RUNS_PATH, _RUNS, params=params)

    async def get(self, run_id: str) -> Run:
        """Return one run."""
        return await self.api.get(run_path(run_id), _RUN)

    async def diff(self, run_id: str) -> str:
        """Return the run's diff against its new base."""
        return await self.api.get_text(run_path(run_id, "diff"))

    async def tests(self, run_id: str) -> Sequence[TestResult]:
        """Return the run's verify results."""
        return await self.api.get(run_path(run_id, "tests"), _TESTS)
