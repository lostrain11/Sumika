from __future__ import annotations

import threading
from collections.abc import Callable
import logging

from .protocol.models import EventEnvelope
from .storage import Storage


EventSink = Callable[[dict], None]


class EventBus:
    """In-process event fan-out with durable event history."""

    def __init__(self, storage: Storage, logger: logging.Logger | None = None) -> None:
        self.storage = storage
        self.logger = logger
        self._sinks: set[EventSink] = set()
        self._lock = threading.RLock()

    def subscribe(self, sink: EventSink) -> Callable[[], None]:
        with self._lock:
            self._sinks.add(sink)

        def unsubscribe() -> None:
            with self._lock:
                self._sinks.discard(sink)

        return unsubscribe

    def publish(self, event: EventEnvelope) -> dict:
        payload = event.to_dict()
        self.storage.append_event(payload)
        if self.logger:
            self.logger.info(
                "event published type=%s session=%s character=%s",
                event.event_type,
                event.session_id or "-",
                event.character_id or "-",
            )
        with self._lock:
            sinks = list(self._sinks)
        stale: list[EventSink] = []
        for sink in sinks:
            try:
                sink(payload)
            except Exception as error:
                if self.logger:
                    self.logger.warning("event sink removed type=%s error=%s", event.event_type, type(error).__name__)
                stale.append(sink)
        if stale:
            with self._lock:
                for sink in stale:
                    self._sinks.discard(sink)
        return payload
