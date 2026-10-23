"""Turn config YAML into the validated, effective ``RepoConfig``.

The functions here are pure apart from the injected ``RepoConfigSource``: reading and
writing the config file itself belongs to ``config.file``.
"""

from collections.abc import Mapping, Sequence

from pydantic import ValidationError
from pydantic_core import ErrorDetails
from ruamel.yaml import YAML, YAMLError

from git_manager.config.errors import ConfigError
from git_manager.config.merge import deep_merge, env_overrides, layer
from git_manager.config.models import RepoConfig, RepoSection
from git_manager.config.protocols import RepoConfigSource

REPO_CONFIG_SOURCE = "the repo's .git-manager.yaml"
# A trusted repo file may only tune branch behavior; where the repo lives, its
# credentials, the budget and which branches are tracked stay with the operator.
_REPO_FILE_SECTIONS = frozenset({"defaults"})


def _string_keys(mapping: Mapping[object, object]) -> dict[str, object]:
    return {str(key): value for key, value in mapping.items()}


def plain(node: object) -> object:
    """Copy a loaded YAML tree into plain dicts and lists with string keys."""
    if isinstance(node, Mapping):
        return {str(key): plain(value) for key, value in node.items()}
    if isinstance(node, list):
        return [plain(item) for item in node]
    return node


def parse_yaml(text: str, *, source: str) -> dict[str, object]:
    """Parse one config document into plain data; an empty document is an empty mapping."""
    try:
        loaded: object = YAML(typ="rt").load(text)
    except YAMLError as error:
        raise ConfigError(source, [str(error)]) from error
    document = plain(loaded)
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ConfigError(source, ["the document must be a mapping of config sections"])
    return _string_keys(document)


def _location(loc: Sequence[str | int], document: Mapping[str, object]) -> str:
    # Name branches rather than numbering them: ``branches[feature/x].verify.test``.
    parts: list[str] = []
    for index, part in enumerate(loc):
        if index == 1 and loc[0] == "branches" and isinstance(part, int):
            branches = document.get("branches")
            entry = branches[part] if isinstance(branches, list) else None
            name = entry.get("name") if isinstance(entry, dict) else None
            parts[-1] = f"branches[{name if isinstance(name, str) else part}]"
        else:
            parts.append(str(part))
    return ".".join(parts)


def _describe(detail: ErrorDetails, document: Mapping[str, object]) -> str:
    message = detail["msg"].removeprefix("Value error, ")
    location = _location(detail["loc"], document)
    return f"{location}: {message}" if location else message


def describe_errors(error: ValidationError, document: Mapping[str, object]) -> list[str]:
    """One line per validation problem, each led by its config path."""
    return [_describe(detail, document) for detail in error.errors()]


def _repo_defaults(text: str) -> dict[str, object]:
    document = parse_yaml(text, source=REPO_CONFIG_SOURCE)
    extra = sorted(set(document) - _REPO_FILE_SECTIONS)
    if extra:
        problems = [f"{key}: only defaults: may be set in the repo" for key in extra]
        raise ConfigError(REPO_CONFIG_SOURCE, problems)
    defaults = document.get("defaults")
    if defaults is None:
        return {}
    if not isinstance(defaults, dict):
        raise ConfigError(REPO_CONFIG_SOURCE, ["defaults: must be a mapping"])
    return _string_keys(defaults)


def _trusted_repo_defaults(
    document: Mapping[str, object],
    overrides: Mapping[str, object],
    *,
    repo_config: RepoConfigSource,
) -> dict[str, object]:
    """The repo file's ``defaults:``, read only when the operator trusts the repo."""
    file_repo = document.get("repo")
    env_repo = overrides.get("repo")
    section = deep_merge(
        file_repo if isinstance(file_repo, dict) else {},
        env_repo if isinstance(env_repo, dict) else {},
    )
    try:
        repo = RepoSection.model_validate(section)
    except ValidationError:
        # Reported with the whole document; without a valid repo section there is no
        # trust decision to make.
        return {}
    if not repo.trust_repo_config:
        return {}
    text = repo_config.read(data_dir=repo.data_dir)
    return {} if text is None else _repo_defaults(text)


def build_config(
    document: Mapping[str, object],
    *,
    source: str,
    environ: Mapping[str, str],
    repo_config: RepoConfigSource,
) -> RepoConfig:
    """Layer ``document`` (the parsed config file) with every other source and validate.

    Raises ``ConfigError`` listing every problem, labelled with ``source``; a repo file
    that sets more than ``defaults:`` is reported under its own name.
    """
    overrides = env_overrides(environ)
    repo_defaults = _trusted_repo_defaults(document, overrides, repo_config=repo_config)
    merged = layer(document, repo_defaults=repo_defaults, overrides=overrides)
    try:
        return RepoConfig.model_validate(merged)
    except ValidationError as error:
        raise ConfigError(source, describe_errors(error, merged)) from error
