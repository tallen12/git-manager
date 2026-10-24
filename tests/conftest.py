import builtins
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cyclopts import App
from pydantic import SecretStr

from git_manager.approvals import ApiToken, Scope, TokenAuthenticator, TokensFile
from git_manager.branches import BranchHeads, BranchState, TrackedBranch
from git_manager.cli.main import run
from git_manager.config import VerifyConfig
from git_manager.core import ConflictError, NotFoundError, Operations, Service
from git_manager.core.unavailable import UnavailableBranches, UnavailableConfig, UnavailableRuns
from git_manager.events import Event, EventDraft
from git_manager.health import HealthReporter, HealthService, StaticHealthReporter
from git_manager.rebasing import (
    LeaseRejected,
    Pushed,
    PushOutcome,
    RebaseCompleted,
    RebaseOutcome,
    Run,
    RunTrigger,
)
from git_manager.runtime import Command, ProcessCompleted, ProcessResult
from git_manager.verification import VerifyCommands, VerifyOutcome, VerifyPassed

TEST_VERSION = "0.0.0-test"
# Accepted by ``authenticator`` with every scope; send it with ``AUTH_HEADERS``.
TEST_TOKEN = "test-token-0123456789abcdef0123456789"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}"}
START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def run_cli(app: App, tokens: list[str]) -> int:
    """Run the CLI through its meta app, as ``git-manager`` does, and return the exit status."""
    try:
        run(app, tokens)
    except SystemExit as exit_:
        return exit_.code if isinstance(exit_.code, int) else 0
    return 0


def sha(number: int) -> str:
    """A distinct, valid-looking 40-digit commit hash for ``number``."""
    return f"{number:040x}"


def make_branch(**overrides: object) -> TrackedBranch:
    """A tracked branch with valid defaults; pass fields to override."""
    values: dict[str, object] = {
        "id": "branch-1",
        "repo_id": "repo",
        "name": "feature/one",
        "base": "main",
        "fork_point": sha(1),
        "last_base_sha": sha(1),
        "last_head_sha": sha(2),
    }
    return TrackedBranch.model_validate(values | overrides)


def make_run(**overrides: object) -> Run:
    """A finished, pushed run with valid defaults; pass fields to override."""
    values: dict[str, object] = {
        "id": "run-1",
        "branch_id": "branch-1",
        "trigger": RunTrigger.POLL,
        "base_from": sha(1),
        "base_to": sha(3),
        "heads": (BranchHeads(branch="feature/one", old_head=sha(2), new_head=sha(4)),),
        "outcome": BranchState.IDLE,
        "started_at": START,
        "finished_at": START + timedelta(minutes=5),
    }
    return Run.model_validate(values | overrides)


# --- Fakes for the shared protocols. Only a milestone's contracts feature edits these. ---


@dataclass(slots=True)
class FixedClock:
    """``Clock`` that stands still until a test advances it."""

    current: datetime = START

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


@dataclass(slots=True)
class SequentialIds:
    """``IdGenerator`` returning ``<prefix>-1``, ``<prefix>-2``, ..."""

    prefix: str = "id"
    issued: int = 0

    def new_id(self) -> str:
        self.issued += 1
        return f"{self.prefix}-{self.issued}"


def _exit_zero(_command: Command) -> ProcessResult:
    return ProcessCompleted(exit_code=0, stdout="", stderr="", duration=timedelta(0))


@dataclass(slots=True)
class FakeProcessRunner:
    """``ProcessRunner`` that records commands and answers with ``respond``."""

    respond: Callable[[Command], ProcessResult] = _exit_zero
    commands: list[Command] = field(default_factory=list)

    async def run(self, command: Command) -> ProcessResult:
        self.commands.append(command)
        return self.respond(command)


@dataclass(slots=True)
class FakeGit:
    """``Git`` over an in-memory remote.

    ``remote`` maps branch names to hashes; pushes check their lease against it, so a test
    can simulate a teammate's push by changing it. Rebase outcomes are scripted in order.
    """

    remote: dict[str, str] = field(default_factory=dict)
    rebase_outcomes: list[RebaseOutcome] = field(default_factory=list)
    merge_bases: dict[frozenset[str], str] = field(default_factory=dict)
    ancestry: set[tuple[str, str]] = field(default_factory=set)
    diffs: dict[tuple[str, str], str] = field(default_factory=dict)
    worktrees: dict[Path, str] = field(default_factory=dict)
    local_branches: dict[str, str] = field(default_factory=dict)
    fetched: list[tuple[str, ...]] = field(default_factory=list)
    aborted: list[Path] = field(default_factory=list)

    async def ls_remote(self, refs: Sequence[str]) -> Mapping[str, str]:
        return {ref: self.remote[ref] for ref in refs if ref in self.remote}

    async def fetch(self, refs: Sequence[str]) -> None:
        self.fetched.append(tuple(refs))

    async def merge_base(self, first: str, second: str) -> str:
        return self.merge_bases[frozenset({first, second})]

    async def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return ancestor == descendant or (ancestor, descendant) in self.ancestry

    async def add_worktree(self, path: Path, commit: str) -> None:
        if path in self.worktrees:
            msg = f"worktree already exists: {path}"
            raise AssertionError(msg)
        self.worktrees[path] = commit

    async def remove_worktree(self, path: Path) -> None:
        self.worktrees.pop(path, None)

    async def rebase_onto(
        self, worktree: Path, *, new_base: str, fork_point: str, rebase_merges: bool
    ) -> RebaseOutcome:
        if worktree not in self.worktrees:
            msg = f"no worktree at {worktree}"
            raise AssertionError(msg)
        if not self.rebase_outcomes:
            msg = f"no rebase outcome scripted for {new_base} onto {fork_point}"
            raise AssertionError(msg)
        outcome = self.rebase_outcomes.pop(0)
        if isinstance(outcome, RebaseCompleted):
            self.worktrees[worktree] = outcome.head
        return outcome

    async def abort_rebase(self, worktree: Path) -> None:
        self.aborted.append(worktree)

    async def push_with_lease(
        self, worktree: Path, *, branch: str, head: str, expected: str
    ) -> PushOutcome:
        if self.remote.get(branch) != expected:
            return LeaseRejected(expected=expected)
        self.remote[branch] = head
        return Pushed(head=head)

    async def create_branch(self, name: str, commit: str) -> None:
        self.local_branches[name] = commit

    async def diff(self, start: str, end: str) -> str:
        return self.diffs.get((start, end), "")


@dataclass(slots=True)
class InMemoryBranches:
    """``BranchRepository`` in a dict."""

    rows: dict[str, TrackedBranch] = field(default_factory=dict)

    async def add(self, branch: TrackedBranch) -> None:
        if branch.id in self.rows or await self.find(branch.name) is not None:
            msg = f"branch already tracked: {branch.name}"
            raise ConflictError(msg)
        self.rows[branch.id] = branch

    async def get(self, branch_id: str) -> TrackedBranch | None:
        return self.rows.get(branch_id)

    async def find(self, name: str) -> TrackedBranch | None:
        return next((row for row in self.rows.values() if row.name == name), None)

    async def list(self) -> Sequence[TrackedBranch]:
        return sorted(self.rows.values(), key=lambda row: row.name)

    async def update(self, branch: TrackedBranch) -> None:
        if branch.id not in self.rows:
            raise NotFoundError(kind="branch", key=branch.id)
        self.rows[branch.id] = branch

    async def remove(self, branch_id: str) -> None:
        if self.rows.pop(branch_id, None) is None:
            raise NotFoundError(kind="branch", key=branch_id)


@dataclass(slots=True)
class InMemoryRuns:
    """``RunRepository`` in a dict; insertion order stands in for start time."""

    rows: dict[str, Run] = field(default_factory=dict)

    async def add(self, run: Run) -> None:
        if run.id in self.rows:
            msg = f"run already exists: {run.id}"
            raise ConflictError(msg)
        self.rows[run.id] = run

    async def get(self, run_id: str) -> Run | None:
        return self.rows.get(run_id)

    async def list(self, *, branch_id: str | None = None, limit: int = 50) -> Sequence[Run]:
        runs = [row for row in self.rows.values() if branch_id in {None, row.branch_id}]
        return runs[::-1][:limit]

    async def update(self, run: Run) -> None:
        if run.id not in self.rows:
            raise NotFoundError(kind="run", key=run.id)
        self.rows[run.id] = run


@dataclass(slots=True)
class InMemoryEvents:
    """``EventRepository`` in a list."""

    # ``builtins``: the ``list`` method below shadows the type inside this class.
    rows: builtins.list[Event] = field(default_factory=builtins.list)

    async def append(self, draft: EventDraft, *, at: datetime) -> Event:
        event = Event(**draft.model_dump(), id=len(self.rows) + 1, at=at)
        self.rows.append(event)
        return event

    async def list(self, *, after: int = 0, limit: int = 100) -> Sequence[Event]:
        return [event for event in self.rows if event.id > after][:limit]


@dataclass(slots=True)
class RecordingEventSink:
    """``EventSink`` that records events in an ``InMemoryEvents`` log."""

    clock: FixedClock = field(default_factory=FixedClock)
    log: InMemoryEvents = field(default_factory=InMemoryEvents)

    @property
    def events(self) -> builtins.list[Event]:
        return self.log.rows

    async def emit(self, draft: EventDraft) -> Event:
        return await self.log.append(draft, at=self.clock.now())


@dataclass(frozen=True, slots=True)
class VerifyCall:
    """One call a ``FakeVerifier`` received."""

    worktree: Path
    commands: VerifyCommands
    config: VerifyConfig
    run_id: str


@dataclass(slots=True)
class FakeVerifier:
    """``Verifier`` that returns scripted outcomes (passing by default)."""

    outcomes: list[VerifyOutcome] = field(default_factory=list)
    calls: list[VerifyCall] = field(default_factory=list)

    async def verify(
        self, *, worktree: Path, commands: VerifyCommands, config: VerifyConfig, run_id: str
    ) -> VerifyOutcome:
        self.calls.append(VerifyCall(worktree, commands, config, run_id))
        return self.outcomes.pop(0) if self.outcomes else VerifyPassed(results=())


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """One request a ``RecordingApprovalGate`` received."""

    id: str
    run_id: str
    base_sha: str
    heads: tuple[BranchHeads, ...]


@dataclass(slots=True)
class RecordingApprovalGate:
    """``ApprovalGate`` that records each request and issues ``approval-N`` ids."""

    requests: list[ApprovalRequest] = field(default_factory=list)

    async def request(self, *, run_id: str, base_sha: str, heads: Sequence[BranchHeads]) -> str:
        approval_id = f"approval-{len(self.requests) + 1}"
        self.requests.append(ApprovalRequest(approval_id, run_id, base_sha, tuple(heads)))
        return approval_id


# --- Fixtures ---


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide the developer's global and system git config from every git call in tests.

    Hooks, signing and rebase defaults from ``~/.gitconfig`` would otherwise make git tests
    pass in CI and fail locally (or the reverse).
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture(autouse=True)
def isolated_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Hide every settings source the developer may have, so settings come only from tests.

    Clears ``GM_*`` variables and runs each test in an empty directory (no
    ``git-manager.yaml`` or ``.env``) with an empty secrets directory.
    """
    for name in [name for name in os.environ if name.startswith("GM_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
    monkeypatch.setenv("GM_SECRETS_DIR", str(tmp_path_factory.mktemp("secrets")))


@pytest.fixture
def authenticator() -> TokenAuthenticator:
    """Accepts ``TEST_TOKEN`` as ``operator`` with every scope."""
    entry = ApiToken(name="operator", token=SecretStr(TEST_TOKEN), scopes=frozenset(Scope))
    return TokenAuthenticator(TokensFile(tokens=(entry,)))


@pytest.fixture
def reporter() -> HealthReporter:
    return StaticHealthReporter(version=TEST_VERSION)


@pytest.fixture
def service(reporter: HealthReporter) -> Operations:
    """In-process operations; domains not built yet raise ``UnavailableError``."""
    reason = "not built in this test"
    return Service(
        health=HealthService(reporter=reporter),
        config=UnavailableConfig(reason),
        branches=UnavailableBranches(reason),
        runs=UnavailableRuns(reason),
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def ids() -> SequentialIds:
    return SequentialIds()


@pytest.fixture
def process_runner() -> FakeProcessRunner:
    return FakeProcessRunner()


@pytest.fixture
def git() -> FakeGit:
    return FakeGit()


@pytest.fixture
def branch_repository() -> InMemoryBranches:
    return InMemoryBranches()


@pytest.fixture
def run_repository() -> InMemoryRuns:
    return InMemoryRuns()


@pytest.fixture
def event_sink(clock: FixedClock) -> RecordingEventSink:
    return RecordingEventSink(clock=clock)


@pytest.fixture
def verifier() -> FakeVerifier:
    return FakeVerifier()


@pytest.fixture
def approval_gate() -> RecordingApprovalGate:
    return RecordingApprovalGate()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """An empty git repository with a deterministic identity and no signing."""
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    for key, value in (
        ("user.name", "Test User"),
        ("user.email", "test@example.com"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(["git", "-C", str(tmp_path), "config", key, value], check=True)
    return tmp_path
