"""Run queue value types."""

from dataclasses import dataclass
from datetime import datetime

from git_manager.rebasing.models import RunTrigger


@dataclass(frozen=True, slots=True)
class QueuedRun:
    """A branch waiting for its turn to run."""

    branch_id: str
    trigger: RunTrigger
    queued_at: datetime
