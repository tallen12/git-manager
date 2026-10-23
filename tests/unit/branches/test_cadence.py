from datetime import UTC, datetime, timedelta

import pytest

from git_manager.branches.cadence import (
    DetectOnly,
    RunAt,
    cadence_decision,
    next_cron_window,
)
from git_manager.config.models import CadenceConfig, CadenceMode
from tests.conftest import START

# START is Monday 2026-01-05 09:00 UTC.
WEEKDAYS_AT_SIX = "0 6 * * 1-5"


def test_immediate_runs_at_the_change() -> None:
    cadence = CadenceConfig(mode=CadenceMode.IMMEDIATE)

    assert cadence_decision(cadence, base_changed_at=START) == RunAt(at=START)


def test_debounce_waits_for_the_quiet_window() -> None:
    cadence = CadenceConfig(mode=CadenceMode.DEBOUNCE, debounce=timedelta(minutes=10))

    assert cadence_decision(cadence, base_changed_at=START) == RunAt(
        at=START + timedelta(minutes=10)
    )


def test_cron_takes_the_next_window_after_the_change() -> None:
    cadence = CadenceConfig(mode=CadenceMode.CRON, cron=WEEKDAYS_AT_SIX)

    assert cadence_decision(cadence, base_changed_at=START) == RunAt(
        at=datetime(2026, 1, 6, 6, 0, tzinfo=UTC)
    )


def test_cron_skips_the_weekend() -> None:
    friday_evening = datetime(2026, 1, 9, 18, 0, tzinfo=UTC)

    assert next_cron_window(WEEKDAYS_AT_SIX, after=friday_evening) == datetime(
        2026, 1, 12, 6, 0, tzinfo=UTC
    )


def test_a_change_exactly_on_a_window_waits_for_the_next() -> None:
    six = datetime(2026, 1, 6, 6, 0, tzinfo=UTC)

    assert next_cron_window(WEEKDAYS_AT_SIX, after=six) == six + timedelta(days=1)


def test_manual_only_detects() -> None:
    cadence = CadenceConfig(mode=CadenceMode.MANUAL)

    assert cadence_decision(cadence, base_changed_at=START) == DetectOnly()


def test_cron_without_an_expression_is_rejected() -> None:
    # The config validator refuses this; model_construct skips it to reach the guard.
    cadence = CadenceConfig.model_construct(mode=CadenceMode.CRON, cron=None)

    with pytest.raises(ValueError, match=r"cadence\.cron"):
        cadence_decision(cadence, base_changed_at=START)
