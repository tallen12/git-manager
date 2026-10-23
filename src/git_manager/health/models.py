"""Health value types."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthStatus(BaseModel):
    """Liveness report returned by every interface."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    version: str
