"""Helpers used only by the CLI tests."""

from pathlib import Path

from git_manager.config import YamlConfigFile
from tests.unit.config.conftest import StaticRepoConfig


def read_config(path: Path) -> YamlConfigFile:
    """Open a config file with no ``GM_*`` overrides and no repo ``.git-manager.yaml``."""
    return YamlConfigFile(path, environ={}, repo_config=StaticRepoConfig())
