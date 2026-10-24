"""In-process implementation of the operations."""

from dataclasses import dataclass

from git_manager.branches.protocols import BranchOperations
from git_manager.config.protocols import ConfigOperations
from git_manager.events.protocols import EventOperations
from git_manager.health.protocols import HealthOperations
from git_manager.rebasing.protocols import RunOperations


@dataclass(frozen=True, slots=True)
class Service:
    """Runs operations in this process: one injected implementation per domain."""

    health: HealthOperations
    config: ConfigOperations
    branches: BranchOperations
    runs: RunOperations
    events: EventOperations
