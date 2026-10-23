"""Settings for every entry point (CLI commands, ``serve`` and ``mcp stdio``).

``Settings`` composes one section per domain: ``target`` (``core.targets``), ``http``
(``web.settings``) and ``mcp`` (``mcp.settings``). The domain sections are plain models;
only this class reads sources. Sources, highest first: init arguments (CLI flags),
``GM_*`` environment variables, a ``.env`` file in the current directory, files in the
secrets directory, the YAML settings file, then defaults. Nested values merge across
sources.
"""

import os
from pathlib import Path
from typing import Annotated, override

from cyclopts import Parameter
from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    NestedSecretsSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from git_manager.core.targets import NO_TARGET, Target
from git_manager.mcp.settings import McpSettings
from git_manager.web.settings import HttpSettings

SETTINGS_FILE_VARIABLE = "GM_SETTINGS_FILE"
DEFAULT_SETTINGS_FILE = Path("git-manager.yaml")
SECRETS_DIR_VARIABLE = "GM_SECRETS_DIR"
# Docker and compose mount secrets here.
DEFAULT_SECRETS_DIR = Path("/run/secrets")


class Settings(BaseSettings):
    """Settings for one invocation, merged from every source.

    The CLI flattens ``target`` into plain flags (``--config``, ``--url``, ``--socket``)
    and keeps the sections as dotted flags (``--http.port``, ``--mcp.name``).
    """

    model_config = SettingsConfigDict(
        env_prefix="GM_",
        env_nested_delimiter="__",
        env_file=".env",
        # Other variables in .env (without the GM_ prefix) are not ours to reject.
        dotenv_filtering="only_existing",
        secrets_nested_delimiter="__",
        secrets_dir_missing="ok",
        extra="forbid",
    )

    target: Annotated[Target, Parameter(name="*")]
    http: HttpSettings = Field(default_factory=HttpSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)

    @model_validator(mode="before")
    @classmethod
    def _shape_target(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        target = data.get("target")
        if target is None:
            raise ValueError(NO_TARGET)
        if not isinstance(target, dict):
            return data
        # One secrets directory or environment serves every mode: a token only means
        # something next to a URL, so a local or socket target ignores it.
        if target.get("url") is None and "token" in target:
            target = {key: value for key, value in target.items() if key != "token"}
        if not any(target.get(key) is not None for key in ("config", "url", "socket")):
            raise ValueError(NO_TARGET)
        return {**data, "target": target}

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        settings_file = Path(os.environ.get(SETTINGS_FILE_VARIABLE, DEFAULT_SETTINGS_FILE))
        secrets_dir = Path(os.environ.get(SECRETS_DIR_VARIABLE, DEFAULT_SECRETS_DIR))
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            NestedSecretsSettingsSource(file_secret_settings, secrets_dir=secrets_dir),
            YamlConfigSettingsSource(settings_cls, yaml_file=settings_file),
        )
