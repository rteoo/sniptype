"""Microphone capture for push-to-talk.

The PortAudio callback only copies frames into a bounded queue. A worker
owns start/stop. Queue overflow fails the session instead of growing RAM.
sounddevice is imported lazily so the rest of the app starts without it.
"""

import queue


SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 4  # float32
# ceiling: 30 s of 16 kHz mono float32 (~1.9 MB). Longer holds cancel rather
# than grow without bound. Raise if real dictation needs longer takes.
MAX_SAMPLES = SAMPLE_RATE * 30
BLOCK_SIZE = 1024
QUEUE_MAX_CHUNKS = (MAX_SAMPLES + BLOCK_SIZE - 1) // BLOCK_SIZE


class VoiceAudioError(Exception):
    """User-visible capture failure."""


def sounddevice_available():
    try:
        import sounddevice  # noqa: F401
    except Exception:
        return False
    return True


class AudioCapture:
    """Bounded float32 mono capture. ``stop()`` returns (pcm_list, overflow)."""

    def __init__(self, max_samples=MAX_SAMPLES, queue_max=None):
        self.max_samples = max_samples
        if queue_max is None:
            queue_max = (max_samples + BLOCK_SIZE - 1) // BLOCK_SIZE
        self._queue = queue.Queue(maxsize=queue_max)
        self._overflow = False
        self._sample_count = 0
        self._stream = None
        self._started = False

    def start(self):
        if self._started:
            return
        try:
            import sounddevice as sd
        except Exception as exc:
            raise VoiceAudioError(
                "A captura de áudio não está disponível neste aplicativo."
            ) from exc
        self._overflow = False
        self._sample_count = 0
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        def callback(indata, frames, time_info, status):
            if status:
                self._overflow = True
            self._sample_count += frames
            if self._sample_count > self.max_samples:
                self._overflow = True
                return
            try:
                self._queue.put_nowait(indata.copy())
            except queue.Full:
                self._overflow = True

        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise VoiceAudioError(f"Não foi possível abrir o microfone: {exc}") from exc
        self._started = True

    def stop(self):
        """Close the stream and return ``(samples, overflowed)``.

        ``samples`` is a list of floats. Empty when nothing was captured.
        """
        stream = self._stream
        self._stream = None
        self._started = False
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        samples = []
        while True:
            try:
                chunk = self._queue.get_nowait()
            except queue.Empty:
                break
            samples.extend(_as_floats(chunk))
            if len(samples) > self.max_samples:
                self._overflow = True
                break
        overflow = self._overflow
        self._overflow = False
        self._sample_count = 0
        if overflow:
            return [], True
        return samples, False


def _as_floats(chunk):
    if chunk is None:
        return []
    if hasattr(chunk, "flatten"):
        flat = chunk.flatten()
        return [float(value) for value in flat]
    if isinstance(chunk, (bytes, bytearray)):
        import array
        values = array.array("f")
        values.frombytes(bytes(chunk[: len(chunk) - (len(chunk) % SAMPLE_WIDTH)]))
        return values.tolist()
    return [float(value) for value in chunk]
