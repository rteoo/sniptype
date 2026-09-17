"""In-memory workflow identity and successful-expansion history."""

from collections import deque
from dataclasses import dataclass
import threading


SNIPPET_KINDS = frozenset({"static", "mapping", "dynamic"})


@dataclass(frozen=True)
class SnippetRef:
    """Stable identity for a manager item without carrying snippet content."""

    kind: str
    key: str
    container: str | None = None

    def __post_init__(self):
        if self.kind not in SNIPPET_KINDS:
            raise ValueError(f"unsupported snippet kind: {self.kind!r}")
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("snippet key must be non-empty text")
        if self.kind == "mapping":
            if not isinstance(self.container, str) or not self.container:
                raise ValueError("mapping references require a container key")
        elif self.container is not None:
            raise ValueError("only mapping references may have a container")


class WorkflowState:
    """Thread-safe, session-only last-successful and recent item state."""

    def __init__(self, recent_limit=20):
        if not isinstance(recent_limit, int) or isinstance(recent_limit, bool) or recent_limit <= 0:
            raise ValueError("recent_limit must be a positive integer")
        self._lock = threading.Lock()
        self._recent = deque(maxlen=recent_limit)
        self._last = None

    def record_success(self, item):
        """Record one completed insertion, moving repeated items to newest."""
        if not isinstance(item, SnippetRef):
            raise TypeError("item must be a SnippetRef")
        with self._lock:
            self._last = item
            try:
                self._recent.remove(item)
            except ValueError:
                pass
            self._recent.appendleft(item)

    @property
    def last_successful_item(self):
        with self._lock:
            return self._last

    def recent_items(self):
        with self._lock:
            return tuple(self._recent)


__all__ = ["SNIPPET_KINDS", "SnippetRef", "WorkflowState"]
