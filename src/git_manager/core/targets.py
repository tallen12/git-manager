"""Targets: where operations run (in-process or through a daemon's REST API).

The cyclopts ``Parameter`` annotations only shape the CLI flags; pydantic ignores them, so
REST and MCP startup read the same models without the CLI.
"""

import re
from enum import StrEnum
from ipaddress import ip_address
from pathlib import Path
from socket import inet_aton
from typing import Annotated, Self, assert_never

import httpx
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


_IPV4_SHORTHAND = re.compile(r"\d+(\.\d+){0,3}")


class PlainHttp(StrEnum):
    """Where an ``http://`` URL may carry the API token unencrypted."""

    LOOPBACK = "loopback"
    ALLOWED = "allowed"


def _is_loopback(host: str) -> bool:
    # A trailing dot is the fully qualified spelling of the same name.
    name = host.lower().removesuffix(".")
    # RFC 6761 reserves localhost and every name under it for loopback.
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return ip_address(name).is_loopback
    except ValueError:
        pass
    # Shorthand IPv4 like 127.1, which the resolver expands but ip_address rejects.
    if _IPV4_SHORTHAND.fullmatch(name):
        try:
            return ip_address(inet_aton(name)).is_loopback
        except OSError:
            return False
    return False


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
    plain_http: PlainHttp = Field(
        default=PlainHttp.LOOPBACK,
        description=(
            "Where an http:// --url may send the token: loopback hosts only, or allowed "
            "anywhere. [env: GM_TARGET__PLAIN_HTTP]"
        ),
    )

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

    @model_validator(mode="after")
    def _protect_token(self) -> Self:
        match self.plain_http:
            case PlainHttp.ALLOWED:
                return self
            case PlainHttp.LOOPBACK:
                url = httpx.URL(self.url)
                if url.scheme == "http" and not _is_loopback(url.host):
                    msg = (
                        f"--url {self.url} would send the token unencrypted: use https, a "
                        "loopback host, or --plain-http allowed"
                    )
                    raise ValueError(msg)
                return self
            case _:
                assert_never(self.plain_http)


class SocketTarget(BaseModel):
    """Run operations through the REST API over the daemon's Unix socket (API mode)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    socket: Path = Field(
        description="Daemon Unix socket; run through the API. [env: GM_TARGET__SOCKET]"
    )


# Each variant is picked by the one option that identifies it, so there is no ``kind``
# flag, and setting none or several of them fails validation.
_TARGET_TAGS = {"config": "local", "url": "http", "socket": "socket"}
# The options that name a target; any one of them chooses the variant.
TARGET_OPTIONS = frozenset(_TARGET_TAGS)
# Options that come only from the source that names the target. ``plain_http`` is here so an
# ``allowed`` written for one URL never applies to another URL from a higher source.
TARGET_BOUND_OPTIONS = TARGET_OPTIONS | {"plain_http"}
# Options that only mean something next to a URL. One environment or secrets directory
# serves every mode, so a local or socket target ignores them.
HTTP_ONLY_OPTIONS = frozenset({"token", "plain_http"})
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
