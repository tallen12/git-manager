"""When a detected base change is acted on: a pure policy over ``cadence`` config."""

from dataclasses import dataclass
from datetime import datetime
from typing import assert_never

from croniter import croniter

from git_manager.config.models import CadenceConfig, CadenceMode


@dataclass(frozen=True, slots=True)
class RunAt:
    """Schedule a run once the clock reaches ``at``."""

    at: datetime


@dataclass(frozen=True, slots=True)
class DetectOnly:
    """``manual`` cadence: report the change, never schedule a run."""


type CadenceDecision = RunAt | DetectOnly


def next_cron_window(expression: str, *, after: datetime) -> datetime:
    """The first time ``expression`` fires strictly after ``after``, in ``after``'s zone (UTC)."""
    window: object = croniter(expression, after).get_next(datetime)
    if not isinstance(window, datetime):
        msg = f"croniter returned {window!r} for {expression!r}"
        raise TypeError(msg)
    return window


def cadence_decision(cadence: CadenceConfig, *, base_changed_at: datetime) -> CadenceDecision:
    """When to run for a base that last moved at ``base_changed_at``.

    ``debounce`` waits for the base to stay quiet for the window, so every further move
    (a new ``base_changed_at``) pushes the run back. ``cron`` takes the next window after
    the latest move.
    """
    match cadence.mode:
        case CadenceMode.IMMEDIATE:
            return RunAt(at=base_changed_at)
        case CadenceMode.DEBOUNCE:
            return RunAt(at=base_changed_at + cadence.debounce)
        case CadenceMode.CRON:
            if cadence.cron is None:
                msg = "cadence.cron is required when cadence.mode is cron"
                raise ValueError(msg)
            return RunAt(at=next_cron_window(cadence.cron, after=base_changed_at))
        case CadenceMode.MANUAL:
            return DetectOnly()
        case _:
            assert_never(cadence.mode)
