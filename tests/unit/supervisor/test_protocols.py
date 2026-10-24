from pathlib import Path

import pytest

from git_manager.isolation.models import SpawnCompleted
from git_manager.supervisor.handler import RequestHandler
from git_manager.supervisor.models import LaunchPlan, OwnershipModes
from git_manager.supervisor.protocols import (
    Accounts,
    Capabilities,
    CommandLauncher,
    DaemonStarter,
    Ownership,
    PeerCredentials,
    RequestAnswerer,
    SocketServer,
)
from git_manager.supervisor.server import SupervisorServer
from git_manager.supervisor.settings import SupervisorSettings
from tests.unit.supervisor.conftest import (
    GM,
    GM_TESTS,
    REQUIRED_MASK,
    FakeAccounts,
    FakeDaemonStarter,
    FakeLauncher,
    FixedCapabilities,
    FixedPeers,
    OwnershipCall,
    RecordingOwnership,
    RecordingSocketServer,
)


def test_fake_accounts_hold_the_image_users() -> None:
    accounts: Accounts = FakeAccounts()

    assert accounts.user("gm") == GM
    assert accounts.user("root") is None
    assert accounts.group_id("gm-admin") == 10000


def test_fixed_peers_and_capabilities_answer_as_configured() -> None:
    peers: PeerCredentials = FixedPeers(uid=7)
    capabilities: Capabilities = FixedCapabilities()

    assert peers.peer_uid(3) == 7
    assert capabilities.current().effective == REQUIRED_MASK


def test_recording_ownership_records_or_fails_per_path(tmp_path: Path) -> None:
    fake = RecordingOwnership(failures={tmp_path / "bad": PermissionError("no")})
    ownership: Ownership = fake

    ownership.hand_over(tmp_path, uid=1, gid=2, modes=OwnershipModes(file=0o400))

    assert fake.calls == [
        OwnershipCall("hand_over", tmp_path, 1, 2, modes=OwnershipModes(file=0o400))
    ]
    with pytest.raises(PermissionError):
        ownership.set_owner(tmp_path / "bad", uid=1, gid=1, mode=0o600)
    assert len(fake.calls) == 1


async def test_fake_launcher_records_plans(tmp_path: Path) -> None:
    fake = FakeLauncher()
    launcher: CommandLauncher = fake
    plan = LaunchPlan(
        argv=("true",),
        cwd=tmp_path,
        env={},
        account=GM_TESTS,
        timeout=None,
        stdin=None,
        output_limit_bytes=1,
    )

    reply = await launcher.run(plan)

    assert isinstance(reply, SpawnCompleted)
    assert fake.plans == [plan]


async def test_fake_daemon_exits_on_a_signal() -> None:
    fake = FakeDaemonStarter()
    starter: DaemonStarter = fake

    daemon = await starter.start(("git-manager", "serve"), account=GM, env={"A": "b"})
    daemon.signal(15)

    assert await daemon.wait() == -15
    assert fake.starts[0].env == {"A": "b"}


async def test_recording_socket_server_is_open_only_inside_its_context(tmp_path: Path) -> None:
    fake = RecordingSocketServer()
    server: SocketServer = fake

    async with server.serving(tmp_path / "s.sock"):
        assert fake.open
    assert not fake.open
    assert fake.served == [tmp_path / "s.sock"]


def test_the_handler_and_server_satisfy_their_protocols(
    supervisor_settings: SupervisorSettings,
) -> None:
    handler: RequestAnswerer = RequestHandler(
        settings=supervisor_settings,
        accounts=FakeAccounts(),
        ownership=RecordingOwnership(),
        launcher=FakeLauncher(),
    )
    server: SocketServer = SupervisorServer(handler=handler, peers=FixedPeers())

    assert isinstance(server, SupervisorServer)
