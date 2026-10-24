"""Supervisor contracts; the Linux-only parts sit behind these so tests run anywhere."""

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Protocol

from git_manager.isolation.models import ChownRequest, SpawnRequest, SupervisorResponse
from git_manager.supervisor.models import (
    Account,
    CapabilitySets,
    LaunchPlan,
    LaunchResult,
    OwnershipModes,
)


class Accounts(Protocol):
    """Looks up Unix users and groups by name."""

    def user(self, name: str) -> Account | None:
        """The account called ``name``, or ``None`` when it does not exist."""
        ...

    def group_id(self, name: str) -> int | None:
        """The id of the group called ``name``, or ``None`` when it does not exist."""
        ...


class PeerCredentials(Protocol):
    """Identifies the process at the other end of a Unix socket."""

    def peer_uid(self, fd: int) -> int:
        """The effective uid of the peer connected to socket ``fd``."""
        ...


class Capabilities(Protocol):
    """Reads the capability sets of the current process."""

    def current(self) -> CapabilitySets:
        """The effective and bounding sets."""
        ...


class Ownership(Protocol):
    """Changes owners and modes of files the supervisor manages."""

    def hand_over(
        self, path: Path, *, uid: int, gid: int, modes: OwnershipModes | None = None
    ) -> tuple[Path, ...]:
        """Give ``path`` and everything under it to ``uid``:``gid`` without following links.

        Files with more than one hard link keep their owner, since another link may sit
        outside the tree; their paths, relative to ``path``, are returned. Raises
        ``OSError`` when a node cannot be changed, after giving the directories it had
        locked back to their previous owners.
        """
        ...

    def set_owner(self, path: Path, *, uid: int, gid: int, mode: int) -> None:
        """Set the owner and mode of ``path`` itself, never following a link."""
        ...

    def ensure_directory(self, path: Path, *, uid: int, gid: int, mode: int) -> None:
        """Create ``path`` (and missing parents) if needed, then set its owner and mode."""
        ...


class CommandLauncher(Protocol):
    """Starts a checked command as its account and waits for it."""

    async def run(self, plan: LaunchPlan) -> LaunchResult:
        """Run ``plan`` to completion or its timeout.

        On timeout or cancellation the command's whole process group is killed.
        """
        ...


class DaemonProcess(Protocol):
    """The running daemon child."""

    async def wait(self) -> int:
        """Wait for the daemon to exit and return its exit status."""
        ...

    def signal(self, number: int) -> None:
        """Send signal ``number`` to the daemon, if it is still running."""
        ...


class DaemonStarter(Protocol):
    """Starts the daemon as its account."""

    async def start(
        self, argv: tuple[str, ...], *, account: Account, env: Mapping[str, str]
    ) -> DaemonProcess:
        """Start ``argv`` with exactly ``env``; it inherits stdout and stderr."""
        ...


class RequestAnswerer(Protocol):
    """Answers a parsed socket request (``RequestHandler``)."""

    async def handle(
        self, request: SpawnRequest | ChownRequest, *, peer_uid: int
    ) -> SupervisorResponse:
        """The reply to ``request`` from a peer running as ``peer_uid``."""
        ...


class SocketServer(Protocol):
    """Serves supervisor requests on a Unix socket (``SupervisorServer``)."""

    def serving(self, path: Path) -> AbstractAsyncContextManager[None]:
        """Listen on ``path`` while the context is open."""
        ...
