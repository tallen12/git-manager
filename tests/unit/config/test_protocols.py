from pathlib import Path

from git_manager.config import (
    CheckoutRepoConfig,
    ConfigOperations,
    ConfigReader,
    ConfigService,
    ConfigStore,
    RepoConfigSource,
    YamlConfigFile,
)
from git_manager.core.unavailable import UnavailableConfig


def test_unavailable_config_satisfies_the_protocol() -> None:
    # The annotation is the contract: the type checker rejects a non-conforming class.
    operations: ConfigOperations = UnavailableConfig("later")

    assert operations is not None


def test_config_implementations_satisfy_their_protocols(tmp_path: Path) -> None:
    repo_config: RepoConfigSource = CheckoutRepoConfig()
    store: ConfigStore = YamlConfigFile(tmp_path / "c.yaml", environ={}, repo_config=repo_config)

    def open_config(path: Path) -> YamlConfigFile:
        return YamlConfigFile(path, environ={}, repo_config=repo_config)

    reader: ConfigReader = open_config
    operations: ConfigOperations = ConfigService(store)

    assert reader(tmp_path / "c.yaml").path == tmp_path / "c.yaml"
    assert operations is not None
