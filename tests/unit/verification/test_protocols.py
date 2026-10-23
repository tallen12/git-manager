from datetime import UTC, datetime
from pathlib import Path

import pytest

from git_manager.config import VerifyConfig
from git_manager.config.models import DockerConfig
from git_manager.verification import (
    CommandSource,
    DockerCleaner,
    DockerCleanupError,
    Verifier,
    VerifyCommands,
    VerifyFailed,
    VerifyPassed,
    VerifyStep,
)
from tests.conftest import FakeVerifier
from tests.unit.verification.conftest import RecordingDockerCleaner

COMMANDS = VerifyCommands(test="just test", source=CommandSource.CONFIG, source_hash="h")


async def test_fake_verifier_passes_by_default_and_records_calls() -> None:
    fake = FakeVerifier()
    verifier: Verifier = fake

    outcome = await verifier.verify(
        worktree=Path("w"), commands=COMMANDS, config=VerifyConfig(), run_id="run-1"
    )

    assert isinstance(outcome, VerifyPassed)
    assert [call.run_id for call in fake.calls] == ["run-1"]


async def test_fake_verifier_replays_scripted_outcomes() -> None:
    failed = VerifyFailed(results=(), failed_step=VerifyStep.TEST)
    verifier: Verifier = FakeVerifier(outcomes=[failed])

    outcome = await verifier.verify(
        worktree=Path("w"), commands=COMMANDS, config=VerifyConfig(), run_id="run-1"
    )

    assert outcome == failed


async def test_recording_cleaner_records_calls_and_can_fail() -> None:
    fake = RecordingDockerCleaner(error="daemon down")
    cleaner: DockerCleaner = fake
    started = datetime(2026, 1, 5, tzinfo=UTC)

    with pytest.raises(DockerCleanupError, match="daemon down"):
        await cleaner.clean_up(run_id="run-1", docker=DockerConfig(), run_started=started)

    assert [call.run_id for call in fake.calls] == ["run-1"]
