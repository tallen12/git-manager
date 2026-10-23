"""Tracked branch value types, shared by the store, REST bodies and MCP tool schemas."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# A full commit hash: SHA-1 (40 hex digits) or SHA-256 (64).
CommitSha = str
SHA_PATTERN = r"^([0-9a-f]{40}|[0-9a-f]{64})$"


class BranchState(StrEnum):
    """Where a tracked branch is in the sync lifecycle.

    Stop states (``needs_human`` and the rest after ``pushing``) start no run on a base
    change until a human acts; see "Leaving stop states" in the spec.
    """

    IDLE = "idle"
    BEHIND = "behind"
    SCHEDULED = "scheduled"
    RETARGETING = "retargeting"
    REBASING = "rebasing"
    RESOLVING = "resolving"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting_approval"
    PUSHING = "pushing"
    NEEDS_HUMAN = "needs_human"
    NEEDS_CONFIG = "needs_config"
    TESTS_FAILED = "tests_failed"
    DIVERGED_REMOTE = "diverged_remote"
    BASE_MISSING = "base_missing"
    STACK_PARTIAL_PUSH = "stack_partial_push"
    WAITING_BUDGET = "waiting_budget"
    WAITING_QUOTA = "waiting_quota"
    PAUSED = "paused"


class Reason(StrEnum):
    """Why a branch or run is in its state. Later milestones add their own values."""

    # needs_config: no test command in config (and none confirmed from AGENTS.md).
    MISSING_COMMANDS = "missing_commands"
    # paused: the feature branch moved mid-run more than max_restarts times in a row.
    MAX_RESTARTS = "max_restarts"
    # paused: a human ran ``git-manager pause``.
    PAUSED_BY_USER = "paused_by_user"
    # needs_human: the base is not a descendant of last_base_sha (handled in M4).
    REWRITTEN_BASE = "rewritten_base"
    # needs_human: the rebase stopped on a conflict and Claude resolution is not available.
    CONFLICT = "conflict"
    # tests_failed: a verify step failed or timed out.
    VERIFY_FAILED = "verify_failed"
    # diverged_remote: the push lease was rejected because someone pushed meanwhile.
    LEASE_REJECTED = "lease_rejected"


class BranchHeads(BaseModel):
    """A branch's head before a run and after it (``None`` until the run produces one)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch: str
    old_head: CommitSha = Field(pattern=SHA_PATTERN)
    new_head: CommitSha | None = Field(default=None, pattern=SHA_PATTERN)


class TrackedBranch(BaseModel):
    """A branch Git Manager keeps rebased on its base.

    Its effective settings come from the repo config by ``name``, not from this record.
    Stack membership is added with gh stack support in M4.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    repo_id: str
    name: str = Field(min_length=1)
    base: str = Field(min_length=1)
    # The base commit the branch currently sits on: the ``<upstream>`` of
    # ``rebase --onto``, so a retarget never replays the old base's commits.
    fork_point: CommitSha = Field(pattern=SHA_PATTERN)
    last_base_sha: CommitSha = Field(pattern=SHA_PATTERN)
    last_head_sha: CommitSha = Field(pattern=SHA_PATTERN)
    state: BranchState = BranchState.IDLE
    reason: Reason | None = None


class RepoStatus(BaseModel):
    """The managed repository and every branch tracked in it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_id: str
    url: str
    branches: tuple[TrackedBranch, ...]
