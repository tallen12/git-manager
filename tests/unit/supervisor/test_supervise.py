import asyncio
import errno
import signal

import pytest

from git_manager.supervisor.errors import StartupError
from git_manager.supervisor.models import CapabilitySets
from git_manager.supervisor.settings import SOCKET_VARIABLE, SupervisorSettings
from git_manager.supervisor.supervise import (
    API_DIR_MODE,
    CLIENT_CERT_MODES,
    DATA_MODE,
    SECRETS_DIR_MODE,
    SUPERVISOR_SOCKET_MODE,
    Supervisor,
    exit_status,
)
from tests.unit.supervisor.conftest import (
    ADMIN_GID,
    GM,
    GM_TESTS,
    REQUIRED_MASK,
    FakeAccounts,
    FakeDaemonStarter,
    FixedCapabilities,
    OwnershipCall,
    RecordingOwnership,
    RecordingSocketServer,
)

CAP_SYS_ADMIN = 21
ENVIRON = {
    "PATH": "/app/.venv/bin:/usr/bin",
    "GM_TARGET__CONFIG": "/etc/git-manager/config.yaml",
    "GM_SUPERVISOR_OUTPUT_LIMIT_BYTES": "5",
    "HOME": "/root",
}


def _supervisor(
    settings: SupervisorSettings,
    *,
    ownership: RecordingOwnership | None = None,
    capabilities: FixedCapabilities | None = None,
    accounts: FakeAccounts | None = None,
    server: RecordingSocketServer | None = None,
    starter: FakeDaemonStarter | None = None,
) -> Supervisor:
    return Supervisor(
        settings=settings,
        accounts=accounts or FakeAccounts(),
        capabilities=capabilities or FixedCapabilities(),
        ownership=ownership or RecordingOwnership(),
        server=server or RecordingSocketServer(),
        daemon_starter=starter or FakeDaemonStarter(),
        environ=ENVIRON,
    )


def test_startup_sets_the_owners_from_the_isolation_table(
    supervisor_settings: SupervisorSettings,
) -> None:
    ownership = RecordingOwnership()

    users = _supervisor(supervisor_settings, ownership=ownership).prepare()

    assert users.daemon == GM
    assert ownership.calls == [
        OwnershipCall(
            "ensure_directory", supervisor_settings.data_root, GM.uid, GM.gid, mode=DATA_MODE
        ),
        OwnershipCall(
            "ensure_directory",
            supervisor_settings.api_socket_dir,
            GM.uid,
            ADMIN_GID,
            mode=API_DIR_MODE,
        ),
        OwnershipCall("ensure_directory", supervisor_settings.socket.parent, 0, 0, mode=0o755),
        OwnershipCall(
            "set_owner", supervisor_settings.secrets_dir, GM.uid, GM.gid, mode=SECRETS_DIR_MODE
        ),
        OwnershipCall(
            "hand_over",
            supervisor_settings.client_certs,
            GM_TESTS.uid,
            GM_TESTS.gid,
            modes=CLIENT_CERT_MODES,
        ),
    ]


def test_client_certificates_end_up_readable_only_by_gm_tests() -> None:
    assert CLIENT_CERT_MODES.file == 0o400
    assert CLIENT_CERT_MODES.directory == 0o500


def test_only_gm_may_enter_the_secrets_directory() -> None:
    assert SECRETS_DIR_MODE == 0o500


def test_missing_secrets_only_warn(
    supervisor_settings: SupervisorSettings, caplog: pytest.LogCaptureFixture
) -> None:
    ownership = RecordingOwnership(
        failures={supervisor_settings.secrets_dir: FileNotFoundError("gone")}
    )

    _supervisor(supervisor_settings, ownership=ownership).prepare()

    assert "no secrets directory" in caplog.text


def test_a_read_only_secrets_directory_stops_startup(
    supervisor_settings: SupervisorSettings,
) -> None:
    failure = OSError(errno.EROFS, "Read-only file system")
    ownership = RecordingOwnership(failures={supervisor_settings.secrets_dir: failure})

    with pytest.raises(StartupError, match="mount a tmpfs"):
        _supervisor(supervisor_settings, ownership=ownership).prepare()


def test_other_secrets_errors_propagate(supervisor_settings: SupervisorSettings) -> None:
    failure = PermissionError(errno.EPERM, "not permitted")
    ownership = RecordingOwnership(failures={supervisor_settings.secrets_dir: failure})

    with pytest.raises(PermissionError):
        _supervisor(supervisor_settings, ownership=ownership).prepare()


def test_startup_refuses_extra_capabilities(supervisor_settings: SupervisorSettings) -> None:
    wide = REQUIRED_MASK | 1 << CAP_SYS_ADMIN
    capabilities = FixedCapabilities(CapabilitySets(effective=wide, bounding=wide))
    ownership = RecordingOwnership()

    with pytest.raises(StartupError, match="extra \\[21\\]"):
        _supervisor(supervisor_settings, capabilities=capabilities, ownership=ownership).prepare()
    assert ownership.calls == []


def test_startup_refuses_an_image_without_its_users(
    supervisor_settings: SupervisorSettings,
) -> None:
    accounts = FakeAccounts(groups={})
    del accounts.users["gm-tests"]

    with pytest.raises(StartupError, match="gm-tests, group gm-admin"):
        _supervisor(supervisor_settings, accounts=accounts).prepare()


def test_missing_client_certificates_only_warn(
    supervisor_settings: SupervisorSettings, caplog: pytest.LogCaptureFixture
) -> None:
    ownership = RecordingOwnership(
        failures={supervisor_settings.client_certs: FileNotFoundError("gone")}
    )

    _supervisor(supervisor_settings, ownership=ownership).prepare()

    assert "no Docker client certificates" in caplog.text


def test_read_only_client_certificates_stop_startup(
    supervisor_settings: SupervisorSettings,
) -> None:
    failure = OSError(errno.EROFS, "Read-only file system")
    ownership = RecordingOwnership(failures={supervisor_settings.client_certs: failure})

    with pytest.raises(StartupError, match="mount it writable"):
        _supervisor(supervisor_settings, ownership=ownership).prepare()


def test_other_certificate_errors_propagate(supervisor_settings: SupervisorSettings) -> None:
    failure = PermissionError(errno.EPERM, "not permitted")
    ownership = RecordingOwnership(failures={supervisor_settings.client_certs: failure})

    with pytest.raises(PermissionError):
        _supervisor(supervisor_settings, ownership=ownership).prepare()


def test_the_daemon_gets_the_container_environment_as_gm(
    supervisor_settings: SupervisorSettings,
) -> None:
    env = _supervisor(supervisor_settings).daemon_env(GM)

    assert env == {
        "PATH": "/app/.venv/bin:/usr/bin",
        "GM_TARGET__CONFIG": "/etc/git-manager/config.yaml",
        "HOME": "/home/gm",
        "USER": "gm",
        "LOGNAME": "gm",
        SOCKET_VARIABLE: str(supervisor_settings.socket),
    }


async def test_run_serves_while_the_daemon_runs_and_returns_its_status(
    supervisor_settings: SupervisorSettings,
) -> None:
    server = RecordingSocketServer()
    starter = FakeDaemonStarter()
    ownership = RecordingOwnership()
    supervisor = _supervisor(
        supervisor_settings, server=server, starter=starter, ownership=ownership
    )

    running = asyncio.create_task(supervisor.run(("git-manager", "serve")))
    await starter.started.wait()
    assert server.open
    starter.daemon.exit_code = 3
    starter.daemon.exited.set()

    assert await running == 3
    assert not server.open
    assert server.served == [supervisor_settings.socket]
    [start] = starter.starts
    assert start.argv == ("git-manager", "serve")
    assert start.account == GM
    assert (
        OwnershipCall(
            "set_owner", supervisor_settings.socket, GM.uid, GM.gid, mode=SUPERVISOR_SOCKET_MODE
        )
        in ownership.calls
    )


async def test_a_stop_signal_reaches_the_daemon(supervisor_settings: SupervisorSettings) -> None:
    starter = FakeDaemonStarter()
    supervisor = _supervisor(supervisor_settings, starter=starter)

    running = asyncio.create_task(supervisor.run(("git-manager", "serve")))
    await starter.started.wait()
    supervisor.forward(signal.SIGTERM)

    assert await running == 128 + signal.SIGTERM
    assert starter.daemon.signals == [signal.SIGTERM]


async def test_a_stop_signal_before_startup_skips_the_daemon(
    supervisor_settings: SupervisorSettings,
) -> None:
    starter = FakeDaemonStarter()
    supervisor = _supervisor(supervisor_settings, starter=starter)

    supervisor.forward(signal.SIGINT)

    assert await supervisor.run(("git-manager", "serve")) == 128 + signal.SIGINT
    assert starter.starts == []


@pytest.mark.parametrize(("code", "status"), [(0, 0), (1, 1), (-15, 143)])
def test_exit_status_follows_the_shell_convention(code: int, status: int) -> None:
    assert exit_status(code) == status
