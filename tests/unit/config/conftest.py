"""Fakes used only by the config tests (and the CLI tests that open config files)."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest


@dataclass
class StaticRepoConfig:
    """``RepoConfigSource`` that serves fixed text and records where it was asked to look."""

    text: str | None = None
    reads: list[Path] = field(default_factory=list)

    def read(self, *, data_dir: Path) -> str | None:
        self.reads.append(data_dir)
        return self.text


@pytest.fixture
def repo_config() -> StaticRepoConfig:
    return StaticRepoConfig()
