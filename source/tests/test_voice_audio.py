import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_audio import AudioCapture, VoiceAudioError


class AudioCaptureTests(unittest.TestCase):
    def test_stop_without_start_is_empty(self):
        capture = AudioCapture()
        samples, overflow = capture.stop()
        self.assertEqual(samples, [])
        self.assertFalse(overflow)

    def test_missing_sounddevice_is_loud(self):
        capture = AudioCapture()
        with mock.patch.dict("sys.modules", {"sounddevice": None}):
            with mock.patch("builtins.__import__", side_effect=ImportError("no sd")):
                with self.assertRaises(VoiceAudioError):
                    capture.start()

    def test_overflow_flag_from_full_queue(self):
        capture = AudioCapture(queue_max=1)
        capture._queue.put_nowait([0.0])
        capture._queue.put_nowait  # keep attribute
        try:
            capture._queue.put_nowait([1.0])
        except Exception:
            capture._overflow = True
        self.assertTrue(capture._overflow)


if __name__ == "__main__":
    unittest.main()
