"""Verification: test commands, their results and the Docker sidecar."""

from git_manager.verification.commands import (
    CommandsInvalid,
    CommandsMissing,
    ConfigCommands,
    config_commands,
    split_command,
)
from git_manager.verification.docker import RUN_LABEL, DockerCliCleaner, docker_environment
from git_manager.verification.errors import (
    DockerCleanupError,
    InvalidCommandError,
    UnsupportedDockerModeError,
)
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
from git_manager.verification.protocols import DockerCleaner, Verifier
from git_manager.verification.verifier import CommandVerifier

__all__ = [
    "RUN_LABEL",
    "CommandSource",
    "CommandVerifier",
    "CommandsInvalid",
    "CommandsMissing",
    "ConfigCommands",
    "DockerCleaner",
    "DockerCleanupError",
    "DockerCliCleaner",
    "InvalidCommandError",
    "StepOutcome",
    "TestResult",
    "UnsupportedDockerModeError",
    "Verifier",
    "VerifyCommands",
    "VerifyFailed",
    "VerifyOutcome",
    "VerifyPassed",
    "VerifyStep",
    "config_commands",
    "docker_environment",
    "split_command",
]
