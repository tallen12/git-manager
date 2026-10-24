"""Fakes for the supervisor protocols, shared by its unit and integration tests."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from git_manager.isolation.models import SpawnCompleted
from git_manager.runtime import ProcessUser
from git_manager.supervisor.models import (
    Account,
    CapabilitySets,
    LaunchPlan,
    LaunchResult,
    OwnershipModes,
)
from git_manager.supervisor.policy import REQUIRED_CAPABILITIES
from git_manager.supervisor.settings import SupervisorSettings

GM = Account(name="gm", uid=10001, gid=10001, groups=(10001, 10000), home=Path("/home/gm"))
GM_CLAUDE = Account(
    name="gm-claude", uid=10002, gid=10002, groups=(10002,), home=Path("/home/gm-claude")
)
GM_TESTS = Account(
    name="gm-tests", uid=10003, gid=10003, groups=(10003,), home=Path("/home/gm-tests")
)
ADMIN_GID = 10000
REQUIRED_MASK = sum(1 << bit for bit in REQUIRED_CAPABILITIES)


@dataclass(slots=True)
class FakeAccounts:
    """``Accounts`` over fixed tables; defaults to the image's three users."""

    users: dict[str, Account] = field(
        default_factory=lambda: {account.name: account for account in (GM, GM_CLAUDE, GM_TESTS)}
    )
    groups: dict[str, int] = field(default_factory=lambda: {"gm-admin": ADMIN_GID})

    def user(self, name: str) -> Account | None:
        return self.users.get(name)

    def group_id(self, name: str) -> int | None:
        return self.groups.get(name)


@dataclass(frozen=True, slots=True)
class FixedPeers:
    """``PeerCredentials`` that reports the same uid for every connection."""

    uid: int = GM.uid

    def peer_uid(self, fd: int) -> int:
        return self.uid


@dataclass(frozen=True, slots=True)
class FixedCapabilities:
    """``Capabilities`` with fixed sets; defaults to exactly the required four."""

    sets: CapabilitySets = field(
        default_factory=lambda: CapabilitySets(effective=REQUIRED_MASK, bounding=REQUIRED_MASK)
    )

    def current(self) -> CapabilitySets:
        return self.sets


@dataclass(frozen=True, slots=True)
class OwnershipCall:
    """One call a ``RecordingOwnership`` received."""

    action: str
    path: Path
    uid: int
    gid: int
    mode: int | None = None
    modes: OwnershipModes | None = None


@dataclass(slots=True)
class RecordingOwnership:
    """``Ownership`` that records calls and raises ``failures[path]`` for that path.

    ``hand_over`` reports ``skipped`` as the hard-linked files it left alone.
    """

    calls: list[OwnershipCall] = field(default_factory=list)
    failures: dict[Path, Exception] = field(default_factory=dict)

    def _record(self, call: OwnershipCall) -> None:
        if (failure := self.failures.get(call.path)) is not None:
            raise failure
        self.calls.append(call)

    skipped: tuple[Path, ...] = ()

    def hand_over(
        self, path: Path, *, uid: int, gid: int, modes: OwnershipModes | None = None
    ) -> tuple[Path, ...]:
        self._record(OwnershipCall("hand_over", path, uid, gid, modes=modes))
        return self.skipped

    def set_owner(self, path: Path, *, uid: int, gid: int, mode: int) -> None:
        self._record(OwnershipCall("set_owner", path, uid, gid, mode=mode))

    def ensure_directory(self, path: Path, *, uid: int, gid: int, mode: int) -> None:
        self._record(OwnershipCall("ensure_directory", path, uid, gid, mode=mode))


def _exit_zero(_plan: LaunchPlan) -> LaunchResult:
    return SpawnCompleted(exit_code=0, stdout="", stderr="", duration_s=0)


@dataclass(slots=True)
class FakeLauncher:
    """``CommandLauncher`` that records plans and answers with ``respond``."""

    respond: Callable[[LaunchPlan], LaunchResult] = _exit_zero
    plans: list[LaunchPlan] = field(default_factory=list)

    async def run(self, plan: LaunchPlan) -> LaunchResult:
        self.plans.append(plan)
        return self.respond(plan)


@dataclass(slots=True)
class FakeDaemon:
    """``DaemonProcess`` that exits when told to, or on the first signal."""

    exit_code: int = 0
    signals: list[int] = field(default_factory=list)
    exited: asyncio.Event = field(default_factory=asyncio.Event)
    exit_on_signal: bool = True

    async def wait(self) -> int:
        await self.exited.wait()
        return self.exit_code

    def signal(self, number: int) -> None:
        self.signals.append(number)
        if self.exit_on_signal:
            self.exit_code = -number
            self.exited.set()


@dataclass(frozen=True, slots=True)
class DaemonStart:
    """One call a ``FakeDaemonStarter`` received."""

    argv: tuple[str, ...]
    account: Account
    env: Mapping[str, str]


@dataclass(slots=True)
class FakeDaemonStarter:
    """``DaemonStarter`` that hands out ``daemon``."""

    daemon: FakeDaemon = field(default_factory=FakeDaemon)
    starts: list[DaemonStart] = field(default_factory=list)
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def start(
        self, argv: tuple[str, ...], *, account: Account, env: Mapping[str, str]
    ) -> FakeDaemon:
        self.starts.append(DaemonStart(argv, account, dict(env)))
        self.started.set()
        return self.daemon


@dataclass(slots=True)
class RecordingSocketServer:
    """``SocketServer`` that only records where and whether it is serving."""

    served: list[Path] = field(default_factory=list)
    open: bool = False

    @contextlib.asynccontextmanager
    async def serving(self, path: Path) -> AsyncGenerator[None]:
        self.served.append(path)
        self.open = True
        try:
            yield
        finally:
            self.open = False


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    (root / "runs" / "run-1").mkdir(parents=True)
    return root


@pytest.fixture
def supervisor_settings(data_root: Path, tmp_path: Path) -> SupervisorSettings:
    return SupervisorSettings(
        socket=tmp_path / "supervisor" / "supervisor.sock",
        data_root=data_root,
        client_certs=tmp_path / "certs" / "client",
        secrets_dir=tmp_path / "secrets",
        api_socket_dir=tmp_path / "git-manager",
        output_limit_bytes=1024,
    )


@pytest.fixture
def worktree(data_root: Path) -> Path:
    return data_root / "runs" / "run-1"


def users_by_process_user() -> dict[ProcessUser, Account]:
    """The default accounts keyed by the user a command asks for."""
    return {
        ProcessUser.ORCHESTRATOR: GM,
        ProcessUser.CLAUDE: GM_CLAUDE,
        ProcessUser.TESTS: GM_TESTS,
    }
