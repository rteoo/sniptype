import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_audio import AudioCapture, BLOCK_SIZE, VoiceAudioError


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

    def test_two_second_capture_does_not_exhaust_the_default_queue(self):
        stream = mock.Mock()
        options = {}

        def input_stream(**kwargs):
            options.update(kwargs)
            return stream

        sounddevice = mock.Mock(InputStream=mock.Mock(side_effect=input_stream))
        capture = AudioCapture()
        with mock.patch.dict("sys.modules", {"sounddevice": sounddevice}):
            capture.start()
            for _ in range(32):
                options["callback"]([0.0] * BLOCK_SIZE, BLOCK_SIZE, None, None)
            samples, overflow = capture.stop()

        self.assertEqual(options["blocksize"], BLOCK_SIZE)
        self.assertEqual(len(samples), 32 * BLOCK_SIZE)
        self.assertFalse(overflow)

    def test_sample_ceiling_cancels_even_when_the_queue_has_room(self):
        stream = mock.Mock()
        options = {}

        def input_stream(**kwargs):
            options.update(kwargs)
            return stream

        sounddevice = mock.Mock(InputStream=mock.Mock(side_effect=input_stream))
        capture = AudioCapture(max_samples=BLOCK_SIZE * 2, queue_max=10)
        with mock.patch.dict("sys.modules", {"sounddevice": sounddevice}):
            capture.start()
            for _ in range(3):
                options["callback"]([0.0] * BLOCK_SIZE, BLOCK_SIZE, None, None)
            samples, overflow = capture.stop()

        self.assertEqual(samples, [])
        self.assertTrue(overflow)

    def test_capture_journals_each_audio_chunk_before_stop(self):
        stream = mock.Mock()
        options = {}
        journal = mock.Mock()

        def input_stream(**kwargs):
            options.update(kwargs)
            return stream

        sounddevice = mock.Mock(InputStream=mock.Mock(side_effect=input_stream))
        capture = AudioCapture()
        capture.set_journal(journal)
        with mock.patch.dict("sys.modules", {"sounddevice": sounddevice}):
            capture.start()
            options["callback"]([0.25] * BLOCK_SIZE, BLOCK_SIZE, None, None)
            samples, overflow = capture.stop()

        journal.write_chunk.assert_called_once()
        self.assertEqual(len(samples), BLOCK_SIZE)
        self.assertFalse(overflow)


if __name__ == "__main__":
    unittest.main()
