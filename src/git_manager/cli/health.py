"""Health commands."""

from typing import Annotated

from cyclopts import App, Parameter

from git_manager.cli.output import reported
from git_manager.core import Connector, Settings


def register(app: App, *, connect: Connector) -> None:
    """Add ``doctor`` to ``app``."""

    @app.command
    async def doctor(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Print the health status as JSON, in local or API mode."""
        with reported():
            async with connect(settings.target) as operations:
                status = await operations.health.status()
        print(status.model_dump_json())
