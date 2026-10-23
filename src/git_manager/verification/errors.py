"""Verification errors."""


class InvalidCommandError(ValueError):
    """A verify command cannot be split into arguments (unbalanced quotes, or empty)."""


class UnsupportedDockerModeError(ValueError):
    """The configured Docker mode is not available yet (``host_socket`` arrives in F27)."""


class DockerCleanupError(Exception):
    """Removing a run's leftover containers, networks or volumes failed."""
