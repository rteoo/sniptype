"""Crash-recoverable voice recordings and retry metadata.

Audio is an append-only float32 journal. Metadata is replaced atomically after
each state transition, so a process crash can leave at worst an item marked as
``recording``; the next process classifies it as ``interrupted`` and keeps it
retryable. No automatic retention deletes user recordings.
"""

import array
import json
import os
import threading
import time
import uuid


STATUS_RECORDING = "recording"
STATUS_PENDING = "pending"
STATUS_TRANSCRIBED = "transcribed"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted"
STATUS_CANCELLED = "cancelled"

RETRYABLE_STATUSES = {STATUS_PENDING, STATUS_FAILED, STATUS_INTERRUPTED}
METADATA_NAME = "metadata.json"
AUDIO_NAME = "audio.f32"


def _timestamp(now=None):
    value = time.time() if now is None else now
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def _audio_bytes(values):
    if values is None:
        return b""
    if hasattr(values, "flatten"):
        values = values.flatten()
    samples = array.array("f", (float(value) for value in values))
    return samples.tobytes()


class VoiceRecording:
    """Open append-only audio journal for one capture session."""

    def __init__(self, store, record_id, handle):
        self.store = store
        self.record_id = record_id
        self._handle = handle
        self._lock = threading.Lock()
        self._closed = False
        self._bytes_written = 0

    def write_chunk(self, values):
        payload = _audio_bytes(values)
        if not payload:
            return
        with self._lock:
            if self._closed:
                return
            self._handle.write(payload)
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._bytes_written += len(payload)

    def finish_capture(self, fallback_samples=None):
        with self._lock:
            if self._closed:
                return self.record_id
            if self._bytes_written == 0 and fallback_samples:
                payload = _audio_bytes(fallback_samples)
                self._handle.write(payload)
                self._bytes_written += len(payload)
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()
            self._closed = True
        self.store.update(
            self.record_id,
            status=STATUS_PENDING,
            captured_at=_timestamp(),
            audio_bytes=self._bytes_written,
        )
        return self.record_id

    def close_as(self, status, error=None):
        with self._lock:
            if not self._closed:
                self._handle.flush()
                os.fsync(self._handle.fileno())
                self._handle.close()
                self._closed = True
        fields = {"status": status, "audio_bytes": self._bytes_written}
        if error:
            fields["error"] = str(error)
        self.store.update(self.record_id, **fields)


class VoiceHistoryStore:
    """Persistent recording index with atomic lifecycle updates."""

    def __init__(self, root_dir):
        # ceiling: history is intentionally unbounded until the product exposes
        # an explicit retention/delete policy; add one before broad voice rollout.
        self.root_dir = os.path.abspath(root_dir)
        self._lock = threading.Lock()
        os.makedirs(self.root_dir, exist_ok=True)
        self.recover_interrupted()

    def begin(self, mode, provider, profile, language, target_kind):
        record_id = time.strftime("%Y%m%d-%H%M%S", time.localtime()) + "-" + uuid.uuid4().hex[:8]
        item_dir = self._item_dir(record_id)
        os.makedirs(item_dir)
        metadata = {
            "id": record_id,
            "created_at": _timestamp(),
            "status": STATUS_RECORDING,
            "mode": mode,
            "provider": provider,
            "profile": profile,
            "language": language,
            "target_kind": target_kind,
            "sample_rate": 16000,
            "sample_format": "float32-native-endian",
            "audio_bytes": 0,
            "transcript": "",
            "outcome": None,
            "error": None,
        }
        self._write_metadata(record_id, metadata)
        handle = open(self._audio_path(record_id), "ab", buffering=0)
        return VoiceRecording(self, record_id, handle)

    def recover_interrupted(self):
        for entry in self.list_entries():
            if entry.get("status") == STATUS_RECORDING:
                self.update(
                    entry["id"],
                    status=STATUS_INTERRUPTED,
                    error="A gravação foi interrompida antes de terminar.",
                )

    def update(self, record_id, **fields):
        if not self._valid_record_id(record_id):
            return False
        with self._lock:
            metadata = self.get(record_id)
            if metadata is None:
                return False
            metadata.update(fields)
            metadata["updated_at"] = _timestamp()
            self._write_metadata(record_id, metadata)
        return True

    def mark_transcribed(self, record_id, transcript):
        return self.update(
            record_id,
            status=STATUS_TRANSCRIBED,
            transcript=transcript or "",
            error=None,
        )

    def complete(self, record_id, transcript, outcome):
        return self.update(
            record_id,
            status=STATUS_COMPLETED,
            transcript=transcript or "",
            outcome=outcome,
            error=None,
        )

    def fail(self, record_id, error):
        return self.update(record_id, status=STATUS_FAILED, error=str(error))

    def cancel(self, record_id):
        return self.update(record_id, status=STATUS_CANCELLED)

    def is_retryable(self, record_id):
        entry = self.get(record_id)
        return bool(entry and entry.get("status") in RETRYABLE_STATUSES)

    def get(self, record_id):
        if not self._valid_record_id(record_id):
            return None
        path = self._metadata_path(record_id)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, ValueError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    def list_entries(self):
        try:
            names = os.listdir(self.root_dir)
        except OSError:
            return []
        entries = []
        for name in names:
            entry = self.get(name)
            if entry is not None:
                entry = dict(entry)
                # Directory identity wins over editable metadata so recovery
                # can never be redirected outside the history root.
                entry["id"] = name
                entries.append(entry)
        return sorted(entries, key=lambda item: item.get("created_at", ""), reverse=True)

    def load_samples(self, record_id):
        try:
            with open(self._audio_path(record_id), "rb") as handle:
                payload = handle.read()
        except OSError as exc:
            raise ValueError("O áudio salvo não está disponível.") from exc
        usable = len(payload) - (len(payload) % array.array("f").itemsize)
        samples = array.array("f")
        samples.frombytes(payload[:usable])
        return samples.tolist()

    def _item_dir(self, record_id):
        if not self._valid_record_id(record_id):
            raise ValueError("Identificador de histórico inválido.")
        return os.path.join(self.root_dir, str(record_id))

    @staticmethod
    def _valid_record_id(record_id):
        if not isinstance(record_id, str) or not record_id or len(record_id) > 64:
            return False
        return all(character.isalnum() or character == "-" for character in record_id)

    def _metadata_path(self, record_id):
        return os.path.join(self._item_dir(record_id), METADATA_NAME)

    def _audio_path(self, record_id):
        return os.path.join(self._item_dir(record_id), AUDIO_NAME)

    def _write_metadata(self, record_id, metadata):
        path = self._metadata_path(record_id)
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
