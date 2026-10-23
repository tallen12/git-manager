from git_manager.health import HealthReporter, StaticHealthReporter


def test_static_reporter_satisfies_health_reporter() -> None:
    # The annotation is the contract: the type checker rejects a non-conforming reporter.
    reporter: HealthReporter = StaticHealthReporter(version="1.2.3")

    assert reporter.status().status == "ok"
