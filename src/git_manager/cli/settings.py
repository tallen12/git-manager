"""Client settings that choose where CLI operations run."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FilePath,
    HttpUrl,
    PrivateAttr,
    SecretStr,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class LocalTarget(BaseModel):
    """Run operations in-process against a config file (local mode)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["local"] = "local"
    config: Path


class HttpTarget(BaseModel):
    """Run operations through the REST API over HTTP (API mode)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["http"] = "http"
    url: HttpUrl
    token: SecretStr


class SocketTarget(BaseModel):
    """Run operations through the REST API over the daemon's Unix socket (API mode)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["socket"] = "socket"
    socket: Path


Target = Annotated[LocalTarget | HttpTarget | SocketTarget, Field(discriminator="kind")]


class ClientSettings(BaseSettings):
    """Where CLI operations run, from CLI flags (init arguments) and ``GM_*`` variables.

    Init arguments outrank the environment, so a flag always overrides a variable.
    Validation allows exactly one target; ``target()`` returns it.
    """

    model_config = SettingsConfigDict(env_prefix="GM_")

    config: FilePath | None = None
    url: HttpUrl | None = None
    # Environment only, so the token never lands in shell history.
    token: SecretStr | None = None
    token_file: FilePath | None = None
    socket: Path | None = None

    _target: LocalTarget | HttpTarget | SocketTarget = PrivateAttr()

    @model_validator(mode="after")
    def _resolve_target(self) -> Self:
        chosen = [
            option
            for option, value in (
                ("--config / GM_CONFIG", self.config),
                ("--url / GM_URL", self.url),
                ("--socket / GM_SOCKET", self.socket),
            )
            if value is not None
        ]
        if not chosen:
            msg = (
                "no target: pass --config (local mode), or --url with GM_TOKEN or "
                "--token-file, or --socket (API mode); or set the matching GM_* variables"
            )
            raise ValueError(msg)
        if len(chosen) > 1:
            msg = f"choose one target, got {' and '.join(chosen)}"
            raise ValueError(msg)

        if self.config is not None:
            self._target = LocalTarget(config=self.config)
        elif self.socket is not None:
            self._target = SocketTarget(socket=self.socket)
        elif self.url is not None:
            self._target = HttpTarget(url=self.url, token=self._read_token())
        return self

    def _read_token(self) -> SecretStr:
        match (self.token, self.token_file):
            case (SecretStr() as token, None):
                return token
            case (None, Path() as token_file):
                token = token_file.read_text(encoding="utf-8").strip()
                if not token:
                    msg = f"token file {token_file} is empty"
                    raise ValueError(msg)
                return SecretStr(token)
            case (None, None):
                msg = "--url needs a token: set GM_TOKEN or pass --token-file / GM_TOKEN_FILE"
                raise ValueError(msg)
            case _:
                msg = "set only one of GM_TOKEN and --token-file / GM_TOKEN_FILE"
                raise ValueError(msg)

    def target(self) -> LocalTarget | HttpTarget | SocketTarget:
        """Return the one target the settings select."""
        return self._target
