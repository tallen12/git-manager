"""Layer the raw config documents into the shape of the effective ``RepoConfig``.

Precedence, lowest first: built-in defaults (the models' own), the file's ``defaults:``
block, the repo's ``.git-manager.yaml`` (only when ``trust_repo_config`` is true), each
branch's own block, then ``GM_*`` environment variables. Layers merge as plain dicts
before validation, so a branch block that sets only ``verify.test`` keeps every other
``verify`` value from the layers below it. Mappings merge key by key; lists and scalars
replace the value below them.
"""

import json
from collections.abc import Mapping

# Top-level config sections that ``GM_<SECTION>__...`` variables may override. Settings
# own the other ``GM_*`` names (``GM_TARGET__*``, ``GM_HTTP__*``, ``GM_SETTINGS_FILE``).
ENV_SECTIONS = frozenset({"repo", "budget", "defaults"})
ENV_PREFIX = "GM_"
ENV_DELIMITER = "__"


def deep_merge(lower: Mapping[str, object], higher: Mapping[str, object]) -> dict[str, object]:
    """Merge ``higher`` over ``lower``: mappings key by key, anything else replaced."""
    merged = dict(lower)
    for key, value in higher.items():
        below = merged.get(key)
        if isinstance(value, Mapping) and isinstance(below, Mapping):
            merged[key] = deep_merge(_str_keys(below), _str_keys(value))
        else:
            merged[key] = value
    return merged


def _str_keys(mapping: Mapping[object, object]) -> dict[str, object]:
    return {str(key): value for key, value in mapping.items()}


def _mapping(document: Mapping[str, object], key: str) -> dict[str, object]:
    """The mapping at ``key``, or an empty one when it is missing, null or malformed."""
    value = document.get(key)
    return _str_keys(value) if isinstance(value, Mapping) else {}


def _mergeable(document: Mapping[str, object], key: str) -> bool:
    value = document.get(key)
    return value is None or isinstance(value, Mapping)


def _parse_env_value(raw: str) -> object:
    # Lists and mappings (``notify.on``, ``commits.git_config``) are written as JSON, as
    # pydantic-settings does for complex fields; everything else stays a string for
    # pydantic to coerce.
    if raw.lstrip().startswith(("[", "{")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def env_overrides(environ: Mapping[str, str]) -> dict[str, object]:
    """Nest ``GM_<SECTION>__<KEY>__...`` variables into a partial config document.

    Names are case-insensitive, like the settings' own variables. Only the sections in
    ``ENV_SECTIONS`` are read; ``GM_DEFAULTS__...`` applies to the ``defaults:`` block and
    to every branch, since environment variables are the highest layer.
    """
    overrides: dict[str, object] = {}
    for name, raw in sorted(environ.items()):
        if not name.upper().startswith(ENV_PREFIX):
            continue
        parts = name[len(ENV_PREFIX) :].lower().split(ENV_DELIMITER)
        if len(parts) < 2 or parts[0] not in ENV_SECTIONS or not all(parts):
            continue
        nested: object = _parse_env_value(raw)
        for part in reversed(parts):
            nested = {part: nested}
        if isinstance(nested, dict):
            overrides = deep_merge(overrides, nested)
    return overrides


def layer(
    document: Mapping[str, object],
    *,
    repo_defaults: Mapping[str, object],
    overrides: Mapping[str, object],
) -> dict[str, object]:
    """Merge every layer into a document shaped like the effective ``RepoConfig``.

    ``document`` is the config file, ``repo_defaults`` the ``defaults:`` block of a trusted
    repo ``.git-manager.yaml`` (empty otherwise) and ``overrides`` the result of
    ``env_overrides``. Each branch entry gets the merged defaults below its own block.
    """
    shared = deep_merge(_mapping(document, "defaults"), repo_defaults)
    env_defaults = _mapping(overrides, "defaults")
    merged = dict(document)
    # A section that is not a mapping is left as written, for validation to report.
    for section in ENV_SECTIONS - {"defaults"}:
        section_overrides = _mapping(overrides, section)
        if section_overrides and _mergeable(document, section):
            merged[section] = deep_merge(_mapping(document, section), section_overrides)
    if _mergeable(document, "defaults"):
        merged["defaults"] = deep_merge(shared, env_defaults)
    branches = document.get("branches")
    if isinstance(branches, list):
        merged["branches"] = [
            deep_merge(deep_merge(shared, _str_keys(entry)), env_defaults)
            if isinstance(entry, Mapping)
            else entry
            for entry in branches
        ]
    return merged
