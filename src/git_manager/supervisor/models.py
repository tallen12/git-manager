"""Supervisor value types. The wire messages are ``git_manager.isolation.models``."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType

from git_manager.isolation.models import SpawnCompleted, SpawnFailed, SpawnTimedOut

type LaunchResult = SpawnCompleted | SpawnTimedOut | SpawnFailed
"""What starting a command can come to; sent to the daemon as is."""


@dataclass(frozen=True, slots=True)
class Account:
    """A Unix user as the supervisor switches to it."""

    name: str
    uid: int
    gid: int
    groups: tuple[int, ...]
    home: Path


def _frozen(env: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(env))


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """A checked request: what the launcher starts, with the final environment."""

    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    account: Account
    timeout: timedelta | None
    stdin: str | None
    output_limit_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "env", _frozen(self.env))


@dataclass(frozen=True, slots=True)
class OwnershipModes:
    """Modes applied while handing a tree over; ``None`` keeps a node's mode."""

    directory: int | None = None
    file: int | None = None


@dataclass(frozen=True, slots=True)
class CapabilitySets:
    """Capability bit masks of the supervisor process (``CAP_*`` numbers as bits)."""

    effective: int
    bounding: int


@dataclass(frozen=True, slots=True)
class CapabilitiesOk:
    """The process holds exactly what it needs."""


@dataclass(frozen=True, slots=True)
class CapabilitiesWrong:
    """Startup must stop: capabilities are missing or more are held than allowed."""

    missing: frozenset[int]
    extra: frozenset[int] = field(default_factory=frozenset)


type CapabilityCheck = CapabilitiesOk | CapabilitiesWrong
