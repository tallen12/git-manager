from git_manager.health import HealthOperations, HealthService, StaticHealthReporter


async def test_health_service_reports_the_reporter_status() -> None:
    operations: HealthOperations = HealthService(reporter=StaticHealthReporter(version="1.2.3"))

    status = await operations.status()

    assert (status.status, status.version) == ("ok", "1.2.3")
