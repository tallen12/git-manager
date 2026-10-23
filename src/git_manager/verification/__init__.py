"""Verification: test commands, their results and the Docker sidecar."""

from git_manager.verification.models import (
    CommandSource,
    StepOutcome,
    TestResult,
    VerifyCommands,
    VerifyFailed,
    VerifyOutcome,
    VerifyPassed,
    VerifyStep,
)
from git_manager.verification.protocols import Verifier

__all__ = [
    "CommandSource",
    "StepOutcome",
    "TestResult",
    "Verifier",
    "VerifyCommands",
    "VerifyFailed",
    "VerifyOutcome",
    "VerifyPassed",
    "VerifyStep",
]
