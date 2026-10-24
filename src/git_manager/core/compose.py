"""Shared wiring for processes that own a data directory: local-mode commands and ``serve``.

``open_local`` builds every in-process implementation from a ``LocalTarget``. It is a
composition root: the only place, with the CLI's ``main``, that constructs concrete
infrastructure. The daemon reuses it and adds its poller and run queue on top.
"""

import asyncio
import shlex
from collections.abc import AsyncGenerator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol, assert_never

from git_manager.approvals.gate import UnrecordedApprovalGate
from git_manager.branches.protocols import BranchSyncer
from git_manager.branches.queue import FifoRunQueue
from git_manager.branches.service import BranchService
from git_manager.branches.sync import ForegroundSync, QueuedSync, SyncMode
from git_manager.config.file import YamlConfigFile
from git_manager.config.models import RepoConfig
from git_manager.config.protocols import RepoConfigSource
from git_manager.config.repo_file import CLONE_DIR
from git_manager.config.service import ConfigService
from git_manager.core.service import Service
from git_manager.core.targets import LocalTarget
from git_manager.events.bus import EventBus
from git_manager.events.protocols import EventHistory
from git_manager.events.stream import EventStreamService
from git_manager.health.reporters import StaticHealthReporter
from git_manager.health.service import HealthService
from git_manager.isolation.channel import DEFAULT_SOCKET, UnixSocketSupervisorChannel
from git_manager.isolation.local import LocalProcessRunner
from git_manager.isolation.supervised import SupervisedProcessRunner
from git_manager.rebasing.git import SubprocessGit
from git_manager.rebasing.locks import InMemoryBranchLocks
from git_manager.rebasing.protocols import Git, RunExecutor
from git_manager.rebasing.runner import RebaseRunner
from git_manager.rebasing.service import RunService
from git_manager.runtime.protocols import Clock, ProcessRunner
from git_manager.runtime.system import RandomIds, SystemClock
from git_manager.store.database import open_database, state_db_path
from git_manager.store.lock import FileDataDirectoryLock, held
from git_manager.store.protocols import BranchRepository, RunRepository
from git_manager.store.repositories import (
    SqlBranchRepository,
    SqlEventRepository,
    SqlRunRepository,
)
from git_manager.verification.docker import DockerCliCleaner
from git_manager.verification.verifier import CommandVerifier

# One repo per instance (see the spec's data models), so its id is fixed.
REPO_ID = "repo"
# Variables git may take from the orchestrator's environment: where programs and config
# live, and the SSH credentials that reach only git, never Claude or test commands.
GIT_INHERITED_VARIABLES = frozenset(
    {"PATH", "HOME", "SSH_AUTH_SOCK", "GIT_SSH_COMMAND", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"}
)
# Docker cleanup runs as gm-tests, which the supervisor allows only strictly inside the
# data directory.
_RUNS_DIR = "runs"


@dataclass(frozen=True, slots=True)
class LocalRuntime:
    """Everything ``open_local`` built, valid until its ``async with`` block ends.

    ``service`` serves every operation in-process. The other fields are what a daemon
    needs to poll and run on its own: ``config`` is the config as loaded when the runtime
    opened (it fixed the data directory; read the current one with
    ``service.config.show()``), ``events`` is both the ``EventSink`` and ``EventSource``,
    and ``executor`` runs one rebase (it shares the branch locks ``service`` uses).
    ``queue`` is the run queue the daemon's worker drains; with ``SyncMode.QUEUED``,
    ``service``'s sync puts runs there too.
    """

    service: Service
    config: RepoConfig
    branches: BranchRepository
    runs: RunRepository
    git: Git
    events: EventBus
    executor: RunExecutor
    clock: Clock
    queue: FifoRunQueue


class RuntimeOpener(Protocol):
    """Opens a ``LocalRuntime`` for a target, like ``open_local`` with its options bound."""

    def __call__(self, target: LocalTarget) -> AbstractAsyncContextManager[LocalRuntime]: ...


def process_runner(environ: Mapping[str, str]) -> ProcessRunner:
    """The runner for this host: through the supervisor in the container, local outside it.

    Outside the container nothing switches users, so the local runner warns on its first
    Claude or test command that process isolation is off (see "Local mode keeps the
    security rules" in the spec).
    """
    direct = LocalProcessRunner(inherited=environ)
    if not DEFAULT_SOCKET.exists():
        return direct
    channel = UnixSocketSupervisorChannel(DEFAULT_SOCKET)
    return SupervisedProcessRunner(channel=channel, direct=direct, inherited=environ)


def git_environment(config: RepoConfig, environ: Mapping[str, str]) -> dict[str, str]:
    """The whole environment git runs with: the inherited allowlist, credential and identity.

    ``repo.credential`` is an SSH key file, used through ``GIT_SSH_COMMAND``. Rewritten
    commits get the configured committer.
    """
    env = {name: value for name, value in environ.items() if name in GIT_INHERITED_VARIABLES}
    if config.repo.credential is not None:
        key = shlex.quote(str(config.repo.credential))
        env["GIT_SSH_COMMAND"] = f"ssh -i {key} -o IdentitiesOnly=yes"
    committer = config.defaults.commits.committer
    env["GIT_COMMITTER_NAME"] = committer.name
    env["GIT_COMMITTER_EMAIL"] = committer.email
    return env


@asynccontextmanager
async def open_local(
    target: LocalTarget,
    *,
    environ: Mapping[str, str],
    repo_config: RepoConfigSource,
    runner: ProcessRunner,
    version: str,
    sync: SyncMode = SyncMode.FOREGROUND,
) -> AsyncGenerator[LocalRuntime]:
    """Open the target's config, data directory and store, and build the service on them.

    In order: load the config (``ConfigError`` if invalid), take the data-directory lock
    (``DataDirectoryLockedError``, naming API mode, if a daemon holds it), open
    ``state.db``, and clone ``repo.url`` into ``<data_dir>/repo`` if it is not there yet.
    Everything is released when the block ends. ``runner`` runs git as the orchestrator
    and test commands as ``gm-tests``; see ``process_runner``. ``sync`` picks how the
    service's ``sync`` runs: in the foreground for local-mode commands, or queued for
    ``serve``.
    """
    store = YamlConfigFile(target.config, environ=environ, repo_config=repo_config)
    config = await asyncio.to_thread(store.load)
    data_dir = config.repo.data_dir
    clock = SystemClock()
    with held(FileDataDirectoryLock(data_dir)):
        async with open_database(state_db_path(data_dir)) as database:
            event_log = SqlEventRepository(database)
            git = SubprocessGit(
                runner=runner, clone=data_dir / CLONE_DIR, env=git_environment(config, environ)
            )
            await git.ensure_clone(config.repo.url)
            await asyncio.to_thread((data_dir / _RUNS_DIR).mkdir, exist_ok=True)
            yield _build(
                config=config,
                config_service=ConfigService(store),
                branches=SqlBranchRepository(database),
                runs=SqlRunRepository(database),
                events=EventBus(repository=event_log, clock=clock),
                event_history=event_log,
                git=git,
                runner=runner,
                clock=clock,
                version=version,
                sync=sync,
            )


def _build(
    *,
    config: RepoConfig,
    config_service: ConfigService,
    branches: BranchRepository,
    runs: RunRepository,
    events: EventBus,
    event_history: EventHistory,
    git: Git,
    runner: ProcessRunner,
    clock: Clock,
    version: str,
    sync: SyncMode,
) -> LocalRuntime:
    ids = RandomIds()
    locks = InMemoryBranchLocks()
    cleaner = DockerCliCleaner(runner=runner, cwd=config.repo.data_dir / _RUNS_DIR)
    executor = RebaseRunner(
        git=git,
        branches=branches,
        runs=runs,
        events=events,
        verifier=CommandVerifier(runner=runner, cleaner=cleaner, clock=clock),
        approvals=UnrecordedApprovalGate(ids),
        locks=locks,
        clock=clock,
        ids=ids,
    )
    queue = FifoRunQueue(clock=clock)
    match sync:
        case SyncMode.FOREGROUND:
            syncer: BranchSyncer = ForegroundSync(executor=executor, config=config_service)
        case SyncMode.QUEUED:
            syncer = QueuedSync(queue=queue)
        case _:
            assert_never(sync)
    service = Service(
        health=HealthService(reporter=StaticHealthReporter(version=version)),
        config=config_service,
        branches=BranchService(
            repo_id=REPO_ID,
            config=config_service,
            git=git,
            branches=branches,
            syncer=syncer,
            events=events,
            locks=locks,
            ids=ids,
        ),
        runs=RunService(runs=runs, branches=branches, git=git),
        events=EventStreamService(source=events, history=event_history),
    )
    return LocalRuntime(
        service=service,
        config=config,
        branches=branches,
        runs=runs,
        git=git,
        events=events,
        executor=executor,
        clock=clock,
        queue=queue,
    )
