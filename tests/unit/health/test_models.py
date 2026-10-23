import pytest
from pydantic import ValidationError

from git_manager.health import HealthStatus


def test_status_other_than_ok_is_rejected() -> None:
    with pytest.raises(ValidationError):
        HealthStatus.model_validate({"status": "degraded", "version": "1.0.0"})


def test_status_round_trips_through_json() -> None:
    status = HealthStatus(status="ok", version="1.0.0")

    assert HealthStatus.model_validate_json(status.model_dump_json()) == status
