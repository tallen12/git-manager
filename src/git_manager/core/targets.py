"""Targets: where operations run (in-process or through a daemon's REST API).

The cyclopts ``Parameter`` annotations only shape the CLI flags; pydantic ignores them, so
REST and MCP startup read the same models without the CLI.
"""

from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    FilePath,
    HttpUrl,
    SecretStr,
    Tag,
    TypeAdapter,
    ValidationError,
    model_validator,
)

_HTTP_URL: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)


def _check_http_url(value: str) -> str:
    try:
        _HTTP_URL.validate_python(value)
    except ValidationError as error:
        msg = f"invalid --url {value!r}: {error.errors()[0]['msg']}"
        raise ValueError(msg) from error
    return value


# A checked ``str`` rather than ``HttpUrl``: cyclopts recurses forever while inspecting
# pydantic's URL class.
HttpUrlStr = Annotated[str, AfterValidator(_check_http_url)]


class LocalTarget(BaseModel):
    """Run operations in-process against a config file (local mode)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    config: FilePath = Field(
        description="Config file; run in-process (local mode). [env: GM_TARGET__CONFIG]"
    )


class HttpTarget(BaseModel):
    """Run operations through the REST API over HTTP (API mode)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: HttpUrlStr = Field(description="Daemon URL; run through the API. [env: GM_TARGET__URL]")
    # No flag, so the token never lands in shell history: it comes from GM_TARGET__TOKEN,
    # .env, the settings file or a ``gm_target__token`` file in the secrets directory.
    token: Annotated[SecretStr, Parameter(parse=False)]

    @model_validator(mode="before")
    @classmethod
    def _require_token(cls, data: object) -> object:
        if isinstance(data, dict) and not data.get("token"):
            msg = (
                "--url needs a token: set GM_TARGET__TOKEN or put it in a gm_target__token "
                "file in the secrets directory"
            )
            raise ValueError(msg)
        return data


class SocketTarget(BaseModel):
    """Run operations through the REST API over the daemon's Unix socket (API mode)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    socket: Path = Field(
        description="Daemon Unix socket; run through the API. [env: GM_TARGET__SOCKET]"
    )


# Each variant is picked by the one option that identifies it, so there is no ``kind``
# flag, and setting none or several of them fails validation.
_TARGET_TAGS = {"config": "local", "url": "http", "socket": "socket"}
NO_TARGET = (
    "no target: pass --config (local mode), or --url with a token, or --socket (API mode); "
    "or set target in git-manager.yaml or the GM_TARGET__* variables"
)


def _target_tag(value: object) -> str | None:
    match value:
        case LocalTarget():
            return "local"
        case HttpTarget():
            return "http"
        case SocketTarget():
            return "socket"
        case dict():
            tags = [tag for key, tag in _TARGET_TAGS.items() if value.get(key) is not None]
            return tags[0] if len(tags) == 1 else None
        case _:
            return None


Target = Annotated[
    Annotated[LocalTarget, Tag("local")]
    | Annotated[HttpTarget, Tag("http")]
    | Annotated[SocketTarget, Tag("socket")],
    Discriminator(
        _target_tag,
        custom_error_type="target",
        custom_error_message="choose one target: --config, --url or --socket",
    ),
]
