"""Event bus errors."""


class SubscriberLaggedError(Exception):
    """A subscriber fell so far behind that its queue filled, so the bus dropped it.

    Events after ``last_id`` were not delivered; the subscriber catches up from the event
    log (``EventRepository.list(after=last_id)``) and subscribes again.
    """

    def __init__(self, *, last_id: int) -> None:
        super().__init__(f"subscriber fell behind after event {last_id}")
        self.last_id = last_id


class NotificationError(Exception):
    """A notifier could not show a notification (missing program, failure or timeout)."""
