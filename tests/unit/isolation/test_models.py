from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from git_manager.isolation import (
    Chowned,
    ChownErrorCode,
    ChownFailed,
    ChownRequest,
    SpawnCompleted,
    SpawnErrorCode,
    SpawnFailed,
    SpawnRequest,
    SpawnResponse,
    SpawnTimedOut,
    SupervisorRequest,
    SupervisorResponse,
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


def test_a_request_without_kind_is_a_spawn() -> None:
    adapter: TypeAdapter[SupervisorRequest] = TypeAdapter(SupervisorRequest)
    values = request().model_dump(mode="json")
    del values["kind"]

    assert adapter.validate_python(values) == request()


def test_a_chown_request_names_any_user_and_an_absolute_path() -> None:
    adapter: TypeAdapter[SupervisorRequest] = TypeAdapter(SupervisorRequest)
    path = str(Path(ROOT, "data", "runs", "run-1"))

    parsed = adapter.validate_python({"kind": "chown", "user": "gm", "path": path})

    assert parsed == ChownRequest(user=ProcessUser.ORCHESTRATOR, path=Path(path))
    with pytest.raises(ValidationError, match="absolute"):
        ChownRequest(user=ProcessUser.CLAUDE, path=Path("runs"))
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "exec", "user": "gm", "path": path})


def test_chown_answers_are_told_apart_by_kind() -> None:
    adapter: TypeAdapter[SupervisorResponse] = TypeAdapter(SupervisorResponse)

    assert adapter.validate_python({"kind": "chowned", "skipped": ["sub/linked"]}) == Chowned(
        skipped=(Path("sub/linked"),)
    )
    assert adapter.validate_python(
        {"kind": "chown_failed", "code": "failed", "message": "EPERM"}
    ) == ChownFailed(code=ChownErrorCode.FAILED, message="EPERM")
