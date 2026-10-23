"""Git Manager: keeps git branches rebased inside an isolated container."""


def main() -> None:
    """Console entry point for ``git-manager`` (also runnable as ``git manager``)."""
    from git_manager.cli.main import main as run

    run()
