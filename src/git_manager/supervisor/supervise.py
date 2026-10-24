"""Supervisor lifecycle: check the container, prepare ownership, serve, run the daemon."""

import asyncio
import errno
import logging
from collections.abc import Mapping
from dataclasses import dataclass

from git_manager.runtime import ProcessUser
from git_manager.supervisor.errors import StartupError
from git_manager.supervisor.models import (
    Account,
    CapabilitiesOk,
    CapabilitiesWrong,
    OwnershipModes,
)
from git_manager.supervisor.policy import check_capabilities
from git_manager.supervisor.protocols import (
    Accounts,
    Capabilities,
    DaemonProcess,
    DaemonStarter,
    Ownership,
    SocketServer,
)
from git_manager.supervisor.settings import ENV_PREFIX, SOCKET_VARIABLE, SupervisorSettings

logger = logging.getLogger(__name__)

ADMIN_GROUP = "gm-admin"
ROOT_UID = 0
# /data: gm owns it; other users may only pass through to the worktree handed to them.
DATA_MODE = 0o711
# Operators reach the API socket through the gm-admin group (Process isolation).
API_DIR_MODE = 0o750
SUPERVISOR_DIR_MODE = 0o755
SUPERVISOR_SOCKET_MODE = 0o600
CLIENT_CERT_MODES = OwnershipModes(directory=0o500, file=0o400)
# Compose file secrets are bind mounts that keep the host's (often world-readable) modes,
# so the directory holding them is what keeps gm-claude and gm-tests out.
SECRETS_DIR_MODE = 0o500
# Shell convention for "terminated by signal N".
SIGNAL_EXIT_BASE = 128


@dataclass(frozen=True, slots=True)
class ContainerUsers:
    """The accounts the supervisor works with, looked up once at startup."""

    daemon: Account
    claude: Account
    tests: Account
    admin_group: int


def exit_status(code: int) -> int:
    """A process exit status for the daemon's return code (negative means a signal)."""
    return SIGNAL_EXIT_BASE - code if code < 0 else code


class Supervisor:
    """Runs the daemon as ``gm`` and serves its requests until it exits."""

    def __init__(
        self,
        *,
        settings: SupervisorSettings,
        accounts: Accounts,
        capabilities: Capabilities,
        ownership: Ownership,
        server: SocketServer,
        daemon_starter: DaemonStarter,
        environ: Mapping[str, str],
    ) -> None:
        self._settings = settings
        self._accounts = accounts
        self._capabilities = capabilities
        self._ownership = ownership
        self._server = server
        self._daemon_starter = daemon_starter
        self._environ = environ
        self._daemon: DaemonProcess | None = None
        self._stop_signal: int | None = None

    def prepare(self) -> ContainerUsers:
        """Check capabilities and users, then set the owners the isolation table needs.

        Raises ``StartupError`` when the container is not set up as the image defines it.
        """
        match check_capabilities(self._capabilities.current()):
            case CapabilitiesOk():
                pass
            case CapabilitiesWrong(missing=missing, extra=extra):
                msg = (
                    "the supervisor must hold exactly CAP_CHOWN, CAP_KILL, CAP_SETGID and "
                    f"CAP_SETUID (missing {sorted(missing)}, extra {sorted(extra)}); run "
                    "with cap_drop ALL and cap_add for those four"
                )
                raise StartupError(msg)
        users = self._users()
        settings = self._settings
        self._ownership.ensure_directory(
            settings.data_root, uid=users.daemon.uid, gid=users.daemon.gid, mode=DATA_MODE
        )
        self._ownership.ensure_directory(
            settings.api_socket_dir,
            uid=users.daemon.uid,
            gid=users.admin_group,
            mode=API_DIR_MODE,
        )
        self._ownership.ensure_directory(
            settings.socket.parent, uid=ROOT_UID, gid=ROOT_UID, mode=SUPERVISOR_DIR_MODE
        )
        self._secure_secrets(users.daemon)
        self._secure_client_certs(users.tests)
        return users

    def _users(self) -> ContainerUsers:
        accounts = {user: self._accounts.user(user) for user in ProcessUser}
        admin_group = self._accounts.group_id(ADMIN_GROUP)
        missing = [str(user) for user, account in accounts.items() if account is None]
        if admin_group is None:
            missing.append(f"group {ADMIN_GROUP}")
        daemon = accounts[ProcessUser.ORCHESTRATOR]
        claude = accounts[ProcessUser.CLAUDE]
        tests = accounts[ProcessUser.TESTS]
        if daemon is None or claude is None or tests is None or admin_group is None:
            msg = f"missing from the image: {', '.join(missing)}"
            raise StartupError(msg)
        return ContainerUsers(daemon=daemon, claude=claude, tests=tests, admin_group=admin_group)

    def _secure_secrets(self, daemon: Account) -> None:
        secrets = self._settings.secrets_dir
        try:
            self._ownership.set_owner(
                secrets, uid=daemon.uid, gid=daemon.gid, mode=SECRETS_DIR_MODE
            )
        except FileNotFoundError:
            logger.warning("no secrets directory at %s", secrets)
        except OSError as error:
            if error.errno != errno.EROFS:
                raise
            msg = f"{secrets} is read-only; mount a tmpfs there so only gm can enter it"
            raise StartupError(msg) from error

    def _secure_client_certs(self, tests: Account) -> None:
        certs = self._settings.client_certs
        try:
            self._ownership.hand_over(certs, uid=tests.uid, gid=tests.gid, modes=CLIENT_CERT_MODES)
        except FileNotFoundError:
            logger.warning("no Docker client certificates at %s; tests get no Docker", certs)
        except OSError as error:
            if error.errno != errno.EROFS:
                raise
            msg = f"{certs} is mounted read-only; mount it writable so it can go to gm-tests"
            raise StartupError(msg) from error

    def daemon_env(self, daemon: Account) -> dict[str, str]:
        """The container's environment minus supervisor settings, plus gm's identity."""
        env = {
            name: value for name, value in self._environ.items() if not name.startswith(ENV_PREFIX)
        }
        env |= {
            "HOME": str(daemon.home),
            "USER": daemon.name,
            "LOGNAME": daemon.name,
            SOCKET_VARIABLE: str(self._settings.socket),
        }
        return env

    def forward(self, number: int) -> None:
        """Pass a stop signal to the daemon, or skip starting it if it is not up yet."""
        if self._daemon is None:
            self._stop_signal = number
        else:
            self._daemon.signal(number)

    async def run(self, daemon_argv: tuple[str, ...]) -> int:
        """Prepare, serve the socket and run the daemon; return its exit status."""
        users = await asyncio.to_thread(self.prepare)
        socket = self._settings.socket
        async with self._server.serving(socket):
            await asyncio.to_thread(
                self._ownership.set_owner,
                socket,
                uid=users.daemon.uid,
                gid=users.daemon.gid,
                mode=SUPERVISOR_SOCKET_MODE,
            )
            if self._stop_signal is not None:
                return SIGNAL_EXIT_BASE + self._stop_signal
            self._daemon = await self._daemon_starter.start(
                daemon_argv, account=users.daemon, env=self.daemon_env(users.daemon)
            )
            if self._stop_signal is not None:
                self._daemon.signal(self._stop_signal)
            return exit_status(await self._daemon.wait())
