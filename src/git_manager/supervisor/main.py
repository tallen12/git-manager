"""Composition root for ``git-manager-supervisor``, the container's entry point.

``tini`` is PID 1 and reaps orphans; it starts this process as root with only the four
capabilities the supervisor keeps. Arguments are the daemon's command line.
"""

import asyncio
import logging
import os
import signal
import sys
from collections.abc import Mapping, Sequence

from git_manager.supervisor.errors import StartupError
from git_manager.supervisor.handler import RequestHandler
from git_manager.supervisor.launcher import SubprocessDaemonStarter, SubprocessLauncher
from git_manager.supervisor.linux import ProcCapabilities, SoPeerCredentials
from git_manager.supervisor.server import SupervisorServer
from git_manager.supervisor.settings import SupervisorSettings
from git_manager.supervisor.supervise import Supervisor
from git_manager.supervisor.system import OsOwnership, PasswdAccounts

logger = logging.getLogger(__name__)

DEFAULT_DAEMON_ARGV = ("git-manager", "serve")
FORWARDED_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
# -I: the command's environment must not steer the helper's Python.
ENTER_COMMAND = (sys.executable, "-I", "-m", "git_manager.supervisor.enter")
STARTUP_FAILED = 1
WRONG_PLATFORM = 2


def build_supervisor(settings: SupervisorSettings, environ: Mapping[str, str]) -> Supervisor:
    """The supervisor wired with the container adapters."""
    accounts = PasswdAccounts()
    ownership = OsOwnership()
    handler = RequestHandler(
        settings=settings,
        accounts=accounts,
        ownership=ownership,
        launcher=SubprocessLauncher(entry=ENTER_COMMAND),
    )
    return Supervisor(
        settings=settings,
        accounts=accounts,
        capabilities=ProcCapabilities(),
        ownership=ownership,
        server=SupervisorServer(handler=handler, peers=SoPeerCredentials()),
        daemon_starter=SubprocessDaemonStarter(),
        environ=environ,
    )


async def _supervise(supervisor: Supervisor, daemon_argv: tuple[str, ...]) -> int:
    loop = asyncio.get_running_loop()
    for number in FORWARDED_SIGNALS:
        loop.add_signal_handler(number, supervisor.forward, number)
    return await supervisor.run(daemon_argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the supervisor until the daemon exits, then exit with the daemon's status."""
    logging.basicConfig(level=logging.INFO, format="supervisor: %(levelname)s %(message)s")
    daemon_argv = tuple(sys.argv[1:] if argv is None else argv) or DEFAULT_DAEMON_ARGV
    if sys.platform != "linux":
        logger.error("the supervisor runs only in the Linux container")
        raise SystemExit(WRONG_PLATFORM)
    supervisor = build_supervisor(SupervisorSettings.from_environ(os.environ), os.environ)
    try:
        status = asyncio.run(_supervise(supervisor, daemon_argv))
    except StartupError as error:
        logger.error("cannot start: %s", error)
        raise SystemExit(STARTUP_FAILED) from error
    raise SystemExit(status)
