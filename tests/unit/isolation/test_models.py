from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from git_manager.isolation import (
    SpawnCompleted,
    SpawnErrorCode,
    SpawnFailed,
    SpawnRequest,
    SpawnResponse,
    SpawnTimedOut,
)
from git_manager.runtime import ProcessUser

ROOT = Path.cwd().anchor


def request(**overrides: object) -> SpawnRequest:
    values: dict[str, object] = {
        "user": "gm-tests",
        "argv": ["just", "test"],
        "cwd": str(Path(ROOT, "data", "runs", "run-1")),
        "env": {"PATH": "/usr/bin"},
    }
    return SpawnRequest.model_validate(values | overrides)


def test_request_carries_the_protocol_version_and_isolated_user() -> None:
    parsed = request(timeout_s=60)

    assert parsed.version == 1
    assert parsed.user is ProcessUser.TESTS
    assert parsed.argv == ("just", "test")


def test_request_never_runs_as_the_orchestrator() -> None:
    with pytest.raises(ValidationError):
        request(user="gm")


def test_request_needs_an_absolute_cwd_and_a_program() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        request(cwd="relative/dir")
    with pytest.raises(ValidationError):
        request(argv=[])


def test_request_rejects_unknown_versions_fields_and_non_positive_timeouts() -> None:
    for overrides in ({"version": 2}, {"shell": True}, {"timeout_s": 0}):
        with pytest.raises(ValidationError):
            request(**overrides)


def test_responses_are_told_apart_by_kind() -> None:
    adapter: TypeAdapter[SpawnResponse] = TypeAdapter(SpawnResponse)

    assert isinstance(
        adapter.validate_python(
            {"kind": "completed", "exit_code": 1, "stdout": "", "stderr": "", "duration_s": 1}
        ),
        SpawnCompleted,
    )
    assert isinstance(
        adapter.validate_python({"kind": "timed_out", "stdout": "", "stderr": "", "duration_s": 9}),
        SpawnTimedOut,
    )
    failed = adapter.validate_python(
        {"kind": "failed", "code": "start_failed", "message": "no such file"}
    )
    assert failed == SpawnFailed(code=SpawnErrorCode.START_FAILED, message="no such file")
