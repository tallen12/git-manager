"""REST server settings (the ``http`` section)."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class HttpSettings(BaseModel):
    """Where ``serve`` listens, and the tokens it accepts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = Field(
        default="127.0.0.1", description="Address the REST server binds. [env: GM_HTTP__HOST]"
    )
    port: int = Field(
        default=8765, ge=1, le=65535, description="REST server port. [env: GM_HTTP__PORT]"
    )
    tokens_file: Path | None = Field(
        default=None,
        description=(
            "YAML file of API tokens and their scopes; serve needs it, since every HTTP "
            "request needs a token. [env: GM_HTTP__TOKENS_FILE]"
        ),
    )
    socket: Path | None = Field(
        default=None,
        description=(
            "Unix socket to serve REST on as well, mode 0660 with its directory's group; "
            "requests over it have every scope. [env: GM_HTTP__SOCKET]"
        ),
    )
