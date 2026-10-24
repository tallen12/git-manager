"""Linux-only adapters: socket peer credentials and process capabilities."""

import socket
import struct
from pathlib import Path

from git_manager.supervisor.models import CapabilitySets

# From asm-generic/socket.h; spelled out because macOS's socket module lacks it.
SO_PEERCRED = 17
# struct ucred { pid_t pid; uid_t uid; gid_t gid; }
_UCRED = struct.Struct("3i")
PROC_STATUS = Path("/proc/self/status")


def parse_ucred(raw: bytes) -> int:
    """The uid in a ``struct ucred``."""
    _pid, uid, _gid = _UCRED.unpack(raw)
    if not isinstance(uid, int):  # Never true for format "3i"; narrows unpack's Any.
        msg = "ucred uid is not an integer"
        raise TypeError(msg)
    return uid


class SoPeerCredentials:
    """``PeerCredentials`` through ``SO_PEERCRED``."""

    def peer_uid(self, fd: int) -> int:
        """See ``PeerCredentials.peer_uid``."""
        # ``fromfd`` duplicates the descriptor, so closing it leaves the connection open.
        with socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            return parse_ucred(connection.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, _UCRED.size))


def parse_capabilities(status: str) -> CapabilitySets:
    """The ``CapEff`` and ``CapBnd`` masks from ``/proc/<pid>/status`` text."""
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    try:
        return CapabilitySets(
            effective=int(fields["CapEff"].strip(), 16),
            bounding=int(fields["CapBnd"].strip(), 16),
        )
    except (KeyError, ValueError) as error:
        msg = "process status has no readable CapEff and CapBnd lines"
        raise ValueError(msg) from error


class ProcCapabilities:
    """``Capabilities`` from the proc file system."""

    def __init__(self, *, status_file: Path = PROC_STATUS) -> None:
        self._status_file = status_file

    def current(self) -> CapabilitySets:
        """See ``Capabilities.current``."""
        return parse_capabilities(self._status_file.read_text(encoding="utf-8"))
