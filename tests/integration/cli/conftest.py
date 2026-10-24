"""A bare remote and a local-mode config managing it, for the CLI's end-to-end tests."""

from pathlib import Path

import pytest

from tests.integration.rebasing.conftest import Remote, make_remote


def write_config(path: Path, *, remote: Remote, data_dir: Path) -> Path:
    """A config managing ``remote.bare`` from ``data_dir``, verifying with ``true``."""
    path.write_text(
        f"repo:\n  url: {remote.bare}\n  data_dir: {data_dir}\n"
        "defaults:\n  verify:\n    test: 'true'\n    docker: {mode: none}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def remote(tmp_path: Path) -> Remote:
    return make_remote(tmp_path)


@pytest.fixture
def config_file(remote: Remote, tmp_path: Path) -> Path:
    return write_config(tmp_path / "config.yaml", remote=remote, data_dir=tmp_path / "data")
