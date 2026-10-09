"""Harness-neutral contracts for the desktop companion perception boundary."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
import threading


@dataclass(frozen=True)
class ObservationBundle:
    """One bounded observation; content is data and never an authorization source."""
    observed_at: datetime
    source: str
    target: str
    valid: bool
    text: str = ""
    image: Mapping[str, Any] | None = None
    media_time_seconds: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include timezone")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source required")
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("target required")
        if type(self.valid) is not bool:
            raise ValueError("valid must be boolean")
        if not isinstance(self.text, str):
            raise ValueError("text must be text")
        if self.media_time_seconds is not None and (type(self.media_time_seconds) not in (int, float) or self.media_time_seconds < 0):
            raise ValueError("media time must be non-negative")

    @classmethod
    def now(cls, *, source, target, valid, text="", image=None, media_time_seconds=None, metadata=None):
        return cls(datetime.now(timezone.utc), source, target, valid, text, image, media_time_seconds, metadata or {})


class PerceptionService:
    """Lifecycle contract; platform capture is injected by the Windows adapter."""
    def __init__(self, collector):
        if not callable(collector):
            raise ValueError("collector must be callable")
        self._collector = collector
        self._target = None
        self._state = "stopped"
        self._epoch = 0
        self._lock = threading.RLock()

    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def target(self):
        with self._lock:
            return self._target

    def select_target(self, target):
        if not isinstance(target, str) or not target.strip():
            raise ValueError("target required")
        with self._lock:
            if self._state == "running":
                raise RuntimeError("pause before changing target")
            self._target = target.strip()
            self._epoch += 1
            return {"status": "selected", "target": self._target}

    def start(self):
        with self._lock:
            if not self._target:
                raise RuntimeError("select a target before starting perception")
            if self._state != "running":
                start = getattr(self._collector, 'start', None)
                if callable(start):
                    start()
                self._epoch += 1
                self._state = "running"
            return {"status": "running", "target": self._target}

    def pause(self):
        with self._lock:
            self._epoch += 1
            if self._state == "running":
                self._state = "paused"
            result = {"status": self._state, "target": self._target}
        self._release_collector()
        return result

    def stop(self):
        with self._lock:
            self._epoch += 1
            self._state = "stopped"
            result = {"status": "stopped", "target": self._target}
        self._release_collector()
        return result

    def _release_collector(self):
        stop = getattr(self._collector, 'stop', None)
        if callable(stop):
            stop()

    def observe(self):
        with self._lock:
            if self._state != "running":
                raise RuntimeError("perception is not running")
            target, epoch = self._target, self._epoch
        result = self._collector(target)
        if not isinstance(result, ObservationBundle):
            raise TypeError("collector must return ObservationBundle")
        with self._lock:
            if self._state != 'running' or epoch != self._epoch:
                raise RuntimeError('capture was paused, stopped or superseded')
            if result.target != target:
                raise RuntimeError('collector returned a different target')
        return result
