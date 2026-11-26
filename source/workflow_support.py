"""Workflow identity, session history and local static usage timestamps."""

from collections import deque
from dataclasses import dataclass
import hashlib
import threading
import time

from snippet_utils import load_json_file, write_json_atomic


SNIPPET_KINDS = frozenset({"static", "mapping", "dynamic"})


def unix_milliseconds():
    return time.time_ns() // 1_000_000


def valid_timestamp(value):
    return type(value) is int and 0 < value <= 8_640_000_000_000_000


def static_usage_id(key, item=None):
    """Use the persisted identity, or a stable hash for a pre-existing snippet."""
    identity = (item or {}).get("usage_id")
    if isinstance(identity, str) and identity:
        return identity
    return hashlib.sha256(key.encode("utf-8", errors="surrogatepass")).hexdigest()


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

    def __init__(self, recent_limit=20, *, usage_file=None, logger=None):
        if not isinstance(recent_limit, int) or isinstance(recent_limit, bool) or recent_limit <= 0:
            raise ValueError("recent_limit must be a positive integer")
        self._lock = threading.Lock()
        self._recent = deque(maxlen=recent_limit)
        self._last = None
        self._usage_file = usage_file
        self._logger = logger
        self._usage_lock = threading.Lock()
        self._usage_dirty = False
        self._static_usage = self._load_usage()

    def _load_usage(self):
        if self._usage_file is None:
            return {}
        try:
            records = load_json_file(self._usage_file)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            if self._logger is not None:
                self._logger.warning("Could not read local snippet usage history.")
            return {}
        if not isinstance(records, dict):
            return {}
        return {key: value for key, value in records.items() if valid_timestamp(value)}

    def record_success(self, item, *, usage_id=None):
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
            if item.kind == "static":
                key = usage_id or static_usage_id(item.key)
                self._static_usage[key] = unix_milliseconds()
                self._usage_dirty = True

    def static_usage(self):
        with self._lock:
            return self._static_usage.copy()

    def flush_static_usage(self):
        """Persist on an expansion worker, after its keyboard work has finished."""
        if self._usage_file is None:
            return
        # A concurrent completion can update memory during the atomic write.
        # Serialize writes so that an older snapshot cannot replace a newer one.
        with self._usage_lock:
            with self._lock:
                if not self._usage_dirty:
                    return
                snapshot = self._static_usage.copy()
                self._usage_dirty = False
            try:
                # ceiling: rewrite the local date map per successful static
                # expansion; batch writes if large-library profiling warrants it.
                write_json_atomic(self._usage_file, snapshot)
            except OSError:
                with self._lock:
                    self._usage_dirty = True
                if self._logger is not None:
                    self._logger.warning("Could not save local snippet usage history.")

    @property
    def last_successful_item(self):
        with self._lock:
            return self._last

    def recent_items(self):
        with self._lock:
            return tuple(self._recent)


__all__ = ["SNIPPET_KINDS", "SnippetRef", "WorkflowState"]
