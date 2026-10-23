"""Config operations, as exposed by every interface."""

from typing import Protocol

from git_manager.config.models import RepoConfig


class ConfigOperations(Protocol):
    """Read the effective config (``git-manager config show``, ``GET /config``)."""

    async def show(self) -> RepoConfig:
        """Return the effective config, with defaults and per-branch blocks merged."""
        ...
