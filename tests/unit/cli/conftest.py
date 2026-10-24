"""Helpers used only by the CLI tests."""

import builtins
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from cyclopts import App

from git_manager.branches import BranchState, Reason, RepoStatus, TrackedBranch
from git_manager.branches.results import SyncCompleted, SyncOutcome
from git_manager.cli.main import build_app
from git_manager.config import YamlConfigFile
from git_manager.core import (
    LocalTarget,
    NotFoundError,
    Service,
    UnavailableError,
    build_connector,
)
from git_manager.core.compose import LocalRuntime
from git_manager.core.unavailable import UnavailableConfig, UnavailableEvents
from git_manager.health import HealthStatus
from git_manager.rebasing import Run
from git_manager.verification import TestResult
from tests.conftest import TEST_VERSION, make_branch, make_run
from tests.unit.config.conftest import StaticRepoConfig


def read_config(path: Path) -> YamlConfigFile:
    """Open a config file with no ``GM_*`` overrides and no repo ``.git-manager.yaml``."""
    return YamlConfigFile(path, environ={}, repo_config=StaticRepoConfig())


@dataclass(slots=True)
class FakeBranchOperations:
    """``BranchOperations`` over a dict of branches; ``error`` makes every call raise it."""

    branches: dict[str, TrackedBranch] = field(default_factory=dict)
    sync_outcome: SyncOutcome = field(default_factory=lambda: SyncCompleted(run=make_run()))
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def _get(self, operation: str, branch: str) -> TrackedBranch:
        self.calls.append(f"{operation} {branch}")
        if self.error is not None:
            raise self.error
        if branch not in self.branches:
            raise NotFoundError(kind="branch", key=branch)
        return self.branches[branch]

    async def status(self) -> RepoStatus:
        self.calls.append("status")
        return RepoStatus(repo_id="repo", url="u", branches=tuple(self.branches.values()))

    async def track(self, *, name: str, base: str) -> TrackedBranch:
        self.calls.append(f"track {name} {base}")
        branch = make_branch(name=name, base=base)
        self.branches[name] = branch
        return branch

    async def untrack(self, branch: str) -> None:
        del self.branches[self._get("untrack", branch).name]

    async def sync(self, branch: str) -> SyncOutcome:
        self._get("sync", branch)
        return self.sync_outcome

    async def pause(self, branch: str) -> TrackedBranch:
        found = self._get("pause", branch)
        return found.model_copy(
            update={"state": BranchState.PAUSED, "reason": Reason.PAUSED_BY_USER}
        )

    async def resume(self, branch: str) -> TrackedBranch:
        return self._get("resume", branch).model_copy(update={"state": BranchState.IDLE})


@dataclass(slots=True)
class FakeRunOperations:
    """``RunOperations`` over a list of runs, newest first."""

    # ``builtins``: the ``list`` method below shadows the type inside this class.
    runs: builtins.list[Run] = field(default_factory=builtins.list)
    diffs: dict[str, str] = field(default_factory=dict)

    async def list(self, *, branch: str | None = None, limit: int = 50) -> Sequence[Run]:
        return [run for run in self.runs if branch in {None, run.branch_id}][:limit]

    async def get(self, run_id: str) -> Run:
        found = next((run for run in self.runs if run.id == run_id), None)
        if found is None:
            raise NotFoundError(kind="run", key=run_id)
        return found

    async def diff(self, run_id: str) -> str:
        await self.get(run_id)
        return self.diffs.get(run_id, "")

    async def tests(self, run_id: str) -> Sequence[TestResult]:
        return (await self.get(run_id)).tests


def no_runtime(target: LocalTarget) -> AbstractAsyncContextManager[LocalRuntime]:
    """A ``RuntimeOpener`` for tests that never start ``serve``."""
    msg = f"serve is not started in this test: {target.config}"
    raise AssertionError(msg)


def operations_app(
    *, branches: FakeBranchOperations | None = None, runs: FakeRunOperations | None = None
) -> App:
    """The CLI serving the given fakes in local mode; other domains are unavailable."""
    reason = "not built in this test"
    service = Service(
        health=UnavailableHealth(reason),
        config=UnavailableConfig(reason),
        branches=branches or FakeBranchOperations(),
        runs=runs or FakeRunOperations(),
        events=UnavailableEvents(reason),
    )
    return build_app(
        open_runtime=no_runtime,
        read_config=read_config,
        connect=build_connector(local=lambda _target: nullcontext(service)),
        version=TEST_VERSION,
    )


@dataclass(frozen=True, slots=True)
class UnavailableHealth:
    """``HealthOperations`` that is not built in these tests."""

    reason: str

    async def status(self) -> HealthStatus:
        raise UnavailableError("doctor", reason=self.reason)


@pytest.fixture
def config_target(tmp_path: Path) -> list[str]:
    """Flags selecting local mode with an existing (unread) config file."""
    path = tmp_path / "config.yaml"
    path.write_text("repo: {url: u}\n", encoding="utf-8")
    return ["--config", str(path)]
