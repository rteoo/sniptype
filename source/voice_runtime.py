"""Optional ASR backends. The production binding is transcribe.cpp.

The package is optional until a self-contained wheel exists. Tests inject a
fake backend. Missing native code leaves voice unavailable instead of crashing.
"""

import threading

from voice_catalog import (
    LANGUAGE_AUTO,
    LANGUAGE_EN_US,
    LANGUAGE_PT_BR,
    PROFILE_ACCURACY,
    PROFILE_STREAMING,
)


_MODEL_LANGUAGE_CODES = {
    LANGUAGE_PT_BR: "pt",
    LANGUAGE_EN_US: "en",
}


class VoiceRuntimeError(Exception):
    """User-visible inference or load failure."""


class AsrBackend:
    """Minimal contract one resident model must satisfy."""

    def available(self):
        return False

    def load(self, model_path, profile, language):
        raise VoiceRuntimeError("Backend de voz indisponível.")

    def unload(self):
        return None

    def is_loaded(self):
        return False

    def transcribe(self, pcm, cancel_event=None):
        raise VoiceRuntimeError("Backend de voz indisponível.")

    def cancel(self):
        """Interrupt an in-flight ``transcribe`` from another thread."""
        return None

    def start_stream(self):
        raise VoiceRuntimeError("Este perfil não faz transcrição contínua.")

    def feed(self, pcm_chunk):
        return ""

    def finalize_stream(self):
        return ""

    def supports_stream(self):
        return False


class FakeAsrBackend(AsrBackend):
    """Deterministic backend for tests. Never loads a real model."""

    def __init__(self, transcript="hello", partials=None):
        self.transcript = transcript
        self.partials = list(partials or ())
        self.loaded_path = None
        self.profile = None
        self.language = None
        self.transcribe_calls = []
        self.cancel_calls = 0
        self._cancel = threading.Event()
        self._stream = []

    def available(self):
        return True

    def load(self, model_path, profile, language):
        self.loaded_path = model_path
        self.profile = profile
        self.language = language
        self._cancel.clear()

    def unload(self):
        self.loaded_path = None
        self.profile = None
        self.language = None

    def is_loaded(self):
        return self.loaded_path is not None

    def transcribe(self, pcm, cancel_event=None):
        if self._cancelled(cancel_event):
            raise VoiceRuntimeError("Transcrição cancelada.")
        self.transcribe_calls.append(list(pcm) if pcm is not None else None)
        return self.transcript

    def cancel(self):
        self.cancel_calls += 1
        self._cancel.set()

    def _cancelled(self, cancel_event):
        return self._cancel.is_set() or (
            cancel_event is not None and cancel_event.is_set()
        )

    def supports_stream(self):
        return True

    def start_stream(self):
        self._stream = []

    def feed(self, pcm_chunk):
        self._stream.append(pcm_chunk)
        if self.partials:
            return self.partials[min(len(self._stream), len(self.partials)) - 1]
        return ""

    def finalize_stream(self):
        return self.transcript


class TranscribeCppBackend(AsrBackend):
    """Production backend. Import is lazy so the app starts without the wheel."""

    def __init__(self):
        self._model = None
        self._session = None
        self._stream = None
        self._module = None
        self._profile = None
        self._language = None

    def available(self):
        return self._import() is not None

    def _import(self):
        if self._module is not None:
            return self._module
        try:
            import transcribe_cpp
        except Exception:
            return None
        self._module = transcribe_cpp
        return self._module

    def load(self, model_path, profile, language):
        module = self._import()
        if module is None:
            raise VoiceRuntimeError(
                "O runtime transcribe.cpp não está instalado neste aplicativo."
            )
        self.unload()
        try:
            self._model = module.Model(model_path)
            self._session = self._model.session()
        except Exception as exc:
            self.unload()
            raise VoiceRuntimeError(f"Falha ao carregar o modelo de voz: {exc}") from exc
        self._profile = profile
        if profile == PROFILE_ACCURACY:
            self._language = LANGUAGE_AUTO
        else:
            self._language = language

    def unload(self):
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                close = getattr(stream, "close", None)
                if close is not None:
                    close()
            except Exception:
                pass
        session = self._session
        self._session = None
        if session is not None:
            try:
                close = getattr(session, "close", None)
                if close is not None:
                    close()
            except Exception:
                pass
        model = self._model
        self._model = None
        if model is not None:
            try:
                close = getattr(model, "close", None)
                if close is not None:
                    close()
            except Exception:
                pass
        self._profile = None
        self._language = None

    def is_loaded(self):
        return self._session is not None

    def _language_kw(self):
        if self._language in (None, LANGUAGE_AUTO) or self._profile == PROFILE_ACCURACY:
            return {}
        return {"language": _MODEL_LANGUAGE_CODES.get(self._language, self._language)}

    def cancel(self):
        session = self._session
        if session is None:
            return
        cancel = getattr(session, "cancel", None)
        if cancel is None:
            return
        try:
            cancel()
        except Exception:
            pass

    def transcribe(self, pcm, cancel_event=None):
        if self._session is None:
            raise VoiceRuntimeError("Nenhum modelo de voz está carregado.")
        if cancel_event is not None and cancel_event.is_set():
            self.cancel()
            raise VoiceRuntimeError("Transcrição cancelada.")
        done = threading.Event()

        def watch():
            while not done.wait(0.05):
                if cancel_event is not None and cancel_event.is_set():
                    self.cancel()
                    return

        watcher = None
        if cancel_event is not None:
            watcher = threading.Thread(
                target=watch, name="voice-native-cancel", daemon=True
            )
            watcher.start()
        try:
            try:
                result = self._session.run(pcm, **self._language_kw())
            except TypeError:
                result = self._session.run(pcm)
        except Exception as exc:
            raise VoiceRuntimeError(f"Falha na transcrição: {exc}") from exc
        finally:
            done.set()
            if watcher is not None:
                watcher.join(0.2)
        if cancel_event is not None and cancel_event.is_set():
            raise VoiceRuntimeError("Transcrição cancelada.")
        return _result_text(result)

    def supports_stream(self):
        return self._profile == PROFILE_STREAMING and self._session is not None and hasattr(
            self._session, "stream"
        )

    def start_stream(self):
        if not self.supports_stream():
            raise VoiceRuntimeError("Este perfil não faz transcrição contínua.")
        self._stream = self._session.stream()
        enter = getattr(self._stream, "__enter__", None)
        if enter is not None:
            self._stream = enter()

    def feed(self, pcm_chunk):
        if self._stream is None:
            return ""
        self._stream.feed(pcm_chunk)
        text = self._stream.text()
        committed = getattr(text, "committed", None)
        tentative = getattr(text, "tentative", None)
        if committed is None and tentative is None:
            return str(text or "")
        return f"{committed or ''}{tentative or ''}"

    def finalize_stream(self):
        stream = self._stream
        self._stream = None
        if stream is None:
            return ""
        try:
            finalize = getattr(stream, "finalize", None)
            if finalize is not None:
                finalize()
            text = stream.text()
            return _result_text(text)
        finally:
            close = getattr(stream, "close", None) or getattr(stream, "__exit__", None)
            if close is not None:
                try:
                    if close == getattr(stream, "__exit__", None):
                        close(None, None, None)
                    else:
                        close()
                except Exception:
                    pass


def _result_text(result):
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text
    committed = getattr(result, "committed", None)
    tentative = getattr(result, "tentative", None)
    if committed is not None or tentative is not None:
        return f"{committed or ''}{tentative or ''}"
    return str(result)


def create_backend():
    """Prefer transcribe.cpp; otherwise a backend that reports unavailable."""
    backend = TranscribeCppBackend()
    if backend.available():
        return backend
    return AsrBackend()
