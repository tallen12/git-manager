"""The config file on disk: load it, and write edits back in place.

Edits go through ruamel.yaml's round-trip mode, so comments, key order, quoting and the
file's own indentation survive, and only the edited value changes. Writes are atomic: the
new text goes to a temporary file in the same directory, which then replaces the original.
"""

import io
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path

from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.nodes import ScalarNode
from ruamel.yaml.representer import RoundTripRepresenter

from git_manager.config.errors import ConfigError
from git_manager.config.loader import build_config, parse_yaml
from git_manager.config.models import RepoConfig
from git_manager.config.protocols import ConfigPath, RepoConfigSource

# Indentation used when the file has no block mapping or sequence to copy it from.
_DEFAULT_INDENT = 2
# A sequence item's content sits after its dash and one space.
_DASH_WIDTH = 2


class _Representer(RoundTripRepresenter):
    """Writes ``None`` as ``null``, as the spec's example does, instead of leaving it empty."""


def _represent_null(representer: RoundTripRepresenter, _data: None) -> ScalarNode:
    return representer.represent_scalar("tag:yaml.org,2002:null", "null")


_Representer.add_representer(type(None), _represent_null)


def _round_trip() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.Representer = _Representer
    return yaml


def _is_block(node: CommentedMap | CommentedSeq) -> bool:
    return len(node) > 0 and not node.fa.flow_style()


def _guess_indent(node: object, found: dict[str, int]) -> dict[str, int]:
    """Measure the file's mapping and sequence indentation from the first block of each.

    ruamel.yaml writes with fixed indentation, which would reformat a file written in
    another style; its own ``load_yaml_guess_indent`` mistakes indented sequences for the
    mapping indent.
    """
    if isinstance(node, CommentedMap):
        for key, value in node.items():
            key_column = node.lc.key(key)[1]
            if isinstance(value, CommentedMap) and _is_block(value):
                found.setdefault("mapping", value.lc.col - key_column)
            if isinstance(value, CommentedSeq) and _is_block(value):
                found.setdefault("sequence", value.lc.item(0)[1] - key_column)
            _guess_indent(value, found)
    elif isinstance(node, CommentedSeq):
        for item in node:
            _guess_indent(item, found)
    return found


def _writer_for(document: object) -> YAML:
    yaml = _round_trip()
    found = _guess_indent(document, {})
    mapping = found.get("mapping", _DEFAULT_INDENT)
    sequence = max(found.get("sequence", mapping), _DASH_WIDTH)
    yaml.indent(mapping=mapping, sequence=sequence, offset=sequence - _DASH_WIDTH)
    return yaml


def _dotted(path: ConfigPath) -> str:
    return ".".join(str(part) for part in path) or "(root)"


def _to_yaml(value: object, *, source: str, path: ConfigPath) -> object:
    """Check ``value`` is plain YAML data and copy it into round-trip containers."""
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Mapping):
        mapping = CommentedMap()
        for key, item in value.items():
            if not isinstance(key, str):
                raise ConfigError(source, [f"{_dotted(path)}: mapping keys must be strings"])
            mapping[key] = _to_yaml(item, source=source, path=[*path, key])
        return mapping
    if isinstance(value, list | tuple):
        return CommentedSeq(
            _to_yaml(item, source=source, path=[*path, index]) for index, item in enumerate(value)
        )
    message = f"{_dotted(path)}: {type(value).__name__} is not plain YAML data"
    raise ConfigError(source, [message])


def _child(node: object, part: str | int, *, source: str, path: ConfigPath) -> object:
    """The container at ``part`` inside ``node``, creating missing mappings on the way."""
    match node, part:
        case CommentedMap(), str():
            child = node.get(part)
            if child is None:
                child = CommentedMap()
                node[part] = child
        case CommentedSeq(), int() if -len(node) <= part < len(node):
            child = node[part]
        case CommentedSeq(), int():
            raise ConfigError(source, [f"{_dotted(path)}: no list item {part}"])
        case _:
            raise ConfigError(source, [f"{_dotted(path)}: cannot go into this key"])
    if not isinstance(child, CommentedMap | CommentedSeq):
        raise ConfigError(source, [f"{_dotted(path)}: cannot go into a {type(child).__name__}"])
    return child


def _assign(document: CommentedMap, path: ConfigPath, value: object, *, source: str) -> None:
    if not path:
        raise ConfigError(source, ["(root): name the key to set"])
    node: object = document
    for depth, part in enumerate(path[:-1]):
        node = _child(node, part, source=source, path=path[: depth + 1])
    last = path[-1]
    match node, last:
        case CommentedMap(), str():
            node[last] = value
        case CommentedSeq(), int() if -len(node) <= last < len(node):
            node[last] = value
        case _:
            raise ConfigError(source, [f"{_dotted(path)}: cannot set this key"])


def write_atomically(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` so readers see the old file or the new one, never half.

    Follows a symlinked config to its target, so the link (as Docker and Kubernetes mount
    config) is kept, and keeps the file's permission bits.
    """
    target = path.resolve()
    mode = stat.S_IMODE(target.stat().st_mode)
    descriptor, temporary = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(mode)
        temporary_path.replace(target)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


class YamlConfigFile:
    """``ConfigStore`` for a YAML config file, layered with ``GM_*`` and the repo's file."""

    def __init__(
        self, path: Path, *, environ: Mapping[str, str], repo_config: RepoConfigSource
    ) -> None:
        self._path = path
        self._environ = environ
        self._repo_config = repo_config

    @property
    def path(self) -> Path:
        """The config file this store reads and writes."""
        return self._path

    def _read(self) -> str:
        try:
            return self._path.read_text(encoding="utf-8")
        except OSError as error:
            raise ConfigError(str(self._path), [f"cannot read the file: {error}"]) from error

    def _build(self, text: str) -> RepoConfig:
        source = str(self._path)
        return build_config(
            parse_yaml(text, source=source),
            source=source,
            environ=self._environ,
            repo_config=self._repo_config,
        )

    def load(self) -> RepoConfig:
        """Read and validate the file with every other layer; raise ``ConfigError``."""
        return self._build(self._read())

    def set(self, path: ConfigPath, value: object) -> RepoConfig:
        """Set the YAML value at ``path`` and write the file back, keeping its comments."""
        source = str(self._path)
        text = self._read()
        try:
            loaded: object = _round_trip().load(text)
        except YAMLError as error:
            raise ConfigError(source, [str(error)]) from error
        document = CommentedMap() if loaded is None else loaded
        if not isinstance(document, CommentedMap):
            raise ConfigError(source, ["the document must be a mapping of config sections"])
        # Measured before the edit: new nodes have no position in the file.
        writer = _writer_for(document)
        _assign(document, path, _to_yaml(value, source=source, path=path), source=source)
        output = io.StringIO()
        writer.dump(document, output)
        new_text = output.getvalue()
        # Validate the result before it replaces the file, so a bad edit never lands.
        config = self._build(new_text)
        write_atomically(self._path, new_text)
        return config
