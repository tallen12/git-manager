"""Verification value types: which commands run and what they reported."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from git_manager.approvals.models import Actor


class CommandSource(StrEnum):
    """Where a set of verify commands came from (see the priority table in the spec)."""

    CONFIG = "config"
    AGENTS_MD = "agents_md"


class VerifyStep(StrEnum):
    """One verify command, in the order they run."""

    SETUP = "setup"
    TEST = "test"
    LINT = "lint"


class StepOutcome(StrEnum):
    """How one verify step ended."""

    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class VerifyCommands(BaseModel):
    """The commands a run verifies with, and where they came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    setup: str | None = None
    test: str = Field(min_length=1)
    lint: str | None = None
    source: CommandSource
    # Hash of the config block or of AGENTS.md and the files it pointed to.
    source_hash: str
    # Commands from config need no confirmation; extracted ones do (M3).
    confirmed_by: Actor | None = None


class TestResult(BaseModel):
    """What one verify step reported; kept as a run artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    # Not a test class, despite the name.
    __test__ = False

    step: VerifyStep
    command: str
    outcome: StepOutcome
    exit_code: int | None = Field(description="None when the step timed out.")
    attempts: int = Field(ge=1, description="More than 1 means it passed on a retry.")
    duration_s: float = Field(ge=0)
    output_tail: str = Field(description="Last 500 lines of combined output.")
    junit_xml: str | None = None


@dataclass(frozen=True, slots=True)
class VerifyPassed:
    """Every step passed; the result may be pushed."""

    results: tuple[TestResult, ...]


@dataclass(frozen=True, slots=True)
class VerifyFailed:
    """A step failed or timed out; later steps did not run."""

    results: tuple[TestResult, ...]
    failed_step: VerifyStep


type VerifyOutcome = VerifyPassed | VerifyFailed
