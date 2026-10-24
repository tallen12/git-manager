"""Supervisor failures that stop an operation or startup."""


class StartupError(Exception):
    """The container is not set up the way the supervisor needs; it refuses to start."""
