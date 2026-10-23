from fastapi.testclient import TestClient

from git_manager.core import Operations
from git_manager.web.app import create_app
from tests.conftest import TEST_VERSION


def test_health_endpoint_reports_ok(service: Operations) -> None:
    client = TestClient(create_app(operations=service, version=TEST_VERSION))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": TEST_VERSION}
