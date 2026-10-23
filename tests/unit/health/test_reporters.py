from git_manager.health import HealthStatus, StaticHealthReporter


def test_static_reporter_reports_ok_with_its_version() -> None:
    reporter = StaticHealthReporter(version="1.2.3")

    assert reporter.status() == HealthStatus(status="ok", version="1.2.3")
