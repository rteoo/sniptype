import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clipboard_support
import runtime_support
from app_module import txt_xpander as tx  # .pyw is not importable off Windows


def make_app(base_dir, snippets):
    """Construct a TextExpander with keyboard/task side effects mocked out."""
    with open(os.path.join(base_dir, "snippets.json"), "w", encoding="utf-8") as handle:
        json.dump(snippets, handle)
    previous_home = os.environ.get("TXT_XPANDER_HOME")
    os.environ["TXT_XPANDER_HOME"] = base_dir
    try:
        with mock.patch.object(tx, "get_runtime_base_dir", return_value=base_dir), \
                mock.patch.object(tx, "get_runtime_resource_dir", return_value=base_dir):
            app = tx.TextExpander()
    finally:
        if previous_home is None:
            os.environ.pop("TXT_XPANDER_HOME", None)
        else:
            os.environ["TXT_XPANDER_HOME"] = previous_home
    app.keyboard_controller = mock.Mock()
    app.task_runner = mock.Mock()
    app.text_inserter = mock.Mock()
    return app


class ImmediateModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xhi": "hello"})

    def _type(self, text):
        for char in text:
            self.app._handle_char(char)

    def test_direct_trigger_dispatches_to_worker(self):
        self._type("xhi")
        self.app.task_runner.start.assert_called_once()
        args = self.app.task_runner.start.call_args
        self.assertEqual(args.args[0], self.app._run_expansion)
        self.assertEqual(args.args[1], "xhi")
        self.assertEqual(args.args[2], "")  # no terminator appended
        self.assertEqual(self.app.typed_text, "")

    def test_no_dispatch_without_match(self):
        self._type("zzz")
        self.app.task_runner.start.assert_not_called()


class TerminatorModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xhi": "hello"})
        self.app.terminator_mode = True

    def _type(self, text):
        for char in text:
            self.app._handle_char(char)

    def test_no_expansion_until_terminator(self):
        self._type("xhi")
        self.app.task_runner.start.assert_not_called()

    def test_expands_on_terminator_and_reemits_it(self):
        self._type("xhi ")
        self.app.task_runner.start.assert_called_once()
        args = self.app.task_runner.start.call_args
        self.assertEqual(args.args[1], "xhi")
        self.assertEqual(args.args[2], " ")  # terminator re-typed after expansion


class ListenerResilienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xhi": "hello"})

    def test_raising_callable_does_not_propagate(self):
        def boom():
            raise RuntimeError("callable exploded")

        self.app.snippets["xboom"] = boom
        self.app.refresh_runtime_indexes()
        # Must not raise: the worker guard swallows and logs it.
        self.app._run_expansion("xboom")

    def test_buffer_sized_for_long_composed_dynamic_trigger(self):
        long_item = "a_very_long_mapping_item_name"
        self.app.snippets["_codes"] = {"__prefix__": "cc", "" + long_item: "value"}
        self.app.refresh_runtime_indexes()
        composed_len = len("cc") + len(long_item)
        self.assertGreaterEqual(self.app.max_trigger_length, composed_len + tx.TRIGGER_BUFFER_MARGIN)


class TerminatorReemitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xhi": "hello"})

    def test_terminator_not_reemitted_when_nothing_inserted(self):
        with mock.patch.object(self.app, "expand_snippet", return_value=False):
            self.app._run_expansion("xhi", append_text=" ")
        self.app.keyboard_controller.type.assert_not_called()

    def test_terminator_reemitted_when_inserted(self):
        with mock.patch.object(self.app, "expand_snippet", return_value=True):
            self.app._run_expansion("xhi", append_text=" ")
        self.app.keyboard_controller.type.assert_called_once_with(" ")

    def test_cancelled_form_dialog_inserts_nothing(self):
        """A cancelled form dialog must leave no text and no terminator."""
        self.app.snippets["xform"] = "Olá %%nome%%"
        self.app.refresh_runtime_indexes()
        with mock.patch.object(self.app, "_show_form_dialog", return_value=None) as dialog:
            self.app._run_expansion("xform", append_text=" ")
        dialog.assert_called_once_with(["nome"])
        self.app.text_inserter.insert_text.assert_not_called()
        self.app.keyboard_controller.type.assert_not_called()


class ClipboardSerializationTests(unittest.TestCase):
    def test_concurrent_pastes_do_not_interleave(self):
        events = []

        def fake_get_text():
            return "orig"

        def fake_set_content(value):
            events.append(("set", value))
            time.sleep(0.02)
            events.append(("done", value))
            return True

        with mock.patch.object(runtime_support.Clipboard, "get_text", fake_get_text), \
                mock.patch.object(runtime_support.Clipboard, "set_content", fake_set_content):
            inserter = runtime_support.TextInserter(mock.Mock(), restore_delay=0.0)
            threads = [
                threading.Thread(target=inserter.insert_text, args=(f"payload{i}",))
                for i in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        # Each paste's set/done pair must complete before the next paste's set,
        # proving the clipboard critical section is serialized.
        self.assertEqual(len(events), 4)
        for i in range(0, len(events), 2):
            self.assertEqual(events[i][0], "set")
            self.assertEqual(events[i + 1][0], "done")
            self.assertEqual(events[i][1], events[i + 1][1])


class FakeClipboard:
    """In-memory clipboard that mirrors the Windows backend's CRLF storage."""

    def __init__(self, initial=None):
        self.value = initial
        self.writes = []

    def get_text(self):
        return self.value

    def set_content(self, value):
        text = runtime_support.extract_plain_text(value)
        self.writes.append(text)
        self.value = clipboard_support.normalize_clipboard_newlines(text)
        return True


class TypedFallbackSafetyTests(unittest.TestCase):
    """A failed paste must never inject Enter keys."""

    def test_multiline_snippet_is_never_typed(self):
        # pynput types "\n" as a real Enter: in a terminal that executes the
        # line, in a chat app it sends the message. The user's xcattle snippet
        # ("cd ~/Projects/...\nuv run ...") would run a command mid-insert.
        clipboard = FakeClipboard(initial="orig")
        keyboard = mock.Mock()
        notify = mock.Mock()
        snippet = "cd ~/Projects/cattle-auction/\nuv run python main.py"

        with mock.patch.object(runtime_support, "Clipboard", clipboard):
            inserter = runtime_support.TextInserter(keyboard, notify=notify)
            with mock.patch.object(inserter, "_paste_value", return_value=False):
                self.assertFalse(inserter.insert_text(snippet))

        keyboard.type.assert_not_called()
        # Payload left where the user can retrieve it with a manual Ctrl+V.
        self.assertEqual(clipboard.writes[-1], snippet)
        notify.assert_called_once()
        self.assertIn("Ctrl+V", notify.call_args.args[0])

    def test_single_line_snippet_still_falls_back_to_typing(self):
        clipboard = FakeClipboard(initial="orig")
        keyboard = mock.Mock()

        with mock.patch.object(runtime_support, "Clipboard", clipboard):
            inserter = runtime_support.TextInserter(keyboard)
            with mock.patch.object(inserter, "_paste_value", return_value=False):
                self.assertTrue(inserter.insert_text("bom dia"))

        keyboard.type.assert_called_once_with("bom dia")


class ClipboardCoWriterTests(unittest.TestCase):
    def _insert(self, clipboard, snippet):
        logger = mock.Mock()
        with mock.patch.object(runtime_support, "Clipboard", clipboard):
            inserter = runtime_support.TextInserter(
                mock.Mock(), logger=logger, restore_delay=0.0
            )
            with mock.patch.object(inserter, "_send_paste_shortcut"):
                inserter.insert_text(snippet)
        return logger

    def test_third_party_overwrite_is_logged(self):
        """The evidence that distinguishes a co-writer from a slow target."""
        clipboard = FakeClipboard(initial="orig")

        def hostile_set(value):
            # A sync agent wins the clipboard right after our write.
            clipboard.writes.append(runtime_support.extract_plain_text(value))
            clipboard.value = "texto de outra maquina"
            return True

        clipboard.set_content = hostile_set
        logger = self._insert(clipboard, "bom dia")

        warnings = " ".join(str(call.args[0]) for call in logger.warning.call_args_list)
        self.assertIn("sobrescrita por outro programa", warnings)

    def test_normal_paste_logs_no_warning(self):
        logger = self._insert(FakeClipboard(initial="orig"), "bom dia")
        logger.warning.assert_not_called()

    def test_single_line_restores_previous_clipboard(self):
        clipboard = FakeClipboard(initial="orig")
        self._insert(clipboard, "bom dia")
        self.assertEqual(clipboard.value, "orig")

    def test_multiline_does_not_restore(self):
        # Deliberate: multi-line has never restored (the old CRLF comparison
        # skipped it), and enabling it now would expose exactly the snippets
        # under investigation to the restore race.
        clipboard = FakeClipboard(initial="orig")
        self._insert(clipboard, "linha um\nlinha dois")
        self.assertEqual(clipboard.value, "linha um\r\nlinha dois")


class SlowRefRoutingTests(unittest.TestCase):
    """A snippet referencing a slow dynamic trigger must take the async path."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "dynamic_snippets.json"), "w", encoding="utf-8") as handle:
            json.dump({"xdolar": {"provider": "bcb", "method": "dolar",
                                  "category": "economy", "slow": True}}, handle)
        self.app = make_app(self.tmp, {
            "xreport": "Dólar: %%xdolar%%",
            "xplain": "texto simples",
        })

    def test_snippet_referencing_slow_trigger_uses_slow_path(self):
        with mock.patch.object(self.app, "run_slow_snippet", return_value=True) as slow, \
                mock.patch.object(self.app, "expand_snippet", return_value=True) as fast:
            self.app._run_expansion("xreport")
        slow.assert_called_once_with("xreport")
        fast.assert_not_called()

    def test_plain_snippet_still_uses_fast_path(self):
        with mock.patch.object(self.app, "run_slow_snippet", return_value=True) as slow, \
                mock.patch.object(self.app, "expand_snippet", return_value=True) as fast:
            self.app._run_expansion("xplain")
        fast.assert_called_once_with("xplain")
        slow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
