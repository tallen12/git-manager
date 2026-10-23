"""Health commands."""

import sys
from typing import Annotated

from cyclopts import App, Parameter

from git_manager.core import (
    ApiError,
    ApiResponseError,
    ApiUnreachableError,
    Connector,
    OperationError,
    Settings,
)


def register(app: App, *, connect: Connector) -> None:
    """Add ``doctor`` to ``app``."""

    @app.command
    async def doctor(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Print the health status as JSON, in local or API mode."""
        async with connect(settings.target) as operations:
            try:
                status = await operations.health.status()
            except (ApiError, ApiResponseError, ApiUnreachableError, OperationError) as error:
                print(f"error: {error}", file=sys.stderr)
                sys.exit(1)
        print(status.model_dump_json())
