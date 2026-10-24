"""Reads the managed repo's ``.git-manager.yaml`` from the clone in the data directory."""

from pathlib import Path

REPO_CONFIG_NAME = ".git-manager.yaml"
# The clone's place in the data directory (see the spec: ``/data/repo``).
CLONE_DIR = "repo"


class CheckoutRepoConfig:
    """``RepoConfigSource`` that reads the file from the clone's working tree."""

    def read(self, *, data_dir: Path) -> str | None:
        """Return ``<data_dir>/repo/.git-manager.yaml``, or ``None`` if it does not exist."""
        path = data_dir / CLONE_DIR / REPO_CONFIG_NAME
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
