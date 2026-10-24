"""The supervisor wire contract: what the daemon asks PID 1 to run, and the answers.

The daemon runs as ``gm`` and cannot switch users; the supervisor (PID 1, see Process
isolation in the spec) can. For every command that must run as ``gm-claude`` or
``gm-tests``, the daemon connects to the supervisor's Unix socket and exchanges exactly one
message each way (framing in ``isolation.wire``):

1. The daemon sends a ``SpawnRequest``.
2. The supervisor validates it, starts ``argv`` in ``cwd`` as ``user`` in a new session
   (so the command leads its own process group), with exactly ``env`` as its environment
   (``env -i`` semantics) plus ``HOME``, ``USER`` and ``LOGNAME`` for ``user`` when ``env``
   does not set them, and writes ``stdin`` (if any) before closing it.
3. When the command exits, the supervisor kills what is left of its process group and
   answers ``SpawnCompleted``. When ``timeout_s`` passes first, it sends ``SIGTERM`` to the
   group, then ``SIGKILL`` after a short grace period, and answers ``SpawnTimedOut`` with
   the output read so far. A request it cannot start gets ``SpawnFailed``.
4. If the daemon closes the connection before the answer, the supervisor kills the group.

The daemon also asks the supervisor to hand a run's worktree to another user between
phases (``ChownRequest``; see Process isolation in the spec), since only root can change
owners. The answer is ``Chowned`` or ``ChownFailed``. Requests are told apart by ``kind``;
a request without one is a ``SpawnRequest``.

The supervisor never adds variables of its own beyond the three above, never runs a
request as ``gm`` or root, and rejects requests with an unknown ``version``.
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, field_validator

from git_manager.runtime.models import ProcessUser

SUPERVISOR_PROTOCOL_VERSION = 1
"""Bumped on any incompatible change to the messages below."""

type IsolatedUser = Literal[ProcessUser.CLAUDE, ProcessUser.TESTS]
"""The users the supervisor may run commands as; ``gm`` commands never go through it."""


class _Message(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _absolute(path: Path) -> Path:
    # The supervisor's working directory is not the daemon's; relative paths would drift.
    if not path.is_absolute():
        msg = f"path must be absolute, got {path}"
        raise ValueError(msg)
    return path


class SpawnRequest(_Message):
    """Run one command as an isolated user."""

    version: Literal[1] = SUPERVISOR_PROTOCOL_VERSION
    kind: Literal["run"] = "run"
    user: IsolatedUser
    argv: tuple[str, ...] = Field(min_length=1)
    cwd: Path
    env: dict[str, str] = Field(description="The complete environment, already scrubbed.")
    timeout_s: float | None = Field(default=None, gt=0)
    stdin: str | None = None

    @field_validator("cwd")
    @classmethod
    def _absolute_cwd(cls, cwd: Path) -> Path:
        return _absolute(cwd)


class ChownRequest(_Message):
    """Give the tree at ``path`` (inside the data directory) to ``user`` and its group."""

    version: Literal[1] = SUPERVISOR_PROTOCOL_VERSION
    kind: Literal["chown"] = "chown"
    user: ProcessUser
    path: Path

    @field_validator("path")
    @classmethod
    def _absolute_path(cls, path: Path) -> Path:
        return _absolute(path)


def _request_kind(value: object) -> str:
    if isinstance(value, dict):
        kind = value.get("kind", "run")
        return kind if isinstance(kind, str) else ""
    return str(getattr(value, "kind", ""))


type SupervisorRequest = Annotated[
    Annotated[SpawnRequest, Tag("run")] | Annotated[ChownRequest, Tag("chown")],
    Discriminator(_request_kind),
]
"""Anything the daemon may send; requests from before ``kind`` existed are spawns."""


class SpawnCompleted(_Message):
    """The command exited; a negative ``exit_code`` is the signal that ended it."""

    kind: Literal["completed"] = "completed"
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float = Field(ge=0)


class SpawnTimedOut(_Message):
    """The command ran past ``timeout_s`` and its process group was killed."""

    kind: Literal["timed_out"] = "timed_out"
    stdout: str
    stderr: str
    duration_s: float = Field(ge=0)


class SpawnErrorCode(StrEnum):
    """Why a request did not run."""

    # The program, or cwd, could not be found or executed (the runner raises OSError).
    START_FAILED = "start_failed"
    # The request broke this contract: unknown version, disallowed user, bad fields.
    INVALID_REQUEST = "invalid_request"


class SpawnFailed(_Message):
    """The supervisor did not start the command."""

    kind: Literal["failed"] = "failed"
    code: SpawnErrorCode
    message: str


type SpawnResponse = Annotated[
    SpawnCompleted | SpawnTimedOut | SpawnFailed, Field(discriminator="kind")
]


class Chowned(_Message):
    """The tree belongs to the requested user, except ``skipped``.

    ``skipped`` lists files (relative to the tree) with more than one hard link: another
    link may be outside the tree, so they keep their owner.
    """

    kind: Literal["chowned"] = "chowned"
    skipped: tuple[Path, ...] = ()


class ChownErrorCode(StrEnum):
    """Why a tree was not, or not completely, handed over."""

    # Outside the data directory, or bad fields; nothing changed.
    INVALID_REQUEST = "invalid_request"
    # A node could not be changed; directories already locked were given back.
    FAILED = "failed"


class ChownFailed(_Message):
    """The hand-over did not happen or did not finish."""

    kind: Literal["chown_failed"] = "chown_failed"
    code: ChownErrorCode
    message: str


type ChownResponse = Annotated[Chowned | ChownFailed, Field(discriminator="kind")]

type SupervisorResponse = Annotated[
    SpawnCompleted | SpawnTimedOut | SpawnFailed | Chowned | ChownFailed,
    Field(discriminator="kind"),
]
"""Anything the supervisor may answer."""
