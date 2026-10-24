"""Operations through the REST API, as an httpx client."""

import httpx

from git_manager.web.api_client import ApiClient
from git_manager.web.branches import HttpBranchOperations
from git_manager.web.config import HttpConfigOperations
from git_manager.web.events import HttpEventOperations
from git_manager.web.health import HttpHealthOperations
from git_manager.web.runs import HttpRunOperations


class HttpOperations:
    """Implements ``Operations`` by calling a running daemon's REST API.

    Operation errors come back as the typed errors ``Service`` raises (``web.errors``).
    The caller owns the injected client and closes it.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        api = ApiClient(client)
        self.health = HttpHealthOperations(api)
        self.config = HttpConfigOperations(api)
        self.branches = HttpBranchOperations(api)
        self.runs = HttpRunOperations(api)
        self.events = HttpEventOperations(api)
