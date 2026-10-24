"""The repo config schema: every section with its defaults (see the spec's example).

These models describe the *effective* config, after ``defaults:`` and each branch's
block are merged; loading and merging belong to the config loader. Fields marked
``SENSITIVE`` need the ``approve`` scope to change (see ``config.sensitivity``).
"""

from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from git_manager.config.sensitivity import SENSITIVE
from git_manager.config.types import Duration, Size


class _Section(BaseModel):
    """Base for config sections: immutable, and typos fail instead of being ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CadenceMode(StrEnum):
    """When a detected base change is acted on."""

    IMMEDIATE = "immediate"
    DEBOUNCE = "debounce"
    CRON = "cron"
    MANUAL = "manual"


class ApprovalPolicy(StrEnum):
    """When a verified result waits for a human. AI-changed code always does."""

    ON_AI_CHANGE = "on_ai_change"
    ALWAYS = "always"


class CommitterDate(StrEnum):
    """The committer date of rewritten commits."""

    AUTHOR = "author"
    NOW = "now"


class StackMode(StrEnum):
    """Whether gh stack membership changes how a branch is rebased."""

    AUTO = "auto"
    IGNORE = "ignore"


class StackScope(StrEnum):
    """How much of a stack a stack run rebases."""

    FULL = "full"
    DOWNSTACK = "downstack"


class StackTest(StrEnum):
    """Which branches of a stack run are verified."""

    ALL = "all"
    TOP = "top"


class ClaudeAuth(StrEnum):
    """Which secret authenticates the Claude CLI."""

    SUBSCRIPTION = "subscription"
    API_KEY = "api_key"


class DiscoverMode(StrEnum):
    """Where verify commands come from when config does not set them."""

    AGENTS_MD = "agents_md"
    NONE = "none"


class DockerMode(StrEnum):
    """How tests reach a Docker daemon."""

    NONE = "none"
    DIND = "dind"
    HOST_SOCKET = "host_socket"


class WebhookKind(StrEnum):
    """Webhook payload formats."""

    NTFY = "ntfy"
    SLACK = "slack"
    GENERIC = "generic"


class NotifyOn(StrEnum):
    """Events that reach notification sinks."""

    AWAITING_APPROVAL = "awaiting_approval"
    NEEDS_HUMAN = "needs_human"
    NEEDS_CONFIG = "needs_config"
    TESTS_FAILED = "tests_failed"
    PUSHED = "pushed"
    BASE_MISSING = "base_missing"
    STACK_REMOVED = "stack_removed"
    STACK_PARTIAL_PUSH = "stack_partial_push"
    WAITING_BUDGET = "waiting_budget"
    WAITING_QUOTA = "waiting_quota"


class CadenceConfig(_Section):
    """When to act on a base change. ``git-manager sync`` always overrides it."""

    mode: CadenceMode = CadenceMode.DEBOUNCE
    debounce: Duration = timedelta(minutes=10)
    cron: str | None = None

    @model_validator(mode="after")
    def _check_cron(self) -> Self:
        if self.mode is CadenceMode.CRON and self.cron is None:
            msg = "cadence.cron is required when cadence.mode is cron"
            raise ValueError(msg)
        if self.cron is not None and not croniter.is_valid(self.cron):
            msg = f"cadence.cron {self.cron!r} is not a valid cron expression"
            raise ValueError(msg)
        return self


class FailuresConfig(_Section):
    """Failure records and their resolution sessions."""

    session_idle_timeout: Duration = timedelta(hours=2)


class Identity(_Section):
    """A git name and email."""

    name: str = Field(min_length=1)
    email: str = Field(min_length=3)


class CommitsConfig(_Section):
    """How rewritten commits are made."""

    committer: Identity = Identity(name="Git Manager", email="git-manager@users.noreply.github.com")
    committer_date: CommitterDate = CommitterDate.AUTHOR
    check_github_rules: bool = True
    # Settings the repo relies on from its unversioned .git/config, like merge.renames.
    git_config: dict[str, str] = Field(default_factory=dict)


class StackConfig(_Section):
    """gh stack handling."""

    mode: Annotated[StackMode, SENSITIVE] = StackMode.AUTO
    scope: StackScope = StackScope.FULL
    test: StackTest = StackTest.ALL


class SizeGate(_Section):
    """Conflicts larger than this go to a human without calling Claude."""

    files: int = Field(default=25, ge=1)
    conflict_lines: int = Field(default=1500, ge=1)


class ProcessLimits(_Section):
    """``prlimit`` values for the Claude process."""

    memory: Size = Size(4 * 1024**3)
    processes: int = Field(default=256, ge=1)
    file_size: Size = Size(200 * 1024**2)


class BashLimits(_Section):
    """Limits on Claude's Bash tool."""

    default_timeout: Duration = timedelta(seconds=60)
    max_timeout: Duration = timedelta(seconds=120)
    max_output_chars: int = Field(default=30_000, ge=1)


class GuidanceConfig(_Section):
    """Which repo guidance is loaded for Claude calls."""

    agents_md: bool = True
    claude_md: bool = True
    skills: bool = True
    subagents: bool = True


class ClaudeConfig(_Section):
    """Claude CLI calls: limits, guidance and tools. The whole section is sensitive."""

    enabled: bool = True
    auth: ClaudeAuth = ClaudeAuth.SUBSCRIPTION
    model: str | None = None
    max_turns: int = Field(default=30, ge=1)
    max_budget_usd: float = Field(default=2.00, gt=0)
    timeout: Duration = timedelta(minutes=15)
    max_calls_per_run: int = Field(default=10, ge=1)
    max_run_usd: float = Field(default=5.00, gt=0)
    size_gate: SizeGate = SizeGate()
    limits: ProcessLimits = ProcessLimits()
    bash: BashLimits = BashLimits()
    guidance: GuidanceConfig = GuidanceConfig()
    agents_file: Path = Path("AGENTS.md")
    resolution_prompt_extra: str = ""
    fix_test_failures: bool = False
    extra_allowed_tools: tuple[str, ...] = ()


class DockerConfig(_Section):
    """The Docker daemon tests may use."""

    mode: DockerMode = DockerMode.DIND
    host: str = "tcp://localhost:2376"
    cert_path: Path = Path("/certs/client")
    reset_between_runs: bool = True
    registry_mirror: str | None = None


class VerifyConfig(_Section):
    """Verify commands and how they run. The whole section is sensitive."""

    discover: DiscoverMode = DiscoverMode.AGENTS_MD
    # None means take the command from AGENTS.md (once confirmed).
    setup: str | None = None
    test: str | None = None
    lint: str | None = None
    timeout: Duration = timedelta(minutes=30)
    retries: int = Field(default=0, ge=0)
    baseline: bool = False
    docker: DockerConfig = DockerConfig()


class Webhook(_Section):
    """One webhook sink."""

    kind: WebhookKind
    url: str = Field(min_length=1)


class NotifyConfig(_Section):
    """Notification sinks and which events reach them."""

    sse: bool = True
    webhooks: Annotated[tuple[Webhook, ...], SENSITIVE] = ()
    on: tuple[NotifyOn, ...] = tuple(NotifyOn)


class BranchOptions(_Section):
    """Per-branch behavior: the ``defaults:`` block, overridable in each branch's block."""

    poll_interval: Duration = timedelta(seconds=60)
    cadence: CadenceConfig = CadenceConfig()
    max_restarts: int = Field(default=3, ge=0)
    auto_push_clean: Annotated[bool, SENSITIVE] = True
    approval_policy: Annotated[ApprovalPolicy, SENSITIVE] = ApprovalPolicy.ON_AI_CHANGE
    # Fixed in v1: retargeting is always a human action.
    allow_auto_retarget: Literal[False] = False
    rebase_merges: bool = False
    keep_failed_attempts: bool = True
    failures: FailuresConfig = FailuresConfig()
    commits: CommitsConfig = CommitsConfig()
    stack: StackConfig = StackConfig()
    claude: Annotated[ClaudeConfig, SENSITIVE] = ClaudeConfig()
    verify: Annotated[VerifyConfig, SENSITIVE] = VerifyConfig()
    notify: NotifyConfig = NotifyConfig()


class BranchConfig(BranchOptions):
    """One tracked branch's effective config: its name, base and merged options."""

    name: str = Field(min_length=1)
    base: str = Field(min_length=1)


class RepoSection(_Section):
    """The one repository this instance manages."""

    url: str = Field(min_length=1)
    credential: Path | None = None
    signing_key: Annotated[Path | None, SENSITIVE] = None
    # Lets anyone with commit access change Git Manager's behavior, hence sensitive.
    trust_repo_config: Annotated[bool, SENSITIVE] = False
    # The clone, run worktrees and state.db live here.
    data_dir: Path = Path("/data")


class BudgetConfig(_Section):
    """Rolling Claude spend, summed from each call's reported cost."""

    daily_usd: float = Field(default=10, gt=0)
    weekly_usd: float = Field(default=40, gt=0)


class RepoConfig(_Section):
    """The whole effective config of one instance (one repo per container)."""

    repo: RepoSection
    budget: Annotated[BudgetConfig, SENSITIVE] = BudgetConfig()
    defaults: BranchOptions = BranchOptions()
    branches: tuple[BranchConfig, ...] = ()

    @model_validator(mode="after")
    def _unique_branches(self) -> Self:
        names = [branch.name for branch in self.branches]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            msg = f"branches listed more than once: {', '.join(duplicates)}"
            raise ValueError(msg)
        return self

    def branch(self, name: str) -> BranchConfig | None:
        """Return the effective config of the branch called ``name``, if listed."""
        return next((branch for branch in self.branches if branch.name == name), None)
