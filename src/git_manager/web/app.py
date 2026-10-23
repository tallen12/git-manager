"""FastAPI application factory."""

from fastapi import FastAPI

from git_manager.health import HealthReporter, HealthStatus


def create_app(*, reporter: HealthReporter, version: str) -> FastAPI:
    """Build the REST application around injected capabilities."""
    app = FastAPI(title="Git Manager", version=version)

    @app.get("/healthz")
    def healthz() -> HealthStatus:
        return reporter.status()

    return app
