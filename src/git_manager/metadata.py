"""Package metadata helpers."""

from importlib.metadata import version

DISTRIBUTION_NAME = "git-manager"


def package_version() -> str:
    """Return the installed version of the ``git-manager`` distribution."""
    return version(DISTRIBUTION_NAME)
