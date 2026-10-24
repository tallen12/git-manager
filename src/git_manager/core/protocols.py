"""Operations contract shared by the in-process service and the HTTP client."""

from typing import Protocol

from git_manager.branches.protocols import BranchOperations
from git_manager.config.protocols import ConfigOperations
from git_manager.events.protocols import EventOperations
from git_manager.health.protocols import HealthOperations
from git_manager.rebasing.protocols import RunOperations


class Operations(Protocol):
    """Every Git Manager operation, grouped by domain (``operations.branches.sync``).

    ``Service`` implements it in-process and ``HttpOperations`` through the REST API, so
    the CLI behaves the same in local and API mode. Each group's protocol lives in its
    domain; add an operation there, to the domain's in-process service, to its REST
    router and to its HTTP client together. A new domain adds one attribute here.
    """

    @property
    def health(self) -> HealthOperations:
        """Liveness and version."""
        ...

    @property
    def config(self) -> ConfigOperations:
        """The effective repo config."""
        ...

    @property
    def branches(self) -> BranchOperations:
        """Tracked branches and syncing."""
        ...

    @property
    def runs(self) -> RunOperations:
        """Runs and their reports."""
        ...

    @property
    def events(self) -> EventOperations:
        """The live event stream."""
        ...
