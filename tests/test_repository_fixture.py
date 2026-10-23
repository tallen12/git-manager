import subprocess
from pathlib import Path


def test_repository_fixture_creates_git_repo(repository: Path) -> None:
    assert (repository / ".git").is_dir()


def test_repository_fixture_ignores_global_and_system_config(repository: Path) -> None:
    listing = subprocess.run(
        ["git", "-C", str(repository), "config", "--list", "--show-scope"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )

    scopes = {line.split("\t", 1)[0] for line in listing.stdout.splitlines()}
    assert scopes == {"local"}
