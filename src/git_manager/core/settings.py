"""Settings that choose where operations run, shared by the CLI, REST and MCP entry points.

The cyclopts ``Parameter`` annotations only shape the CLI flags; pydantic ignores them, so
REST and MCP startup read the same model from ``GM_*`` variables without the CLI.
"""

from pathlib import Path
from typing import Annotated, Self

from cyclopts import Parameter
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    FilePath,
    HttpUrl,
    PrivateAttr,
    SecretStr,
    Tag,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    """Run operations through the REST API over HTTP (API mode).

    The token comes from exactly one of ``GM_TARGET__TOKEN`` and ``--token-file``;
    ``bearer_token()`` returns it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: HttpUrlStr = Field(description="Daemon URL; run through the API. [env: GM_TARGET__URL]")
    # Environment only, so the token never lands in shell history.
    token: Annotated[SecretStr | None, Parameter(parse=False)] = None
    token_file: FilePath | None = Field(
        default=None,
        description=(
            "File holding the API token for --url. [env: GM_TARGET__TOKEN_FILE, GM_TARGET__TOKEN]"
        ),
    )

    _bearer_token: SecretStr = PrivateAttr()

    @model_validator(mode="after")
    def _resolve_token(self) -> Self:
        match (self.token, self.token_file):
            case (SecretStr() as token, None):
                self._bearer_token = token
            case (None, Path() as token_file):
                token = token_file.read_text(encoding="utf-8").strip()
                if not token:
                    msg = f"token file {token_file} is empty"
                    raise ValueError(msg)
                self._bearer_token = SecretStr(token)
            case (None, None):
                msg = "--url needs a token: set GM_TARGET__TOKEN or pass --token-file"
                raise ValueError(msg)
            case _:
                msg = "set only one of GM_TARGET__TOKEN and --token-file"
                raise ValueError(msg)
        return self

    def bearer_token(self) -> SecretStr:
        """Return the API token, read from the environment or the token file."""
        return self._bearer_token


class SocketTarget(BaseModel):
    """Run operations through the REST API over the daemon's Unix socket (API mode)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    socket: Path = Field(
        description="Daemon Unix socket; run through the API. [env: GM_TARGET__SOCKET]"
    )


# Each variant is picked by the one option that identifies it, so there is no ``kind``
# flag, and setting none or several of them fails validation.
_TARGET_TAGS = {"config": "local", "url": "http", "socket": "socket"}
_NO_TARGET = (
    "no target: pass --config (local mode), or --url with GM_TARGET__TOKEN or "
    "--token-file, or --socket (API mode); or set the matching GM_TARGET__* variables"
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


class Settings(BaseSettings):
    """Where operations run, from init arguments (CLI flags) and ``GM_*`` variables.

    The CLI flattens the target's fields into plain flags (``--config``, ``--url``,
    ``--token-file``, ``--socket``); the environment uses nested ``GM_TARGET__*``
    variables. Init arguments are merged over the environment, so a flag overrides its
    variable, and a flag for one target plus a variable for another fails validation.
    """

    model_config = SettingsConfigDict(env_prefix="GM_", env_nested_delimiter="__")

    target: Annotated[Target, Parameter(name="*")]

    @model_validator(mode="before")
    @classmethod
    def _require_target(cls, data: object) -> object:
        if isinstance(data, dict) and not data.get("target"):
            raise ValueError(_NO_TARGET)
        return data
