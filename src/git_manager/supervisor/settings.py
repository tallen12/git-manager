"""Supervisor settings, read from ``GM_SUPERVISOR_*`` environment variables.

The supervisor reads no settings file: it starts before the daemon and must not depend on
anything the daemon's users can write.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from git_manager.isolation.channel import DEFAULT_SOCKET

ENV_PREFIX = "GM_SUPERVISOR_"
# The daemon reads the socket path from this variable (set by the supervisor).
SOCKET_VARIABLE = f"{ENV_PREFIX}SOCKET"


class SupervisorSettings(BaseModel):
    """Paths and limits for one container."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    socket: Path = DEFAULT_SOCKET
    data_root: Path = Path("/data")
    client_certs: Path = Path("/certs/client")
    secrets_dir: Path = Path("/run/secrets")
    api_socket_dir: Path = Path("/run/git-manager")
    output_limit_bytes: int = Field(default=8 * 1024 * 1024, gt=0)

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> Self:
        """Settings from ``GM_SUPERVISOR_<FIELD>`` variables; unknown names are errors."""
        values = {
            name.removeprefix(ENV_PREFIX).lower(): value
            for name, value in environ.items()
            if name.startswith(ENV_PREFIX)
        }
        return cls.model_validate(values)
