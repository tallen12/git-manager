from importlib.metadata import version

from git_manager.metadata import DISTRIBUTION_NAME, package_version


def test_package_version_matches_installed_distribution() -> None:
    assert package_version() == version(DISTRIBUTION_NAME)
