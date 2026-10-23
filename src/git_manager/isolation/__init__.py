"""Process isolation: run Claude and tests as their own users with scrubbed environments."""

from git_manager.isolation.channel import DEFAULT_SOCKET, UnixSocketSupervisorChannel
from git_manager.isolation.environment import (
    INHERITED_VARIABLES,
    SUPERVISED_INHERITED_VARIABLES,
    scrubbed_environment,
)
from git_manager.isolation.errors import (
    SupervisorError,
    SupervisorProtocolError,
    SupervisorUnavailableError,
)
from git_manager.isolation.local import LocalProcessRunner
from git_manager.isolation.models import (
    SUPERVISOR_PROTOCOL_VERSION,
    IsolatedUser,
    SpawnCompleted,
    SpawnErrorCode,
    SpawnFailed,
    SpawnRequest,
    SpawnResponse,
    SpawnTimedOut,
)
from git_manager.isolation.protocols import SupervisorChannel
from git_manager.isolation.supervised import SupervisedProcessRunner

__all__ = [
    "DEFAULT_SOCKET",
    "INHERITED_VARIABLES",
    "SUPERVISED_INHERITED_VARIABLES",
    "SUPERVISOR_PROTOCOL_VERSION",
    "IsolatedUser",
    "LocalProcessRunner",
    "SpawnCompleted",
    "SpawnErrorCode",
    "SpawnFailed",
    "SpawnRequest",
    "SpawnResponse",
    "SpawnTimedOut",
    "SupervisedProcessRunner",
    "SupervisorChannel",
    "SupervisorError",
    "SupervisorProtocolError",
    "SupervisorUnavailableError",
    "UnixSocketSupervisorChannel",
    "scrubbed_environment",
]
