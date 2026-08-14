import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from trigger_index import compile_trigger_index
from voice_audio import VoiceAudioError
from voice_dispatch import MODE_COMMAND, MODE_DICTATION, OUTCOME_INSERTED, VoiceTarget
from voice_runtime import FakeAsrBackend
from voice_support import STATE_IDLE, STATE_RECORDING, STATE_UNAVAILABLE, VoiceController


class InlineRunner:
    def start(self, fn, *args, name=None):
        fn(*args)


class FakeCapture:
    def __init__(self, samples=None, overflow=False, error=None):
        self.samples = list(samples or [0.1, 0.2])
        self.overflow = overflow
        self.error = error
        self.started = False
        self._queue = _Queue(self.samples)

    def start(self):
        if self.error:
            raise self.error
        self.started = True

    def stop(self):
        return self.samples, self.overflow


class _Queue:
    def __init__(self, items):
        self.items = list(items)

    def get(self, timeout=0.1):
        if not self.items:
            raise Exception("empty")
        return self.items.pop(0)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inserted = []
        self.expanded = []
        self.notify = mock.Mock()
        self.logger = mock.Mock()
        self.backend = FakeAsrBackend(transcript="hello world")
        self.capture = FakeCapture()
        self.controller = VoiceController(
            {"voice_enabled": False},
            task_runner=InlineRunner(),
            insert_text=lambda text: self.inserted.append(text) or True,
            expand_trigger=lambda trigger: self.expanded.append(trigger) or True,
            notify=self.notify,
            logger=self.logger,
            capture_target=lambda: VoiceTarget("window", handle=1),
            restore_target=lambda target: True,
            secure_input_blocks=lambda: False,
            backend=self.backend,
            capture_factory=lambda: self.capture,
            cache_dir=self.tmp,
            download=lambda entry, cache_dir, progress=None, cancel_event=None: os.path.join(
                self.tmp, "model.gguf"
            ),
        )
        self.controller.bind_library(
            lambda: {"xadds": "hi"},
            lambda: compile_trigger_index({"xadds": "hi"}, set()),
        )

    def _ready(self):
        with mock.patch("voice_support.model_is_installed", return_value=True), \
                mock.patch("voice_support.installed_model_path", return_value="model.gguf"), \
                mock.patch.object(self.controller, "_start_monitor"):
            self.controller.enable()
        self.assertEqual(self.controller.state, STATE_IDLE)

    def test_defaults_off(self):
        self.assertFalse(self.controller.enabled)
        self.assertEqual(self.controller.state, STATE_UNAVAILABLE)

    def test_hotkey_while_loading_is_ignored(self):
        self.controller._state = "loading"
        self.assertFalse(self.controller.handle_hotkey_press(MODE_DICTATION))

    def test_dictation_inserts_literally(self):
        self._ready()
        self.backend.transcript = "xadds"
        self.assertTrue(self.controller.handle_hotkey_press(MODE_DICTATION))
        self.controller.handle_hotkey_release(MODE_DICTATION)
        self.assertEqual(self.inserted, ["xadds"])
        self.assertEqual(self.expanded, [])
        self.assertEqual(self.controller.last_outcome, OUTCOME_INSERTED)

    def test_voice_command_expands(self):
        self._ready()
        self.backend.transcript = "xadds"
        self.controller.handle_hotkey_press(MODE_COMMAND)
        self.controller.handle_hotkey_release(MODE_COMMAND)
        self.assertEqual(self.expanded, ["xadds"])

    def test_form_target_does_not_paste(self):
        self._ready()
        seen = []
        self.controller.register_form_target(lambda text: seen.append(text))
        self.backend.transcript = "João"
        self.controller.handle_hotkey_press(MODE_DICTATION)
        self.controller.handle_hotkey_release(MODE_DICTATION)
        self.assertEqual(seen, ["João"])
        self.assertEqual(self.inserted, [])

    def test_second_press_ignored(self):
        self._ready()
        self.assertTrue(self.controller.handle_hotkey_press(MODE_DICTATION))
        self.assertFalse(self.controller.handle_hotkey_press(MODE_DICTATION))

    def test_overflow_does_not_insert(self):
        self.capture.overflow = True
        self._ready()
        self.controller.handle_hotkey_press(MODE_DICTATION)
        self.controller.handle_hotkey_release(MODE_DICTATION)
        self.assertEqual(self.inserted, [])

    def test_audio_error_stays_idle(self):
        self.capture.error = VoiceAudioError("recusado")
        self._ready()
        self.assertFalse(self.controller.handle_hotkey_press(MODE_DICTATION))
        self.assertEqual(self.controller.state, STATE_IDLE)

    def test_shutdown_blocks_later_press(self):
        self._ready()
        self.controller.shutdown()
        self.assertFalse(self.controller.handle_hotkey_press(MODE_DICTATION))

    def test_failed_switch_restores_previous_when_possible(self):
        self._ready()
        self.backend.load = mock.Mock(side_effect=Exception("boom"))
        with mock.patch("voice_support.installed_model_path", return_value="old.gguf"):
            # first load after failure uses previous profile
            original_load = FakeAsrBackend.load
            self.backend.load = mock.Mock(side_effect=[Exception("boom"), None])
            self.controller.set_profile("accuracy")
        self.assertEqual(self.controller.settings.profile, "balanced")

    def test_delete_disables(self):
        self._ready()
        with mock.patch("voice_support.delete_model"):
            self.controller.delete_active_model()
        self.assertFalse(self.controller.enabled)

    def test_reapplying_same_options_retries_an_unavailable_backend(self):
        self._ready()
        self.controller.disable()
        self.controller.settings.enabled = True
        with mock.patch("voice_support.model_is_installed", return_value=True), \
                mock.patch("voice_support.installed_model_path", return_value="model.gguf"), \
                mock.patch.object(self.controller, "_start_monitor"):
            self.controller.apply_options(profile="balanced")
        self.assertEqual(self.controller.state, STATE_IDLE)

    def test_language_change_reloads_the_idle_backend(self):
        self._ready()
        with mock.patch("voice_support.model_is_installed", return_value=True), \
                mock.patch("voice_support.installed_model_path", return_value="model.gguf"), \
                mock.patch.object(self.controller, "_start_monitor"):
            self.controller.set_language("en-US")
        self.assertEqual(self.backend.language, "en-US")
        self.assertEqual(self.controller.state, STATE_IDLE)

    def test_denied_microphone_does_not_open_capture(self):
        self._ready()
        self.controller._microphone_status = lambda: "denied"
        self.assertFalse(self.controller.handle_hotkey_press(MODE_DICTATION))
        self.assertEqual(self.controller.state, STATE_IDLE)
        self.assertFalse(self.capture.started)

    def test_download_progress_reaches_the_tray_label(self):
        seen = []
        self.controller._on_status_change = lambda: seen.append(self.controller.status_label())

        def fake_download(entry, cache_dir, progress=None, cancel_event=None):
            if progress is not None:
                progress(50, 100)
            return os.path.join(self.tmp, "model.gguf")

        self.controller._download = fake_download
        with mock.patch("voice_support.model_is_installed", return_value=False), \
                mock.patch.object(self.controller, "_start_monitor"):
            self.controller.enable()
        self.assertTrue(any("baixando" in label for label in seen))

    def test_enable_after_disable_returns_to_idle(self):
        self._ready()
        self.controller.disable()
        self.assertEqual(self.controller.state, STATE_UNAVAILABLE)
        self._ready()
        self.assertEqual(self.controller.state, STATE_IDLE)
        self.assertTrue(self.controller.handle_hotkey_press(MODE_DICTATION))
        self.assertEqual(self.controller.state, STATE_RECORDING)


if __name__ == "__main__":
    unittest.main()
