from pathlib import Path

from git_manager.config import CheckoutRepoConfig


def test_reads_the_file_from_the_clone_in_the_data_directory(tmp_path: Path) -> None:
    clone = tmp_path / "repo"
    clone.mkdir()
    (clone / ".git-manager.yaml").write_text("defaults: {}\n", encoding="utf-8")

    assert CheckoutRepoConfig().read(data_dir=tmp_path) == "defaults: {}\n"


def test_returns_none_when_the_repo_has_no_file(tmp_path: Path) -> None:
    assert CheckoutRepoConfig().read(data_dir=tmp_path) is None
