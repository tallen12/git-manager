"""Process, clock and id contracts that every domain injects instead of touching the OS."""

from git_manager.runtime.models import (
    Command,
    ProcessCompleted,
    ProcessResult,
    ProcessTimedOut,
    ProcessUser,
)
from git_manager.runtime.protocols import Clock, IdGenerator, ProcessRunner

__all__ = [
    "Clock",
    "Command",
    "IdGenerator",
    "ProcessCompleted",
    "ProcessResult",
    "ProcessRunner",
    "ProcessTimedOut",
    "ProcessUser",
]
