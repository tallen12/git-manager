"""REST server settings (the ``http`` section)."""

from pydantic import BaseModel, ConfigDict, Field


class HttpSettings(BaseModel):
    """Where ``serve`` listens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = Field(
        default="127.0.0.1", description="Address the REST server binds. [env: GM_HTTP__HOST]"
    )
    port: int = Field(
        default=8765, ge=1, le=65535, description="REST server port. [env: GM_HTTP__PORT]"
    )
