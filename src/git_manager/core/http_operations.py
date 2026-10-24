"""Operations through the REST API, as an httpx client."""

import httpx

from git_manager.core.unavailable import (
    UnavailableBranches,
    UnavailableConfig,
    UnavailableEvents,
    UnavailableRuns,
)
from git_manager.web.api_client import ApiClient
from git_manager.web.health import HttpHealthOperations

# Rule 5 of the feature plan: M1 operations reach REST together in M2.
NOT_IN_API_YET = "not in the REST API yet (M2); run it in local mode with --config"


class HttpOperations:
    """Implements ``Operations`` by calling a running daemon's REST API.

    The caller owns the injected client and closes it.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        api = ApiClient(client)
        self.health = HttpHealthOperations(api)
        self.config = UnavailableConfig(NOT_IN_API_YET)
        self.branches = UnavailableBranches(NOT_IN_API_YET)
        self.runs = UnavailableRuns(NOT_IN_API_YET)
        # The SSE client lands with ``git-manager watch`` (F12b).
        self.events = UnavailableEvents(NOT_IN_API_YET)
