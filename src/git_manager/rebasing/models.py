"""Rebase run and git outcome value types."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from git_manager.branches.models import SHA_PATTERN, BranchHeads, BranchState, CommitSha, Reason
from git_manager.verification.models import TestResult, VerifyCommands


class RunTrigger(StrEnum):
    """What started a run."""

    POLL = "poll"
    MANUAL = "manual"
    RETARGET = "retarget"
    RETRY = "retry"


class Run(BaseModel):
    """One rebase run of a tracked branch, from fetch to push or a stop state.

    Claude usage and conflict resolutions join in M3, stack runs in M4.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    branch_id: str
    trigger: RunTrigger
    base_from: CommitSha = Field(pattern=SHA_PATTERN)
    base_to: CommitSha = Field(pattern=SHA_PATTERN)
    heads: tuple[BranchHeads, ...]
    rewritten_base: bool = False
    restarts: int = Field(default=0, ge=0)
    commands: VerifyCommands | None = None
    tests: tuple[TestResult, ...] = ()
    # The branch's state while the run is in progress, then the state it ended in.
    outcome: BranchState
    reason: Reason | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None


@dataclass(frozen=True, slots=True)
class RebaseCompleted:
    """The rebase applied every commit; ``head`` is the rebased tip."""

    head: CommitSha


@dataclass(frozen=True, slots=True)
class RebaseStopped:
    """The rebase stopped on a conflict and is still in progress in the worktree."""

    commit: CommitSha
    conflicted_paths: tuple[str, ...]


type RebaseOutcome = RebaseCompleted | RebaseStopped


@dataclass(frozen=True, slots=True)
class Pushed:
    """The remote branch now points at the pushed commit."""

    head: CommitSha


@dataclass(frozen=True, slots=True)
class LeaseRejected:
    """The remote branch was not at the expected commit, so nothing was pushed."""

    expected: CommitSha


type PushOutcome = Pushed | LeaseRejected
