"""Event value types: every state change emits one."""

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from git_manager.branches.models import BranchState, Reason


class EventKind(StrEnum):
    """What happened. ``STATE_CHANGED`` carries the new state."""

    TRACKED = "tracked"
    UNTRACKED = "untracked"
    STATE_CHANGED = "state_changed"
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    PUSHED = "pushed"


class EventDraft(BaseModel):
    """An event before the store gives it an id and a time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EventKind
    branch_id: str
    run_id: str | None = None
    state: BranchState | None = None
    reason: Reason | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict)


class Event(EventDraft):
    """A recorded event; ids increase, so SSE clients resume after the last one seen."""

    id: int = Field(ge=1)
    at: AwareDatetime
