"""The daemon's Unix socket listener (``http.socket``)."""

import os
import socket
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

# Owner and group only: operators reach the socket through the gm-admin group.
SOCKET_MODE = 0o660


@contextmanager
def unix_listener(path: Path) -> Generator[socket.socket]:
    """Bind a stream socket at ``path`` for uvicorn to serve on; remove it on exit.

    The socket gets mode ``0660`` and its directory's group (``gm-admin`` for
    ``/run/git-manager``), both set before uvicorn starts listening, so no caller can
    connect in between. A socket left by a daemon that crashed is replaced; any other file
    at ``path`` is left alone and binding fails.
    """
    if path.is_socket():
        path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(os.fspath(path))
        try:
            group = path.parent.stat().st_gid
            if path.stat().st_gid != group:
                os.chown(path, -1, group)
            path.chmod(SOCKET_MODE)
            yield listener
        finally:
            path.unlink(missing_ok=True)
