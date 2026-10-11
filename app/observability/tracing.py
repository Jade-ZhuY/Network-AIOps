import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class RequestTrace:
    """Request-local trace; no payloads, credentials, disk logs or persistent store."""

    trace_id: str
    events: list[dict] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)

    @contextmanager
    def span(self, name: str):
        start = time.perf_counter()
        event = {"name": name, "status": "ok"}
        try:
            yield event
        except BaseException as exc:
            event.update(status="error", error_type=type(exc).__name__)
            raise
        finally:
            event["duration_ms"] = round((time.perf_counter() - start) * 1000, 3)
            with self.lock:
                self.events.append(event)
