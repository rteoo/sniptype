import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_runtime import AsrBackend, FakeAsrBackend, VoiceRuntimeError, create_backend


class RuntimeTests(unittest.TestCase):
    def test_base_backend_is_unavailable(self):
        backend = AsrBackend()
        self.assertFalse(backend.available())
        with self.assertRaises(VoiceRuntimeError):
            backend.load("x.gguf", "balanced", "auto")

    def test_create_backend_without_wheel_is_unavailable(self):
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


if __name__ == "__main__":
    unittest.main()
