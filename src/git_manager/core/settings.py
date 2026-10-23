"""Settings for every entry point (CLI commands, ``serve`` and ``mcp stdio``).

``Settings`` composes one section per domain: ``target`` (``core.targets``), ``http``
(``web.settings``) and ``mcp`` (``mcp.settings``). The domain sections are plain models;
only this class reads sources. Sources, highest first: init arguments (CLI flags),
``GM_*`` environment variables, a ``.env`` file in the current directory, files in the
secrets directory, the YAML settings file, then defaults. Nested values merge across
sources, except the target: the highest source that names one (``config``, ``url`` or
``socket``) supplies it, so ``--socket`` replaces a ``url`` from the settings file.
"""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, override

from cyclopts import Parameter
from pydantic import BaseModel, Field, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    NestedSecretsSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from git_manager.core.targets import (
    HTTP_ONLY_OPTIONS,
    NO_TARGET,
    TARGET_BOUND_OPTIONS,
    TARGET_OPTIONS,
    Target,
)
from git_manager.mcp.settings import McpSettings
from git_manager.web.settings import HttpSettings

SETTINGS_FILE_VARIABLE = "GM_SETTINGS_FILE"
DEFAULT_SETTINGS_FILE = Path("git-manager.yaml")
SECRETS_DIR_VARIABLE = "GM_SECRETS_DIR"
# Docker and compose mount secrets here.
DEFAULT_SECRETS_DIR = Path("/run/secrets")


def _names_target(target: object) -> bool:
    if isinstance(target, BaseModel):
        return True
    return isinstance(target, Mapping) and any(
        target.get(option) is not None for option in TARGET_OPTIONS
    )


def _merge(higher: Mapping[str, object], lower: Mapping[str, object]) -> dict[str, object]:
    """Deep-merge two source dicts; ``higher`` wins on conflicts."""
    merged = dict(lower)
    for key, value in higher.items():
        below = merged.get(key)
        if isinstance(value, Mapping) and isinstance(below, Mapping):
            merged[key] = _merge(value, below)
        else:
            merged[key] = value
    return merged


class _TargetPrecedenceSource(PydanticBaseSettingsSource):
    """Merges the real sources, highest first, choosing the target from one source only.

    Plain deep merging would combine ``url`` from the settings file with ``--socket`` from a
    flag and fail as two targets. Here the highest source that names a target wins it, and
    lower sources lose their target-naming options. A lower source that names its own
    target also loses ``plain_http``, so an opt-in written for one URL never reaches
    another; a ``plain_http`` set on its own is a general policy and merges. Other target
    values, like a token, still merge from any source.
    """

    def __init__(
        self, settings_cls: type[BaseSettings], sources: Sequence[PydanticBaseSettingsSource]
    ) -> None:
        super().__init__(settings_cls)
        self._sources = sources

    @override
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[object, str, bool]:
        # Values come from the wrapped sources in __call__, never field by field.
        return None, field_name, False

    @override
    def __call__(self) -> dict[str, object]:
        merged: dict[str, object] = {}
        target_chosen = False
        for source in self._sources:
            values: dict[str, object] = dict(source())
            target = values.get("target")
            if target_chosen and isinstance(target, Mapping):
                dropped = TARGET_BOUND_OPTIONS if _names_target(target) else TARGET_OPTIONS
                values["target"] = {
                    key: value for key, value in target.items() if key not in dropped
                }
            elif _names_target(target):
                target_chosen = True
            merged = _merge(merged, values)
        return merged


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
        if target.get("url") is None:
            target = {key: value for key, value in target.items() if key not in HTTP_ONLY_OPTIONS}
        if not any(target.get(key) is not None for key in TARGET_OPTIONS):
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
        sources = (
            init_settings,
            env_settings,
            dotenv_settings,
            # Passed here, not in model_config: pydantic-settings cannot see this source
            # inside the wrapper below and would warn that the config keys are unused.
            NestedSecretsSettingsSource(
                file_secret_settings,
                secrets_dir=secrets_dir,
                secrets_dir_missing="ok",
                secrets_nested_delimiter="__",
            ),
            YamlConfigSettingsSource(settings_cls, yaml_file=settings_file),
        )
        return (_TargetPrecedenceSource(settings_cls, sources),)
