import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_runtime import (
    AsrBackend,
    FakeAsrBackend,
    TranscribeCppBackend,
    VoiceRuntimeError,
    create_backend,
)


class RuntimeTests(unittest.TestCase):
    def test_base_backend_is_unavailable(self):
        backend = AsrBackend()
        self.assertFalse(backend.available())
        with self.assertRaises(VoiceRuntimeError):
            backend.load("x.gguf", "balanced", "auto")

    def test_create_backend_without_wheel_is_unavailable(self):
        real_import = __import__

        def import_without_backend(name, *args, **kwargs):
            if name == "transcribe_cpp":
                raise ImportError("simulated missing optional backend")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=import_without_backend):
            backend = create_backend()
            self.assertFalse(backend.available())

    def test_fake_backend_roundtrip(self):
        backend = FakeAsrBackend(transcript="ok")
        backend.load("model.gguf", "balanced", "pt-BR")
        self.assertTrue(backend.is_loaded())
        self.assertEqual(backend.transcribe([0.0, 0.1]), "ok")
        backend.unload()
        self.assertFalse(backend.is_loaded())

    def test_fake_cancel(self):
        backend = FakeAsrBackend()
        cancel = type("E", (), {"is_set": lambda self: True})()
        with self.assertRaises(VoiceRuntimeError):
            backend.transcribe([0.0], cancel_event=cancel)

    def test_transcribe_cpp_cancel_interrupts_an_in_flight_run(self):
        started = threading.Event()
        session = mock.Mock()

        def run(pcm, **kwargs):
            started.set()
            time.sleep(0.25)
            return "late"

        session.run.side_effect = run
        backend = TranscribeCppBackend()
        backend._session = session
        cancel = threading.Event()
        errors = []

        def worker():
            try:
                backend.transcribe([0.0], cancel_event=cancel)
            except VoiceRuntimeError as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(started.wait(1.0))
        cancel.set()
        thread.join(1.0)
        self.assertFalse(thread.is_alive())
        session.cancel.assert_called()
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
