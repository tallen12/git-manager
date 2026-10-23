"""Config operations, as exposed by every interface, and the config's own capabilities."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from git_manager.config.models import RepoConfig

# A key path into the config file, as YAML keys and list indexes:
# ``("defaults", "cadence", "mode")`` or ``("branches", 0, "verify", "test")``.
ConfigPath = Sequence[str | int]


class ConfigOperations(Protocol):
    """Read the effective config (``git-manager config show``, ``GET /config``)."""

    async def show(self) -> RepoConfig:
        """Return the effective config, with defaults and per-branch blocks merged."""
        ...


class ConfigStore(Protocol):
    """The config file: load it as the effective config, or edit it in place."""

    def load(self) -> RepoConfig:
        """Read and validate the file with every other layer; raise ``ConfigError``."""
        ...

    def set(self, path: ConfigPath, value: object) -> RepoConfig:
        """Set the YAML value at ``path`` and write the file back, keeping its comments.

        ``value`` is plain YAML data (strings, numbers, booleans, ``None``, lists and
        mappings). The edit is validated before anything is written, and the write is
        atomic, so an invalid edit or a crash leaves the file as it was. Returns the new
        effective config. Whether the caller may change ``path`` is not checked here (see
        ``config.sensitivity``).
        """
        ...


class ConfigReader(Protocol):
    """Opens the config file at a path, for local mode and ``config validate``."""

    def __call__(self, path: Path) -> ConfigStore: ...


class RepoConfigSource(Protocol):
    """Reads the managed repo's own ``.git-manager.yaml``, if it has one."""

    def read(self, *, data_dir: Path) -> str | None:
        """Return the file's text from the clone under ``data_dir``, or ``None``."""
        ...
