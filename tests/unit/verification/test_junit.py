import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from git_manager.verification.junit import MAX_REPORT_BYTES, find_junit_xml

STEP_STARTED = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
REPORT = '<?xml version="1.0"?>\n<testsuites><testsuite name="unit" tests="1"/></testsuites>\n'


def write(path: Path, text: str, *, at: datetime) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (at.timestamp(), at.timestamp()))
    return path


def test_finds_a_report_written_during_the_step(tmp_path: Path) -> None:
    write(tmp_path / "build" / "junit.xml", REPORT, at=STEP_STARTED + timedelta(seconds=5))

    assert find_junit_xml(tmp_path, since=STEP_STARTED) == REPORT


def test_ignores_reports_from_before_the_step(tmp_path: Path) -> None:
    write(tmp_path / "junit.xml", REPORT, at=STEP_STARTED - timedelta(minutes=1))

    assert find_junit_xml(tmp_path, since=STEP_STARTED) is None


def test_ignores_xml_that_is_not_a_report_or_has_another_name(tmp_path: Path) -> None:
    later = STEP_STARTED + timedelta(seconds=1)
    write(tmp_path / "junit-config.xml", "<config/>", at=later)
    write(tmp_path / "pom.xml", REPORT, at=later)

    assert find_junit_xml(tmp_path, since=STEP_STARTED) is None


def test_skips_dependency_and_git_directories(tmp_path: Path) -> None:
    later = STEP_STARTED + timedelta(seconds=1)
    write(tmp_path / "node_modules" / "lib" / "junit.xml", REPORT, at=later)
    write(tmp_path / ".git" / "junit.xml", REPORT, at=later)

    assert find_junit_xml(tmp_path, since=STEP_STARTED) is None


def test_the_newest_report_wins_and_surefire_names_match(tmp_path: Path) -> None:
    newer = REPORT.replace("unit", "surefire")
    write(tmp_path / "junit.xml", REPORT, at=STEP_STARTED + timedelta(seconds=1))
    write(tmp_path / "target" / "TEST-App.xml", newer, at=STEP_STARTED + timedelta(seconds=2))

    assert find_junit_xml(tmp_path, since=STEP_STARTED) == newer


def test_oversized_reports_are_left_out(tmp_path: Path) -> None:
    padding = " " * MAX_REPORT_BYTES
    write(tmp_path / "junit.xml", REPORT + padding, at=STEP_STARTED + timedelta(seconds=1))

    assert find_junit_xml(tmp_path, since=STEP_STARTED) is None
