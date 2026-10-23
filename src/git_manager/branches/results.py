"""Results of branch operations."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field

from git_manager.rebasing.models import Run


class SyncCompleted(BaseModel):
    """Local mode: the run finished in the foreground."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["completed"] = "completed"
    run: Run


class SyncQueued(BaseModel):
    """API mode: the daemon queued the run behind ``position`` others."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["queued"] = "queued"
    branch_id: str
    position: int = Field(ge=0)


type SyncOutcome = Annotated[SyncCompleted | SyncQueued, Discriminator("kind")]
