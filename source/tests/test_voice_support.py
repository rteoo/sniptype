import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from trigger_index import compile_trigger_index
from voice_audio import CaptureIssue, CaptureResult, VoiceAudioError
from voice_dispatch import (
    MODE_COMMAND,
    MODE_DICTATION,
    OUTCOME_FAILED,
    OUTCOME_INSERTED,
    OUTCOME_SECURE_INPUT,
    OUTCOME_TARGET_LOST,
    VoiceTarget,
)
from voice_runtime import FakeAsrBackend, VoiceRuntimeError
from voice_support import (
    STATE_IDLE,
    STATE_LOADING,
    STATE_RECORDING,
    STATE_ROUTING,
    STATE_TRANSCRIBING,
    STATE_UNAVAILABLE,
    VoiceController,
)


class InlineRunner:
    def start(self, fn, *args, name=None):
        fn(*args)


class FakeCapture:
    def __init__(self, samples=None, overflow=False, error=None):
        self.samples = list(samples or [0.1, 0.2])
        self.overflow = overflow
        self.error = error
        self.started = False
        self.stop_calls = 0
        self.issue = None
        self._queue = _Queue(self.samples)

    def start(self):
        if self.error:
            raise self.error
        self.started = True

    def stop(self):
        self.stop_calls += 1
        self.started = False
        issue = self.issue
        if issue is None and self.overflow:
            issue = CaptureIssue.DURATION_LIMIT
        return CaptureResult(
            self.samples,
            issue=issue,
            message=("capture failed" if issue is not None else None),
            duration_seconds=len(self.samples) / 16000,
        )

    def read_chunk(self, timeout=0.1):
        return self._queue.get(timeout=timeout)


class _Queue:
    def __init__(self, items):
        self.items = list(items)

    def get(self, timeout=0.1):
        if not self.items:
            raise Exception("empty")
        return self.items.pop(0)


class _ChunkCapture:
    def __init__(self, chunks):
        self._chunks = _Queue(chunks)

    def read_chunk(self, timeout=0):
        return self._chunks.get(timeout=timeout)


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
        entry = self.controller.history_entries()[0]
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(entry["transcript"], "xadds")
        self.assertEqual(entry["provider"], "local")

    def test_failed_transcription_stays_retryable_in_history(self):
        self._ready()
        self.backend.transcribe = mock.Mock(side_effect=VoiceRuntimeError("falhou"))

        self.controller.handle_hotkey_press(MODE_DICTATION)
        self.controller.handle_hotkey_release(MODE_DICTATION)

        entry = self.controller.history_entries()[0]
        self.assertEqual(entry["status"], "failed")
        self.assertTrue(self.controller._history.is_retryable(entry["id"]))

    def test_history_retry_copies_recovered_text_without_pasting(self):
        self._ready()
        recording = self.controller._history.begin(
            mode=MODE_DICTATION,
            provider="local",
            profile="balanced",
            language="pt-BR",
            target_kind="window",
        )
        recording.finish_capture([0.1, 0.2])
        self.controller._history.fail(recording.record_id, "offline")
        self.controller.settings.voice_replacements = {"Queen": "Qwen"}
        self.backend.transcript = "texto Queen recuperado"

        with mock.patch("voice_support.Clipboard.set_content", return_value=True) as copied:
            self.assertTrue(self.controller.retry_history(recording.record_id))

        self.assertEqual(self.inserted, [])
        copied.assert_called_once_with("texto Qwen recuperado")
        entry = self.controller.history_entry(recording.record_id)
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(entry["outcome"], "recovered")
        self.assertEqual(entry["raw_transcript"], "texto Queen recuperado")

    def test_cancelled_history_retry_is_not_mislabeled_as_failed(self):
        self._ready()
        recording = self.controller._history.begin(
            mode=MODE_DICTATION,
            provider="local",
            profile="balanced",
            language="pt-BR",
            target_kind="window",
        )
        recording.finish_capture([0.1])
        self.controller._history.fail(recording.record_id, "offline")
        self.controller._cancel.set()

        self.controller._retry_history_worker(
            self.controller._session_generation,
            recording.record_id,
        )

        entry = self.controller.history_entry(recording.record_id)
        self.assertEqual(entry["status"], "cancelled")

    def test_clipboard_exception_reports_that_dictation_was_not_recovered(self):
        self._ready()
        self.controller._insert_text = lambda text: False
        with mock.patch("voice_support.Clipboard.set_content", side_effect=OSError("busy")):
            self.controller.handle_hotkey_press(MODE_DICTATION)
            self.controller.handle_hotkey_release(MODE_DICTATION)

        self.assertEqual(self.controller.last_outcome, OUTCOME_FAILED)
        self.notify.assert_called_with(
            "Não foi possível inserir o texto de voz nem copiá-lo "
            "para a área de transferência.",
            key="voice-insert",
        )
        self.logger.warning.assert_called_once()

    def test_failed_insertion_reports_successful_clipboard_recovery(self):
        self._ready()
        self.controller._insert_text = lambda text: False
        with mock.patch("voice_support.Clipboard.set_content", return_value=True):
            self.controller.handle_hotkey_press(MODE_DICTATION)
            self.controller.handle_hotkey_release(MODE_DICTATION)

        self.assertEqual(self.controller.last_outcome, OUTCOME_FAILED)
        self.notify.assert_called_with(
            "Não foi possível inserir o texto de voz automaticamente. "
            "Ele está na área de transferência.",
            key="voice-insert",
        )

    def test_dispatch_exception_marks_history_failed_and_returns_to_idle(self):
        self._ready()
        self.controller._insert_text = mock.Mock(
            side_effect=RuntimeError("insert exploded")
        )

        self.assertTrue(self.controller.handle_hotkey_press(MODE_DICTATION))
        self.assertTrue(self.controller.handle_hotkey_release(MODE_DICTATION))

        self.assertEqual(self.controller.state, STATE_IDLE)
        entry = self.controller.history_entries()[0]
        self.assertEqual(entry["status"], "failed")
        self.notify.assert_called_with(
            "Falha ao processar o texto de voz: insert exploded",
            key="voice-error",
        )

    def test_secure_input_reports_clipboard_failure_truthfully(self):
        self._ready()
        self.controller._secure_input_blocks = lambda: True
        with mock.patch("voice_support.Clipboard.set_content", return_value=False):
            self.controller.handle_hotkey_press(MODE_DICTATION)
            self.controller.handle_hotkey_release(MODE_DICTATION)

        self.assertEqual(self.controller.last_outcome, OUTCOME_SECURE_INPUT)
        self.notify.assert_called_with(
            "Entrada segura do macOS ativa. Não foi possível copiar o texto "
            "para a área de transferência.",
            key="voice-secure",
        )
        self.logger.warning.assert_called_once()

    def test_lost_target_reports_clipboard_failure_truthfully(self):
        self._ready()
        self.controller._restore_target = lambda target: False
        with mock.patch("voice_support.Clipboard.set_content", return_value=False):
            self.controller.handle_hotkey_press(MODE_DICTATION)
            self.controller.handle_hotkey_release(MODE_DICTATION)

        self.assertEqual(self.controller.last_outcome, OUTCOME_TARGET_LOST)
        self.notify.assert_called_with(
            "O aplicativo de destino não está mais na frente e não foi "
            "possível copiar o texto para a área de transferência.",
            key="voice-target",
        )
        self.logger.warning.assert_called_once()

    def test_status_callback_covers_interactive_session_states(self):
        self._ready()
        seen = []
        self.controller._on_status_change = lambda: seen.append(
            self.controller.status_snapshot()
        )
        self.controller.handle_hotkey_press(MODE_DICTATION)
        self.controller.handle_hotkey_release(MODE_DICTATION)
        self.assertEqual(
            [item["state"] for item in seen],
            [STATE_RECORDING, STATE_TRANSCRIBING, STATE_ROUTING, STATE_IDLE],
        )
        self.assertEqual(seen[0]["mode"], MODE_DICTATION)
        self.assertIsNone(seen[-1]["mode"])

    def test_cancel_returns_indicator_state_to_idle(self):
        self._ready()
        seen = []
        self.controller._on_status_change = lambda: seen.append(self.controller.state)
        self.controller.handle_hotkey_press(MODE_DICTATION)
        self.controller.cancel()
        self.assertEqual(seen, [STATE_RECORDING, STATE_IDLE])

    def test_voice_command_expands(self):
        self._ready()
        self.controller.settings.voice_replacements = {"xadds": "wrong"}
        self.backend.transcript = "xadds"
        self.controller.handle_hotkey_press(MODE_COMMAND)
        self.controller.handle_hotkey_release(MODE_COMMAND)
        self.assertEqual(self.expanded, ["xadds"])

    def test_stream_tail_chunks_are_fed_before_finalize(self):
        self.backend.start_stream()
        capture = _ChunkCapture([[0.1, 0.2], [0.3]])

        self.controller._drain_stream_chunks(capture)

        self.assertEqual(self.backend._stream, [[0.1, 0.2], [0.3]])

    def test_stream_completion_is_scoped_to_its_generation(self):
        import threading

        old_done = threading.Event()
        new_done = threading.Event()
        self.controller._stream_worker_events[2] = new_done

        self.controller._stream_worker(1, old_done)

        self.assertTrue(old_done.is_set())
        self.assertFalse(new_done.is_set())

    def test_dictation_applies_term_correction_and_keeps_raw_transcript(self):
        self._ready()
        self.controller.settings.voice_replacements = {"Queen": "Qwen"}
        self.backend.transcript = "Testing Queen now"

        self.controller.handle_hotkey_press(MODE_DICTATION)
        self.controller.handle_hotkey_release(MODE_DICTATION)

        self.assertEqual(self.inserted, ["Testing Qwen now"])
        entry = self.controller.history_entries()[0]
        self.assertEqual(entry["transcript"], "Testing Qwen now")
        self.assertEqual(entry["raw_transcript"], "Testing Queen now")
        self.assertIn("inference_duration_seconds", entry)

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

    def test_input_status_failure_is_not_reported_as_duration_limit(self):
        self.capture.issue = CaptureIssue.INPUT_STATUS
        self._ready()
        with mock.patch.object(
            self.backend, "transcribe", wraps=self.backend.transcribe
        ) as transcribe:
            self.controller.handle_hotkey_press(MODE_DICTATION)
            self.controller.handle_hotkey_release(MODE_DICTATION)

        transcribe.assert_not_called()
        entry = self.controller.history_entries()[0]
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["capture_issue"], "input_status")
        self.assertEqual(
            entry["capture_issues"],
            [{"issue": "input_status", "message": "capture failed"}],
        )
        self.assertTrue(self.controller._history.is_retryable(entry["id"]))
        self.notify.assert_called_with(
            "O microfone relatou uma falha durante a gravação. "
            "O áudio parcial foi salvo no histórico.",
            key="voice-error",
        )

    def test_unexpected_stop_failure_closes_the_history_journal(self):
        self._ready()
        self.controller.handle_hotkey_press(MODE_DICTATION)
        recording = self.controller._history_recording
        self.capture.stop = mock.Mock(side_effect=OSError("device lost"))

        self.controller.handle_hotkey_release(MODE_DICTATION)

        self.assertTrue(recording._closed)
        entry = self.controller.history_entry(recording.record_id)
        self.assertEqual(entry["status"], "failed")
        self.assertIn("device lost", entry["error"])

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

    def test_profile_switch_emits_final_idle_status_after_success(self):
        self._ready()
        seen = []
        self.controller._on_status_change = lambda: seen.append(self.controller.state)
        with mock.patch("voice_support.model_is_installed", return_value=True), \
                mock.patch("voice_support.installed_model_path", return_value="new.gguf"), \
                mock.patch.object(self.controller, "_start_monitor"):
            self.controller.set_profile("accuracy")
        self.assertEqual(seen, [STATE_LOADING, STATE_IDLE])
        self.assertEqual(self.controller.settings.profile, "accuracy")

    def test_profile_switch_emits_final_idle_status_after_rollback(self):
        self._ready()
        seen = []
        self.controller._on_status_change = lambda: seen.append(self.controller.state)
        self.backend.load = mock.Mock(side_effect=[Exception("new model failed"), None])
        with mock.patch("voice_support.model_is_installed", return_value=True), \
                mock.patch("voice_support.installed_model_path", return_value="old.gguf"), \
                mock.patch.object(self.controller, "_start_monitor"):
            self.controller.set_profile("accuracy")
        self.assertEqual(seen, [STATE_LOADING, STATE_IDLE])
        self.assertEqual(self.controller.settings.profile, "balanced")

    def test_profile_switch_emits_unavailable_status_after_terminal_failure(self):
        self._ready()
        seen = []
        self.controller._on_status_change = lambda: seen.append(self.controller.state)
        self.backend.load = mock.Mock(side_effect=Exception("new model failed"))
        with mock.patch("voice_support.model_is_installed", return_value=True), \
                mock.patch("voice_support.installed_model_path", return_value=None), \
                mock.patch.object(self.controller, "_start_monitor"):
            self.controller.set_profile("accuracy")
        self.assertEqual(seen, [STATE_LOADING, STATE_UNAVAILABLE])
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

    def test_hotkey_change_restarts_monitor_without_reloading_backend(self):
        self._ready()
        with mock.patch.object(self.controller, "_start_monitor") as start_monitor, \
                mock.patch.object(self.backend, "load", wraps=self.backend.load) as load:
            self.controller.apply_options(
                hotkey="control+shift+f8",
                command_hotkey="ctrl+alt+f9",
            )
        self.assertEqual(self.controller.settings.hotkey, "ctrl+shift+f8")
        self.assertEqual(self.controller.settings.command_hotkey, "ctrl+alt+f9")
        start_monitor.assert_called_once_with()
        load.assert_not_called()

    def test_hotkey_change_cancels_an_active_recording(self):
        self._ready()
        self.assertTrue(self.controller.handle_hotkey_press(MODE_DICTATION))
        with mock.patch.object(self.controller, "_start_monitor"):
            self.controller.apply_options(hotkey="ctrl+shift+f8")
        self.assertGreaterEqual(self.capture.stop_calls, 1)
        self.assertFalse(self.capture.started)
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

    def test_explicit_model_download_does_not_enable_or_load_voice(self):
        seen = []
        downloaded = []
        self.controller._on_status_change = lambda: seen.append(
            self.controller.status_label()
        )

        def fake_download(entry, cache_dir, progress=None, cancel_event=None):
            downloaded.append(entry["profile"])
            if progress is not None:
                progress(50, 100)
            return os.path.join(self.tmp, "model.gguf")

        self.controller._download = fake_download
        with mock.patch("voice_support.model_is_installed", return_value=False):
            started = self.controller.download_profile("compact")

        self.assertTrue(started)
        self.assertEqual(downloaded, ["compact"])
        self.assertFalse(self.controller.is_enabled())
        self.assertFalse(self.backend.is_loaded())
        self.assertTrue(any("baixando" in label for label in seen))
        self.notify.assert_called_with(
            "Modelo de voz baixado e verificado.", key="voice-model-download"
        )

    def test_duplicate_explicit_download_is_rejected_while_active(self):
        self.controller._model_download_active = True
        self.controller._model_download_profile = "compact"

        self.assertFalse(self.controller.download_profile("compact"))

    def test_enable_after_disable_returns_to_idle(self):
        self._ready()
        self.controller.disable()
        self.assertEqual(self.controller.state, STATE_UNAVAILABLE)
        self._ready()
        self.assertEqual(self.controller.state, STATE_IDLE)
        self.assertTrue(self.controller.handle_hotkey_press(MODE_DICTATION))
        self.assertEqual(self.controller.state, STATE_RECORDING)

    def test_switch_during_recording_stops_capture(self):
        self._ready()
        self.assertTrue(self.controller.handle_hotkey_press(MODE_DICTATION))
        self.assertEqual(self.controller.state, STATE_RECORDING)
        with mock.patch("voice_support.model_is_installed", return_value=True), \
                mock.patch("voice_support.installed_model_path", return_value="model.gguf"), \
                mock.patch.object(self.controller, "_start_monitor"):
            self.controller.set_language("en-US")
        self.assertGreaterEqual(self.capture.stop_calls, 1)
        self.assertFalse(self.capture.started)
        self.assertFalse(self.controller.handle_hotkey_release(MODE_DICTATION))
        self.assertEqual(self.inserted, [])

    def test_closed_form_does_not_receive_a_later_forms_transcript(self):
        self._ready()
        first = []
        second = []
        self.controller.register_form_target(lambda text: first.append(text))
        self.controller.handle_hotkey_press(MODE_DICTATION)
        self.controller.unregister_form_target()
        self.controller.register_form_target(lambda text: second.append(text))
        self.backend.transcript = "João"
        self.controller.handle_hotkey_release(MODE_DICTATION)
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(self.inserted, [])
        self.controller._invoke_session_form("tarde demais")
        self.assertEqual(first, [])
        self.assertEqual(second, [])

    def test_shutdown_cancels_native_inference_before_unload(self):
        import threading
        import time

        class ThreadRunner:
            def start(self, fn, *args, name=None):
                thread = threading.Thread(target=fn, args=args, daemon=True, name=name)
                thread.start()
                return thread

        entered = threading.Event()
        left = threading.Event()
        unloaded_before_exit = []

        class SlowBackend(FakeAsrBackend):
            def transcribe(self, pcm, cancel_event=None):
                entered.set()
                try:
                    deadline = time.time() + 1.0
                    while time.time() < deadline:
                        if self._cancelled(cancel_event):
                            raise VoiceRuntimeError("Transcrição cancelada.")
                        time.sleep(0.01)
                    return self.transcript
                finally:
                    left.set()

            def unload(self):
                unloaded_before_exit.append(not left.is_set())
                super().unload()

        backend = SlowBackend(transcript="late")
        controller = VoiceController(
            {"voice_enabled": False},
            task_runner=ThreadRunner(),
            insert_text=lambda text: self.inserted.append(text) or True,
            expand_trigger=lambda trigger: True,
            notify=self.notify,
            logger=self.logger,
            capture_target=lambda: VoiceTarget("window", handle=1),
            restore_target=lambda target: True,
            secure_input_blocks=lambda: False,
            backend=backend,
            capture_factory=lambda: FakeCapture(),
            cache_dir=self.tmp,
            download=lambda entry, cache_dir, progress=None, cancel_event=None: os.path.join(
                self.tmp, "model.gguf"
            ),
        )
        with mock.patch("voice_support.model_is_installed", return_value=True), \
                mock.patch("voice_support.installed_model_path", return_value="model.gguf"), \
                mock.patch.object(controller, "_start_monitor"):
            controller.enable()
        self.assertTrue(controller.handle_hotkey_press(MODE_DICTATION))
        self.assertTrue(controller.handle_hotkey_release(MODE_DICTATION))
        self.assertTrue(entered.wait(1.0))
        controller.shutdown(timeout=1.0)
        self.assertTrue(left.wait(1.0))
        self.assertGreaterEqual(backend.cancel_calls, 1)
        self.assertEqual(unloaded_before_exit, [False])
        self.assertEqual(self.inserted, [])

    def test_switch_during_transcription_keeps_loading_and_rejects_press(self):
        import threading
        import time

        class ThreadRunner:
            def start(self, fn, *args, name=None):
                thread = threading.Thread(target=fn, args=args, daemon=True, name=name)
                thread.start()
                return thread

        entered = threading.Event()
        in_unload = threading.Event()
        allow_unload = threading.Event()
        captures = []

        class SlowBackend(FakeAsrBackend):
            def transcribe(self, pcm, cancel_event=None):
                entered.set()
                deadline = time.time() + 1.0
                while time.time() < deadline:
                    if self._cancelled(cancel_event):
                        raise VoiceRuntimeError("Transcrição cancelada.")
                    time.sleep(0.01)
                return self.transcript

            def unload(self):
                in_unload.set()
                allow_unload.wait(1.0)
                super().unload()

        def factory():
            capture = FakeCapture()
            captures.append(capture)
            return capture

        backend = SlowBackend(transcript="late")
        controller = VoiceController(
            {"voice_enabled": False},
            task_runner=ThreadRunner(),
            insert_text=lambda text: self.inserted.append(text) or True,
            expand_trigger=lambda trigger: True,
            notify=self.notify,
            logger=self.logger,
            capture_target=lambda: VoiceTarget("window", handle=1),
            restore_target=lambda target: True,
            secure_input_blocks=lambda: False,
            backend=backend,
            capture_factory=factory,
            cache_dir=self.tmp,
            download=lambda entry, cache_dir, progress=None, cancel_event=None: os.path.join(
                self.tmp, "model.gguf"
            ),
        )
        with mock.patch("voice_support.model_is_installed", return_value=True), \
                mock.patch("voice_support.installed_model_path", return_value="model.gguf"), \
                mock.patch.object(controller, "_start_monitor"):
            controller.enable()
            deadline = time.time() + 1.0
            while controller.state != STATE_IDLE and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(controller.state, STATE_IDLE)
            self.assertTrue(controller.handle_hotkey_press(MODE_DICTATION))
            self.assertTrue(controller.handle_hotkey_release(MODE_DICTATION))
            self.assertTrue(entered.wait(1.0))
            controller.set_language("en-US")
            self.assertTrue(in_unload.wait(1.0))
            self.assertEqual(controller.state, STATE_LOADING)
            self.assertFalse(controller.handle_hotkey_press(MODE_DICTATION))
            allow_unload.set()
            deadline = time.time() + 1.0
            while controller.state == STATE_LOADING and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(controller.state, STATE_IDLE)
        self.assertFalse(any(capture.started for capture in captures))
        self.assertEqual(self.inserted, [])


if __name__ == "__main__":
    unittest.main()
