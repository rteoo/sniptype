"""Source-blind-friendly CLI for the voice behavior contract.

Prints one result line per action. Uses fakes so it can run without a
microphone, a model, or the GUI.
"""

import argparse
import hashlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from trigger_index import compile_trigger_index
from voice_audio import VoiceAudioError
from voice_dispatch import MODE_COMMAND, MODE_DICTATION
from voice_models import VoiceModelError, download_model
from voice_runtime import FakeAsrBackend
from voice_support import VoiceController, VoiceTarget


class ImmediateRunner:
    def start(self, fn, *args, name=None):
        fn(*args)


class FakeCapture:
    def __init__(self, samples=None, overflow=False):
        self.samples = list(samples or [0.1])
        self.overflow = overflow

    def start(self):
        return None

    def stop(self):
        return list(self.samples), self.overflow


class _FakeResponse:
    def __init__(self, data):
        self._data = data
        self._offset = 0

    def read(self, size=-1):
        if self._offset >= len(self._data):
            return b""
        chunk = self._data[self._offset:] if size < 0 else self._data[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _controller(transcript, form=None):
    inserted = []
    expanded = []
    forms = []
    backend = FakeAsrBackend(transcript=transcript)
    cache = tempfile.mkdtemp()
    model_path = os.path.join(cache, "tiny.gguf")
    with open(model_path, "wb") as handle:
        handle.write(b"fake")
    controller = VoiceController(
        {"voice_enabled": False},
        task_runner=ImmediateRunner(),
        insert_text=lambda text: inserted.append(text) or True,
        expand_trigger=lambda trigger: expanded.append(trigger) or True,
        notify=lambda message, key=None: None,
        logger=None,
        backend=backend,
        capture_factory=lambda: FakeCapture(),
        cache_dir=cache,
        download=lambda entry, cache_dir, cancel_event=None: model_path,
        capture_target=lambda: VoiceTarget("window", 1),
        restore_target=lambda target: True,
    )
    controller.bind_library(
        lambda: {"xhi": "hello"},
        lambda: compile_trigger_index({"xhi": "hello"}, set()),
    )
    if form:
        controller.register_form_target(forms.append)
    return controller, inserted, expanded, forms


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=(
        "disabled-press",
        "dictate",
        "command",
        "form",
        "cancel",
        "second-press",
        "no-match",
        "download-ok",
        "download-bad",
    ))
    parser.add_argument("--transcript", default="hello world")
    args = parser.parse_args(argv)

    if args.action == "disabled-press":
        controller, inserted, _, _ = _controller(args.transcript)
        ok = controller.handle_hotkey_press(MODE_DICTATION)
        print("ignored" if not ok else "started")
        print("inserted:" + (inserted[0] if inserted else ""))
        return 0

    if args.action == "dictate":
        controller, inserted, _, _ = _controller(args.transcript)
        controller.enable()
        controller.handle_hotkey_press(MODE_DICTATION)
        controller.handle_hotkey_release(MODE_DICTATION)
        print("inserted:" + (inserted[0] if inserted else ""))
        return 0

    if args.action == "command":
        controller, _, expanded, _ = _controller(args.transcript)
        controller.enable()
        controller.handle_hotkey_press(MODE_COMMAND)
        controller.handle_hotkey_release(MODE_COMMAND)
        print("expanded:" + (expanded[0] if expanded else "no_match"))
        return 0

    if args.action == "form":
        controller, inserted, _, forms = _controller(args.transcript, form=True)
        controller.enable()
        controller.handle_hotkey_press(MODE_DICTATION)
        controller.handle_hotkey_release(MODE_DICTATION)
        print("form:" + (forms[0] if forms else ""))
        print("inserted:" + (inserted[0] if inserted else ""))
        return 0

    if args.action == "cancel":
        controller, inserted, _, _ = _controller(args.transcript)
        controller.enable()
        controller.handle_hotkey_press(MODE_DICTATION)
        controller.cancel()
        print(controller.last_outcome or "none")
        print("inserted:" + (inserted[0] if inserted else ""))
        return 0

    if args.action == "second-press":
        controller, _, _, _ = _controller(args.transcript)
        controller.enable()
        first = controller.handle_hotkey_press(MODE_DICTATION)
        second = controller.handle_hotkey_press(MODE_DICTATION)
        print("started" if first else "ignored")
        print("ignored" if not second else "started-again")
        return 0

    if args.action == "no-match":
        controller, _, expanded, _ = _controller("not-a-trigger")
        controller.enable()
        controller.handle_hotkey_press(MODE_COMMAND)
        controller.handle_hotkey_release(MODE_COMMAND)
        print(controller.last_outcome)
        print("expanded:" + (expanded[0] if expanded else ""))
        return 0

    payload = b"fixture-model"
    digest = hashlib.sha256(payload).hexdigest()
    entry = {
        "id": "tiny-test-model",
        "profile": "balanced",
        "filename": "tiny.gguf",
        "url": "https://example.test/tiny.gguf",
        "sha256": digest,
        "size_bytes": len(payload),
        "license_id": "MIT",
        "upstream_model": "test/tiny",
    }
    cache = tempfile.mkdtemp()

    def opener(body):
        def open_url(request, timeout=None):
            return _FakeResponse(body)
        return open_url

    if args.action == "download-ok":
        download_model(entry, cache, opener=opener(payload))
        print("installed")
        return 0

    if args.action == "download-bad":
        try:
            download_model(entry, cache, opener=opener(b"tampered"))
        except VoiceModelError:
            print("rejected")
            return 0
        print("installed")
        return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
