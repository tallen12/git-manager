"""The ``Operations`` contract: ``Service`` and ``HttpOperations`` over REST behave alike.

Every test runs once in process and once through the REST app with ``HttpOperations``, and
checks the same results and the same typed errors with the same messages, so the CLI
prints the same thing in both modes.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from git_manager.approvals import Authenticator
from git_manager.branches import BranchState, TrackedBranch
from git_manager.branches.results import SyncCompleted, SyncOutcome
from git_manager.branches.service import BranchService
from git_manager.config import ConfigError, ConfigService, YamlConfigFile
from git_manager.core import (
    ConflictError,
    HttpOperations,
    NotFoundError,
    OperationError,
    Operations,
    Service,
    UnavailableError,
)
from git_manager.core.unavailable import UnavailableEvents
from git_manager.health import HealthService, HealthStatus, StaticHealthReporter
from git_manager.rebasing.locks import InMemoryBranchLocks
from git_manager.rebasing.service import RunService
from git_manager.verification import StepOutcome, TestResult, VerifyStep
from git_manager.web.app import create_app
from tests.conftest import (
    AUTH_HEADERS,
    TEST_VERSION,
    FakeGit,
    InMemoryBranches,
    InMemoryRuns,
    RecordingEventSink,
    SequentialIds,
    make_branch,
    make_run,
    sha,
)
from tests.unit.config.conftest import StaticRepoConfig

type Implementation = Callable[[Operations, Authenticator], AbstractAsyncContextManager[Operations]]

EXPECTED = HealthStatus(status="ok", version=TEST_VERSION)
# On the remote, ``main`` is at BASE and ``feature/one`` at HEAD; they fork at FORK.
FORK, HEAD, BASE = sha(1), sha(2), sha(3)
CONFIG = "# the operator's notes\nrepo:\n  url: https://example.com/repo.git\n"
RESULT = TestResult(
    step=VerifyStep.TEST,
    command="just test",
    outcome=StepOutcome.FAILED,
    exit_code=1,
    attempts=2,
    duration_s=3.0,
    output_tail="1 failed\n",
)


@asynccontextmanager
async def in_process(
    service: Operations, _authenticator: Authenticator
) -> AsyncGenerator[Operations]:
    yield service


@asynccontextmanager
async def over_rest(
    service: Operations, authenticator: Authenticator
) -> AsyncGenerator[Operations]:
    app = create_app(operations=service, version=TEST_VERSION, authenticator=authenticator)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        yield HttpOperations(client)


IMPLEMENTATIONS = pytest.mark.parametrize(
    "implementation", [in_process, over_rest], ids=["service", "http"]
)


@dataclass(slots=True)
class FinishedSync:
    """``BranchSyncer`` that reports a finished run for each branch it is asked to sync."""

    synced: list[str] = field(default_factory=list)

    async def sync(self, branch: TrackedBranch) -> SyncOutcome:
        self.synced.append(branch.name)
        return SyncCompleted(run=make_run(id="manual-run", branch_id=branch.id))


@dataclass(frozen=True, slots=True)
class Harness:
    """A ``Service`` over the shared fakes and a real config file, and those fakes."""

    service: Service
    config_file: Path
    git: FakeGit
    branches: InMemoryBranches
    runs: InMemoryRuns
    syncer: FinishedSync


@pytest.fixture
def harness(
    tmp_path: Path,
    reporter: StaticHealthReporter,
    git: FakeGit,
    branch_repository: InMemoryBranches,
    run_repository: InMemoryRuns,
) -> Harness:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(CONFIG, encoding="utf-8")
    config = ConfigService(YamlConfigFile(config_file, environ={}, repo_config=StaticRepoConfig()))
    git.remote.update({"main": BASE, "feature/one": HEAD})
    git.merge_bases[frozenset({BASE, HEAD})] = FORK
    syncer = FinishedSync()
    service = Service(
        health=HealthService(reporter=reporter),
        config=config,
        branches=BranchService(
            repo_id="repo",
            config=config,
            git=git,
            branches=branch_repository,
            syncer=syncer,
            events=RecordingEventSink(),
            locks=InMemoryBranchLocks(),
            ids=SequentialIds(prefix="branch"),
        ),
        runs=RunService(runs=run_repository, branches=branch_repository, git=git),
        # The stream has no API client until F12b, so it has no shared contract yet.
        events=UnavailableEvents("not built in this test"),
    )
    return Harness(service, config_file, git, branch_repository, run_repository, syncer)


async def raised(call: Callable[[], Awaitable[object]]) -> OperationError:
    """The operation error ``call`` raises; fails the test if it returns."""
    with pytest.raises(OperationError) as error:
        await call()
    return error.value


@IMPLEMENTATIONS
async def test_operations_contract_health(
    service: Operations, authenticator: Authenticator, implementation: Implementation
) -> None:
    async with implementation(service, authenticator) as operations:
        assert await operations.health.status() == EXPECTED


@IMPLEMENTATIONS
async def test_operations_contract_unavailable_domain(
    service: Operations, authenticator: Authenticator, implementation: Implementation
) -> None:
    # ``service`` leaves the branches unbuilt: their stand-in's error survives REST.
    async with implementation(service, authenticator) as operations:
        error = await raised(operations.branches.status)

    assert isinstance(error, UnavailableError)
    assert (error.operation, error.reason) == ("status", "not built in this test")


@IMPLEMENTATIONS
async def test_operations_contract_config(
    harness: Harness, authenticator: Authenticator, implementation: Implementation
) -> None:
    async with implementation(harness.service, authenticator) as operations:
        shown = await operations.config.show()
        updated = await operations.config.set(("defaults", "cadence", "mode"), "manual")
        invalid = await raised(lambda: operations.config.set(("budget", "daily_usd"), 0))
        empty = await raised(lambda: operations.config.set((), 1))

    assert shown.repo.url == "https://example.com/repo.git"
    assert updated.defaults.cadence.mode == "manual"
    assert harness.config_file.read_text(encoding="utf-8").startswith("# the operator's notes")
    assert isinstance(invalid, ConfigError)
    assert invalid.source == str(harness.config_file)
    assert invalid.problems[0].startswith("budget.daily_usd: ")
    assert isinstance(empty, ConfigError)
    assert empty.problems == ("(root): name the key to set",)


@IMPLEMENTATIONS
async def test_operations_contract_branch_lifecycle(
    harness: Harness, authenticator: Authenticator, implementation: Implementation
) -> None:
    async with implementation(harness.service, authenticator) as operations:
        tracked = await operations.branches.track(name="feature/one", base="main")
        status = await operations.branches.status()
        paused = await operations.branches.pause("feature/one")
        refused = await raised(lambda: operations.branches.sync("feature/one"))
        resumed = await operations.branches.resume(tracked.id)
        synced = await operations.branches.sync("feature/one")
        await operations.branches.untrack("feature/one")
        after = await operations.branches.status()

    assert tracked == make_branch(id="branch-1", fork_point=FORK, last_base_sha=FORK)
    assert status.url == "https://example.com/repo.git"
    assert status.branches == (tracked,)
    assert paused.state is BranchState.PAUSED
    assert isinstance(refused, ConflictError)
    assert str(refused) == "cannot sync feature/one: it is paused; resume it first"
    assert resumed.state is BranchState.IDLE
    assert synced == SyncCompleted(run=make_run(id="manual-run", branch_id="branch-1"))
    assert harness.syncer.synced == ["feature/one"]
    assert after.branches == ()


@IMPLEMENTATIONS
async def test_operations_contract_branch_errors(
    harness: Harness, authenticator: Authenticator, implementation: Implementation
) -> None:
    async with implementation(harness.service, authenticator) as operations:
        await operations.branches.track(name="feature/one", base="main")
        twice = await raised(lambda: operations.branches.track(name="feature/one", base="main"))
        missing_remote = await raised(lambda: operations.branches.track(name="gone", base="main"))
        unknown = [
            await raised(lambda: operations.branches.untrack("nope")),
            await raised(lambda: operations.branches.sync("nope")),
            await raised(lambda: operations.branches.pause("nope")),
            await raised(lambda: operations.branches.resume("nope")),
        ]
        await operations.branches.pause("feature/one")
        await operations.branches.resume("feature/one")
        not_stopped = await raised(lambda: operations.branches.resume("feature/one"))

    assert isinstance(twice, ConflictError)
    assert str(twice) == "branch already tracked: feature/one"
    assert isinstance(missing_remote, NotFoundError)
    assert (missing_remote.kind, missing_remote.key) == ("remote branch", "gone")
    for error in unknown:
        assert isinstance(error, NotFoundError)
        assert str(error) == "branch not found: nope"
    assert isinstance(not_stopped, ConflictError)
    assert str(not_stopped) == "cannot resume feature/one: it is idle, not paused or stopped"


@IMPLEMENTATIONS
async def test_operations_contract_runs(
    harness: Harness, authenticator: Authenticator, implementation: Implementation
) -> None:
    await harness.branches.add(make_branch())
    harness.git.diffs[(sha(3), sha(4))] = "diff --git a/x b/x\n"
    first = make_run(id="run-1", tests=(RESULT,))
    other = make_run(id="run-2", branch_id="branch-2")
    unpushed = make_run(
        id="run-3",
        heads=(make_run().heads[0].model_copy(update={"new_head": None}),),
        outcome=BranchState.NEEDS_HUMAN,
    )
    for run in (first, other, unpushed):
        await harness.runs.add(run)

    async with implementation(harness.service, authenticator) as operations:
        every = await operations.runs.list()
        by_name = await operations.runs.list(branch="feature/one")
        limited = await operations.runs.list(limit=1)
        shown = await operations.runs.get("run-1")
        diff = await operations.runs.diff("run-1")
        tests = await operations.runs.tests("run-1")
        no_head = await raised(lambda: operations.runs.diff("run-3"))
        unknown = [
            await raised(lambda: operations.runs.get("nope")),
            await raised(lambda: operations.runs.diff("nope")),
            await raised(lambda: operations.runs.tests("nope")),
        ]

    assert [run.id for run in every] == ["run-3", "run-2", "run-1"]
    assert [run.id for run in by_name] == ["run-3", "run-1"]
    assert [run.id for run in limited] == ["run-3"]
    assert shown == first
    assert diff == "diff --git a/x b/x\n"
    assert list(tests) == [RESULT]
    assert isinstance(no_head, ConflictError)
    assert str(no_head) == "run run-3 has no rebased head to diff (it ended needs_human)"
    for error in unknown:
        assert isinstance(error, NotFoundError)
        assert str(error) == "run not found: nope"
