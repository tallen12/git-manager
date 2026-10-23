"""Errors from loading or editing the repo config."""

from collections.abc import Sequence

from git_manager.core.errors import OperationError


class ConfigError(OperationError):
    """The config file, the repo's ``.git-manager.yaml`` or a ``GM_*`` override is invalid.

    ``problems`` holds one line per problem, each starting with the config path it is
    about (``defaults.cadence.mode: ...``), so every interface can list them all.
    """

    def __init__(self, source: str, problems: Sequence[str]) -> None:
        super().__init__(f"invalid config {source}: {'; '.join(problems)}")
        self.source = source
        self.problems = tuple(problems)
