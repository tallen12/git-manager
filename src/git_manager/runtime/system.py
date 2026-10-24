"""The real clock and id generator, for composition roots."""

import uuid
from datetime import UTC, datetime

# 16 hex digits (64 random bits): short enough to type in ``git-manager show RUN``.
_ID_LENGTH = 16


class SystemClock:
    """``Clock`` reading the system time in UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class RandomIds:
    """``IdGenerator`` of random hex ids."""

    def new_id(self) -> str:
        return uuid.uuid4().hex[:_ID_LENGTH]
