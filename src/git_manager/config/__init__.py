"""Repo config: the schema, its sensitive keys, loading and write-back."""

from git_manager.config.errors import ConfigError
from git_manager.config.file import YamlConfigFile
from git_manager.config.models import BranchConfig, BranchOptions, RepoConfig, VerifyConfig
from git_manager.config.protocols import (
    ConfigOperations,
    ConfigPath,
    ConfigReader,
    ConfigStore,
    RepoConfigSource,
)
from git_manager.config.repo_file import CheckoutRepoConfig
from git_manager.config.sensitivity import SENSITIVE, is_sensitive
from git_manager.config.service import ConfigService

__all__ = [
    "SENSITIVE",
    "BranchConfig",
    "BranchOptions",
    "CheckoutRepoConfig",
    "ConfigError",
    "ConfigOperations",
    "ConfigPath",
    "ConfigReader",
    "ConfigService",
    "ConfigStore",
    "RepoConfig",
    "RepoConfigSource",
    "VerifyConfig",
    "YamlConfigFile",
    "is_sensitive",
]
