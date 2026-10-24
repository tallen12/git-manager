from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cyclopts import App
from pydantic import JsonValue

from git_manager.branches import BranchState
from git_manager.branches.models import Reason
from git_manager.cli.events import NO_DESKTOP_NOTIFIER, WATCH_NEEDS_API, event_line
from git_manager.cli.main import build_app
from git_manager.cli.output import EXIT_FAILED
from git_manager.config.models import RepoConfig
from git_manager.config.protocols import ConfigPath
from git_manager.core import HttpTarget, LocalTarget, Operations, Service, SocketTarget
from git_manager.events import Event, EventKind, Notifier
from tests.conftest import TEST_VERSION, RecordingNotifier, make_branch, run_cli
from tests.unit.cli.conftest import (
    FakeBranchOperations,
    FakeRunOperations,
    UnavailableHealth,
    no_runtime,
    read_config,
)

AT = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
CONFIG = RepoConfig.model_validate(
    {
        "repo": {"url": "git@example.test:repo.git"},
        "defaults": {"notify": {"on": ["pushed"]}},
        "branches": [{"name": "feature/two", "base": "main", "notify": {"on": ["needs_human"]}}],
    }
)


def event(event_id: int, branch_id: str, kind: EventKind, **fields: object) -> Event:
    values: dict[str, object] = {"id": event_id, "at": AT, "kind": kind, "branch_id": branch_id}
    return Event.model_validate(values | fields)


EVENTS = (
    # branch-1 (feature/one) uses defaults: notify on pushed only.
    event(1, "branch-1", EventKind.PUSHED, run_id="run-1"),
    event(
        2,
        "branch-1",
        EventKind.STATE_CHANGED,
        state=BranchState.NEEDS_HUMAN,
        reason=Reason.CONFLICT,
    ),
    # branch-2 (feature/two) has its own notify.on: needs_human only.
    event(3, "branch-2", EventKind.PUSHED),
    event(4, "branch-2", EventKind.STATE_CHANGED, state=BranchState.NEEDS_HUMAN),
    # Tracked after watch began: unknown id, defaults apply.
    event(5, "branch-9", EventKind.PUSHED),
)


@dataclass(frozen=True, slots=True)
class StaticConfig:
    """``ConfigOperations`` serving one config."""

    config: RepoConfig

    async def show(self) -> RepoConfig:
        return self.config

    async def set(self, path: ConfigPath, value: JsonValue) -> RepoConfig:
        raise AssertionError(path, value)


@dataclass(slots=True)
class ScriptedEvents:
    """``EventOperations`` yielding fixed events, then ending as a stopping daemon does."""

    events: Sequence[Event]
    afters: list[int | None]

    async def stream(self, *, after: int | None = None) -> AsyncGenerator[Event]:
        self.afters.append(after)
        for item in self.events:
            if after is None or item.id > after:
                yield item


@dataclass(slots=True)
class Harness:
    app: App
    events: ScriptedEvents
    notifier: RecordingNotifier


def harness(*, desktop: bool = True) -> Harness:
    branches = FakeBranchOperations(
        branches={
            "feature/one": make_branch(id="branch-1", name="feature/one"),
            "feature/two": make_branch(id="branch-2", name="feature/two"),
        }
    )
    scripted = ScriptedEvents(events=EVENTS, afters=[])
    service = Service(
        health=UnavailableHealth("not built in this test"),
        config=StaticConfig(CONFIG),
        branches=branches,
        runs=FakeRunOperations(),
        events=scripted,
    )

    @asynccontextmanager
    async def connect(
        target: LocalTarget | HttpTarget | SocketTarget,
    ) -> AsyncGenerator[Operations]:
        assert not isinstance(target, LocalTarget)
        yield service

    recording = RecordingNotifier()

    def notifier() -> Notifier | None:
        return recording if desktop else None

    app = build_app(
        connect=connect,
        open_runtime=no_runtime,
        read_config=read_config,
        version=TEST_VERSION,
        notifier=notifier,
    )
    return Harness(app=app, events=scripted, notifier=recording)


def test_event_line_names_the_branch_and_what_happened() -> None:
    line = event_line(EVENTS[1], branch="feature/one")

    assert (
        line == "2  2026-01-05T09:00:00+00:00  feature/one  state_changed  needs_human  (conflict)"
    )


def test_watch_prints_every_event_by_branch_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built = harness()

    assert run_cli(built.app, ["watch", "--socket", str(tmp_path / "api.sock")]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert [line.split("  ")[2] for line in lines] == [
        "feature/one",
        "feature/one",
        "feature/two",
        "feature/two",
        "branch-9",
    ]
    assert lines[0].endswith("pushed  run run-1")
    assert built.notifier.shown == []


def test_watch_notify_follows_each_branch_notify_on(tmp_path: Path) -> None:
    built = harness()

    status = run_cli(built.app, ["watch", "--notify", "--socket", str(tmp_path / "api.sock")])

    assert status == 0
    assert [shown.message for shown in built.notifier.shown] == [
        "branch feature/one: pushed",
        "branch feature/two: needs_human",
        "branch branch-9: pushed",
    ]


def test_watch_after_replays_from_that_id(tmp_path: Path) -> None:
    built = harness()

    assert run_cli(built.app, ["watch", "--after", "3", "--socket", str(tmp_path / "s")]) == 0

    assert built.events.afters == [3]


def test_a_failed_notification_is_reported_and_the_watch_goes_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built = harness()
    built.notifier.failing = True

    assert run_cli(built.app, ["watch", "--notify", "--socket", str(tmp_path / "s")]) == 0

    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == len(EVENTS)
    assert captured.err.count("warning: notification not shown: no notification daemon") == 3


def test_watch_refuses_local_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("repo:\n  url: u\n", encoding="utf-8")

    assert run_cli(harness().app, ["watch", "--config", str(config)]) == EXIT_FAILED
    assert capsys.readouterr().err == f"error: {WATCH_NEEDS_API}\n"


def test_watch_notify_needs_a_desktop_notifier(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built = harness(desktop=False)

    status = run_cli(built.app, ["watch", "--notify", "--socket", str(tmp_path / "s")])

    assert status == EXIT_FAILED
    assert capsys.readouterr().err == f"error: {NO_DESKTOP_NOTIFIER}\n"
    assert built.events.afters == []
