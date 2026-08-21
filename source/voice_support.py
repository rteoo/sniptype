"""Voice input state machine: one session from enable through paste.

States: unavailable, loading, idle, recording, transcribing, routing.
Hotkey callbacks only flip guarded state and enqueue work. Capture, download,
inference, Tk, and disk stay off the keyboard threads.
"""

import threading
import time

from clipboard_support import Clipboard
from voice_audio import AudioCapture, VoiceAudioError, sounddevice_available
from voice_catalog import PROFILE_STREAMING, catalog_entry
from voice_dispatch import (
    MODE_COMMAND,
    MODE_DICTATION,
    OUTCOME_CANCELLED,
    OUTCOME_EMPTY,
    OUTCOME_FAILED,
    OUTCOME_NO_MATCH,
    OUTCOME_SECURE_INPUT,
    OUTCOME_TARGET_LOST,
    VoiceTarget,
    dispatch_voice_result,
)
from voice_hotkey import VoiceHotkeyMonitor, parse_chord
from voice_models import (
    VoiceModelError,
    default_voice_cache_dir,
    delete_model,
    download_model,
    installed_model_path,
    model_is_installed,
)
from voice_runtime import AsrBackend, VoiceRuntimeError, create_backend
from voice_settings import resolve_voice_settings, voice_settings_payload


STATE_UNAVAILABLE = "unavailable"
STATE_LOADING = "loading"
STATE_IDLE = "idle"
STATE_RECORDING = "recording"
STATE_TRANSCRIBING = "transcribing"
STATE_ROUTING = "routing"

_SHUTDOWN_JOIN_SECONDS = 2.0

_STATE_LABELS = {
    STATE_UNAVAILABLE: "Entrada por voz (indisponível)",
    STATE_LOADING: "Entrada por voz (carregando…)",
    STATE_IDLE: "Entrada por voz (pronta)",
    STATE_RECORDING: "Entrada por voz (gravando…)",
    STATE_TRANSCRIBING: "Entrada por voz (transcrevendo…)",
    STATE_ROUTING: "Entrada por voz (inserindo…)",
}


class VoiceController:
    """Owns the voice feature for one TextExpander process."""

    def __init__(
        self,
        settings,
        task_runner,
        insert_text,
        expand_trigger,
        notify,
        logger,
        persist_settings=None,
        gui_submit=None,
        capture_target=None,
        restore_target=None,
        secure_input_blocks=None,
        microphone_status=None,
        on_status_change=None,
        backend=None,
        capture_factory=None,
        cache_dir=None,
        download=None,
    ):
        warnings = []
        self.settings = resolve_voice_settings(settings, warnings)
        self.task_runner = task_runner
        self._insert_text = insert_text
        self._expand_trigger = expand_trigger
        self._notify = notify
        self._logger = logger
        self._persist_settings = persist_settings
        self._gui_submit = gui_submit
        self._capture_target = capture_target or (lambda: VoiceTarget("unknown"))
        self._restore_target = restore_target or (lambda target: True)
        self._secure_input_blocks = secure_input_blocks or (lambda: False)
        self._microphone_status = microphone_status
        self._on_status_change = on_status_change
        self._download_done = 0
        self._download_total = 0
        self._backend = backend if backend is not None else create_backend()
        self._capture_factory = capture_factory or AudioCapture
        self._download = download or download_model
        self.cache_dir = cache_dir or self.settings.cache_dir or default_voice_cache_dir()
        self._lock = threading.Lock()
        self._state = STATE_UNAVAILABLE
        self._session_generation = 0
        self._cancel = threading.Event()
        self._shutdown = threading.Event()
        self._active_mode = None
        self._active_target = None
        self._session_form_apply = None
        self._capture = None
        self._form_apply = None
        self._partial = ""
        self._monitor = None
        self._load_error = None
        self._workers = []
        self.last_outcome = None
        for warning in warnings:
            self._log(warning)

    def _log(self, message):
        logger = self._logger
        if logger is None:
            return
        info = getattr(logger, "info", None)
        if info is not None:
            info(message)

    def _warn(self, message):
        logger = self._logger
        if logger is None:
            return
        warning = getattr(logger, "warning", None) or getattr(logger, "info", None)
        if warning is not None:
            warning(message)

    @property
    def state(self):
        with self._lock:
            return self._state

    def status_label(self):
        with self._lock:
            if not self.settings.enabled:
                return "Entrada por voz"
            if self._state == STATE_LOADING and self._download_total:
                percent = min(100, int(100 * self._download_done / self._download_total))
                return f"Entrada por voz (baixando {percent}%)"
            return _STATE_LABELS.get(self._state, "Entrada por voz")

    def _emit_status(self):
        callback = self._on_status_change
        if callback is None:
            return
        try:
            callback()
        except Exception:
            pass

    def is_enabled(self):
        return bool(self.settings.enabled)

    @property
    def enabled(self):
        return self.is_enabled()

    @property
    def profile(self):
        return self.settings.profile

    def set_enabled(self, enabled):
        if enabled:
            self.enable()
        else:
            self.disable()

    def model_installed(self):
        entry = catalog_entry(self.settings.profile)
        return bool(entry and model_is_installed(entry, self.cache_dir))

    def set_language(self, language):
        self.apply_options(language=language)

    def apply_options(
        self,
        profile=None,
        language=None,
        hotkey=None,
        command_hotkey=None,
    ):
        """Persist voice options and apply only the runtime changes required."""
        warnings = []
        payload = voice_settings_payload(self.settings)
        if profile is not None:
            payload["voice_profile"] = profile
        if language is not None:
            payload["voice_language"] = language
        if hotkey is not None:
            payload["voice_hotkey"] = hotkey
        if command_hotkey is not None:
            payload["voice_command_hotkey"] = command_hotkey
        candidate = resolve_voice_settings(payload, warnings)
        for warning in warnings:
            self._log(warning)
        previous = self.settings
        runtime_same = (
            candidate.profile == previous.profile
            and candidate.language == previous.language
        )
        hotkeys_same = (
            candidate.hotkey == previous.hotkey
            and candidate.command_hotkey == previous.command_hotkey
        )
        self.settings = candidate
        self._persist()
        if runtime_same and hotkeys_same:
            if candidate.enabled and self.state == STATE_UNAVAILABLE:
                self.enable()
            return
        if not candidate.enabled:
            return
        with self._lock:
            active = self._state in (
                STATE_RECORDING,
                STATE_TRANSCRIBING,
                STATE_ROUTING,
            )
        if runtime_same:
            if active:
                self._cancel_session_locked(reason="hotkey")
            with self._lock:
                state = self._state
            if state == STATE_IDLE:
                self._start_monitor()
            elif state == STATE_UNAVAILABLE:
                self.enable()
            # A load already in progress starts the monitor with the latest
            # settings when it reaches idle.
            return
        if active:
            # Stop the microphone before the switch worker unloads the backend.
            # The abort also bumps the session generation and keeps LOADING so
            # a cancelled finish worker cannot reopen IDLE mid-unload.
            self._cancel_session_locked(reason="switch")
        else:
            with self._lock:
                if not candidate.enabled:
                    return
                self._session_generation += 1
                self._state = STATE_LOADING
            self._emit_status()
        self._start_worker(
            self._switch_profile_worker,
            previous,
            name="voice-switch",
        )

    def partial_text(self):
        with self._lock:
            return self._partial

    def status_snapshot(self):
        """Return one consistent status value for UI callbacks."""
        with self._lock:
            return {
                "state": self._state,
                "mode": self._active_mode,
                "partial": self._partial,
            }

    def register_form_target(self, apply_fn):
        with self._lock:
            self._form_apply = apply_fn

    def unregister_form_target(self):
        with self._lock:
            closed = self._form_apply
            self._form_apply = None
            if self._session_form_apply is closed:
                self._session_form_apply = None

    def enable(self):
        if self._shutdown.is_set():
            return
        with self._lock:
            self.settings.enabled = True
            if self._state in (STATE_LOADING, STATE_IDLE):
                return
            if self._state in (STATE_RECORDING, STATE_TRANSCRIBING, STATE_ROUTING):
                return
            # disable()/cancel() leave this set; a later enable must start clean.
            self._cancel.clear()
            self._state = STATE_LOADING
            self._load_error = None
            self._download_done = 0
            self._download_total = 0
        self._persist()
        self._emit_status()
        self._start_worker(self._load_worker, name="voice-load")

    def disable(self):
        self._cancel_session_locked(reason="disable")
        self._join_workers(_SHUTDOWN_JOIN_SECONDS)
        with self._lock:
            self.settings.enabled = False
            self._state = STATE_UNAVAILABLE
        self._stop_monitor()
        try:
            self._backend.unload()
        except Exception:
            pass
        self._persist()
        self._emit_status()

    def shutdown(self, timeout=_SHUTDOWN_JOIN_SECONDS):
        self._shutdown.set()
        self._cancel_session_locked(reason="shutdown")
        self._stop_monitor()
        with self._lock:
            self._state = STATE_UNAVAILABLE
            self.settings.enabled = False
        self._emit_status()
        # ceiling: 2 s. A stuck native run is abandoned after this and then
        # unloaded; raise if a real backend needs a longer bounded wait.
        joined = self._join_workers(timeout)
        if not joined:
            self._warn("Encerramento da voz atingiu o tempo limite; descarregando mesmo assim.")
        try:
            self._backend.unload()
        except Exception:
            pass

    def set_profile(self, profile):
        self.apply_options(profile=profile)

    def handle_hotkey_press(self, mode):
        if self._shutdown.is_set():
            return False
        with self._lock:
            if self._state != STATE_IDLE:
                return False
            if mode not in (MODE_DICTATION, MODE_COMMAND):
                mode = MODE_DICTATION
            form_apply = self._form_apply
        if self._microphone_status is not None:
            status = self._microphone_status()
            if status == "denied":
                self._notify(
                    "O macOS bloqueou o microfone. Conceda a permissão e reinicie o app.",
                    key="voice-mic",
                )
                return False
        target = self._capture_target()
        session_form = None
        if form_apply is not None and mode != MODE_COMMAND:
            target = VoiceTarget("form", handle=form_apply)
            session_form = form_apply
        try:
            capture = self._capture_factory()
            capture.start()
        except VoiceAudioError as exc:
            self._notify(str(exc), key="voice-audio")
            return False
        except Exception as exc:
            self._notify(f"Não foi possível gravar: {exc}", key="voice-audio")
            return False
        with self._lock:
            if self._state != STATE_IDLE or self._shutdown.is_set():
                try:
                    capture.stop()
                except Exception:
                    pass
                return False
            self._session_generation += 1
            self._cancel.clear()
            self._active_mode = mode
            self._active_target = target
            self._session_form_apply = session_form
            self._capture = capture
            self._partial = ""
            self._state = STATE_RECORDING
            generation = self._session_generation
        self._emit_status()
        if self.settings.profile == PROFILE_STREAMING:
            self._start_worker(self._stream_worker, generation, name="voice-stream")
        return True

    def handle_hotkey_release(self, mode):
        if self._shutdown.is_set():
            return False
        with self._lock:
            if self._state != STATE_RECORDING:
                return False
            generation = self._session_generation
            capture = self._capture
            self._capture = None
            self._state = STATE_TRANSCRIBING
        self._emit_status()
        self._start_worker(
            self._finish_worker,
            generation,
            capture,
            name="voice-finish",
        )
        return True

    def cancel(self):
        self._cancel_session_locked(reason="cancel")

    def _cancel_session_locked(self, reason):
        self._cancel.set()
        try:
            self._backend.cancel()
        except Exception:
            pass
        capture = None
        with self._lock:
            if self._state in (STATE_RECORDING, STATE_TRANSCRIBING, STATE_ROUTING):
                capture = self._capture
                self._capture = None
                self._active_mode = None
                self._active_target = None
                self._session_form_apply = None
                self._partial = ""
                self.last_outcome = OUTCOME_CANCELLED
                if reason == "switch":
                    self._session_generation += 1
                    self._state = STATE_LOADING
                elif reason == "shutdown":
                    self._session_generation += 1
                    self._state = STATE_UNAVAILABLE
                else:
                    self._state = (
                        STATE_IDLE if self.settings.enabled else STATE_UNAVAILABLE
                    )
        if capture is not None:
            try:
                capture.stop()
            except Exception:
                pass
        self._emit_status()

    def _load_worker(self):
        if self._shutdown.is_set():
            return
        try:
            if not self._backend.available() and not self._backend.is_loaded():
                raise VoiceRuntimeError(
                    "O runtime transcribe.cpp não está instalado. "
                    "A voz fica desligada até o pacote nativo estar disponível."
                )
            path = self._ensure_model()
            if self._cancel.is_set() or self._shutdown.is_set():
                return
            self._backend.load(path, self.settings.profile, self.settings.language)
        except (VoiceModelError, VoiceRuntimeError) as exc:
            with self._lock:
                self._state = STATE_UNAVAILABLE
                self._load_error = str(exc)
            self._notify(str(exc), key="voice-load")
            self._emit_status()
            return
        except Exception as exc:
            with self._lock:
                self._state = STATE_UNAVAILABLE
                self._load_error = str(exc)
            self._warn(f"Falha ao ativar a entrada por voz: {exc}")
            self._notify(f"Falha ao ativar a entrada por voz: {exc}", key="voice-load")
            self._emit_status()
            return
        with self._lock:
            if not self.settings.enabled or self._shutdown.is_set():
                self._state = STATE_UNAVAILABLE
                start_monitor = False
            else:
                self._state = STATE_IDLE
                self._load_error = None
                self._download_done = 0
                self._download_total = 0
                start_monitor = True
        if start_monitor:
            self._start_monitor()
        self._emit_status()

    def _switch_profile_worker(self, previous):
        if self._shutdown.is_set():
            return
        # A cancelled finish/stream worker may still be inside native inference.
        self._join_workers(_SHUTDOWN_JOIN_SECONDS)
        if self._shutdown.is_set():
            return
        # The aborted session set this; a new download/load must not inherit it.
        self._cancel.clear()
        try:
            self._backend.unload()
            path = self._ensure_model()
            self._backend.load(path, self.settings.profile, self.settings.language)
        except Exception as exc:
            self._warn(f"Falha ao trocar o perfil de voz; mantendo o anterior: {exc}")
            self.settings = previous
            self._persist()
            try:
                path = installed_model_path(
                    catalog_entry(previous.profile), self.cache_dir
                )
                if path:
                    self._backend.load(path, previous.profile, previous.language)
                    with self._lock:
                        self._state = STATE_IDLE
                    self._emit_status()
                    return
            except Exception:
                pass
            with self._lock:
                self._state = STATE_UNAVAILABLE
            self._emit_status()
            self._notify(str(exc), key="voice-switch")
            return
        with self._lock:
            self._state = STATE_IDLE
        self._start_monitor()
        self._emit_status()

    def _ensure_model(self):
        entry = catalog_entry(self.settings.profile)
        if entry is None:
            raise VoiceModelError("Perfil de voz desconhecido.")
        if model_is_installed(entry, self.cache_dir):
            return installed_model_path(entry, self.cache_dir)

        def progress(done, total):
            with self._lock:
                self._download_done = done
                self._download_total = total or entry["size_bytes"]
            self._emit_status()

        return self._download(
            entry,
            self.cache_dir,
            progress=progress,
            cancel_event=self._cancel,
        )

    def _finish_worker(self, generation, capture):
        if self._shutdown.is_set():
            return
        pcm = []
        overflow = False
        if capture is not None:
            try:
                pcm, overflow = capture.stop()
            except Exception as exc:
                self._fail_to_idle(f"Falha ao encerrar a gravação: {exc}", generation)
                return
        if overflow:
            self._fail_to_idle(
                "A gravação de voz estourou o limite e foi cancelada.",
                generation,
            )
            return
        if self._cancel.is_set() or self._shutdown.is_set():
            self._complete_session(generation, OUTCOME_CANCELLED)
            return
        try:
            if self.settings.profile == PROFILE_STREAMING and self._backend.supports_stream():
                transcript = self._backend.finalize_stream()
            else:
                transcript = self._backend.transcribe(pcm, cancel_event=self._cancel)
        except VoiceRuntimeError as exc:
            self._fail_to_idle(str(exc), generation)
            return
        except Exception as exc:
            self._fail_to_idle(f"Falha na transcrição: {exc}", generation)
            return
        if self._cancel.is_set() or self._shutdown.is_set():
            self._complete_session(generation, OUTCOME_CANCELLED)
            return
        with self._lock:
            if generation != self._session_generation:
                return
            if self._state != STATE_TRANSCRIBING:
                return
            self._state = STATE_ROUTING
            mode = self._active_mode or MODE_DICTATION
            target = self._active_target
            form_apply = self._session_form_apply
        self._emit_status()
        if self._shutdown.is_set():
            return
        if getattr(target, "kind", None) == "form" and form_apply is None:
            self._complete_session(generation, OUTCOME_CANCELLED)
            return
        outcome = dispatch_voice_result(
            transcript,
            mode,
            target,
            snippets=self._snippets(),
            trigger_index=self._trigger_index(),
            insert_text=self._insert_text,
            expand_trigger=self._expand_trigger,
            apply_form=(
                self._invoke_session_form
                if form_apply is not None and mode != MODE_COMMAND
                else None
            ),
            restore_target=self._restore_target,
            secure_input_blocks=self._secure_input_blocks,
            leave_on_clipboard=self._leave_on_clipboard,
            cancelled=self._cancel.is_set(),
        )
        self._finish_outcome(outcome, generation)

    def _stream_worker(self, generation):
        if not self._backend.supports_stream():
            return
        try:
            self._backend.start_stream()
        except VoiceRuntimeError:
            return
        # Display-only partials. The release path finalizes.
        while not self._shutdown.is_set() and not self._cancel.is_set():
            with self._lock:
                if self._state != STATE_RECORDING or generation != self._session_generation:
                    return
                capture = self._capture
            if capture is None:
                return
            try:
                chunk = capture._queue.get(timeout=0.1)
            except Exception:
                continue
            try:
                partial = self._backend.feed(_flatten(chunk))
            except Exception:
                return
            with self._lock:
                self._partial = partial or ""

    def _snippets(self):
        getter = getattr(self, "get_snippets", None)
        if getter is not None:
            return getter()
        return {}

    def _trigger_index(self):
        getter = getattr(self, "get_trigger_index", None)
        if getter is not None:
            return getter()
        return None

    def bind_library(self, get_snippets, get_trigger_index):
        self.get_snippets = get_snippets
        self.get_trigger_index = get_trigger_index

    def _invoke_session_form(self, text):
        """Apply only if the form captured at press is still the session target."""
        with self._lock:
            apply_fn = self._session_form_apply
        if apply_fn is None:
            return
        apply_fn(text)

    def _leave_on_clipboard(self, text):
        try:
            Clipboard.set_content(text)
        except Exception:
            pass

    def _complete_session(self, generation, outcome):
        """Return True when this session still owns the controller state."""
        with self._lock:
            if generation != self._session_generation:
                return False
            if self._state not in (
                STATE_RECORDING,
                STATE_TRANSCRIBING,
                STATE_ROUTING,
            ):
                return False
            self.last_outcome = outcome
            self._active_mode = None
            self._active_target = None
            self._session_form_apply = None
            self._partial = ""
            self._state = STATE_IDLE if self.settings.enabled else STATE_UNAVAILABLE
        self._emit_status()
        return True

    def _finish_outcome(self, outcome, generation):
        if not self._complete_session(generation, outcome):
            return
        if outcome == OUTCOME_NO_MATCH:
            self._notify("Nenhum atalho corresponde ao que foi falado.", key="voice-nomatch")
        elif outcome == OUTCOME_SECURE_INPUT:
            self._notify(
                "Entrada segura do macOS ativa. O texto ficou na área de transferência.",
                key="voice-secure",
            )
        elif outcome == OUTCOME_TARGET_LOST:
            self._notify(
                "O aplicativo de destino não está mais na frente. "
                "O texto ficou na área de transferência.",
                key="voice-target",
            )
        elif outcome == OUTCOME_EMPTY:
            self._notify("Nenhuma fala foi reconhecida.", key="voice-empty")
        elif outcome == OUTCOME_FAILED:
            self._notify("Não foi possível inserir o texto de voz.", key="voice-insert")

    def _fail_to_idle(self, message, generation=None):
        if generation is None:
            with self._lock:
                generation = self._session_generation
        if self._complete_session(generation, OUTCOME_FAILED):
            self._notify(message, key="voice-error")

    def _persist(self):
        if self._persist_settings is None:
            return
        try:
            self._persist_settings(voice_settings_payload(self.settings))
        except Exception as exc:
            self._warn(f"Não foi possível gravar as configurações de voz: {exc}")

    def _start_monitor(self):
        self._stop_monitor()
        try:
            dictation = parse_chord(self.settings.hotkey)
            command = parse_chord(self.settings.command_hotkey)
        except ValueError as exc:
            self._warn(f"Atalho de voz inválido: {exc}")
            return
        monitor = VoiceHotkeyMonitor(
            dictation,
            command,
            on_press=self._hotkey_press_from_os,
            on_release=self._hotkey_release_from_os,
            on_escape=self._hotkey_escape_from_os,
        )
        try:
            monitor.start()
        except Exception as exc:
            self._warn(f"Não foi possível observar o atalho de voz: {exc}")
            return
        self._monitor = monitor

    def _stop_monitor(self):
        monitor = self._monitor
        self._monitor = None
        if monitor is not None:
            monitor.stop()

    def _start_worker(self, fn, *args, name=None):
        thread = self.task_runner.start(fn, *args, name=name)
        if thread is None or not hasattr(thread, "join"):
            return thread
        with self._lock:
            self._workers.append(thread)
        return thread

    def _join_workers(self, timeout):
        """Join tracked voice workers except the caller. True if all finished."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        current = threading.current_thread()
        with self._lock:
            workers = list(self._workers)
        pending = []
        for thread in workers:
            if thread is current:
                pending.append(thread)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                pending.append(thread)
                continue
            try:
                thread.join(remaining)
            except Exception:
                pass
            if thread.is_alive():
                pending.append(thread)
        with self._lock:
            self._workers = pending
        return not pending

    def _hotkey_press_from_os(self, mode):
        # OS callback: enqueue only.
        if self._shutdown.is_set():
            return
        self._start_worker(self.handle_hotkey_press, mode, name="voice-press")

    def _hotkey_release_from_os(self, mode):
        if self._shutdown.is_set():
            return
        self._start_worker(self.handle_hotkey_release, mode, name="voice-release")

    def _hotkey_escape_from_os(self):
        if self._shutdown.is_set():
            return
        self._start_worker(self.cancel, name="voice-escape")

    def delete_active_model(self):
        """Disable voice, then remove only the catalog directory of the profile."""
        entry = catalog_entry(self.settings.profile)
        self.disable()
        if entry is None:
            return
        delete_model(entry, self.cache_dir)


def _flatten(chunk):
    if chunk is None:
        return []
    if hasattr(chunk, "flatten"):
        return [float(value) for value in chunk.flatten()]
    return [float(value) for value in chunk]
