import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import runtime_support
import txt_xpander as tx


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

        with mock.patch.object(runtime_support.WindowsClipboard, "get_text", staticmethod(fake_get_text)), \
                mock.patch.object(runtime_support.WindowsClipboard, "set_content", staticmethod(fake_set_content)):
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


if __name__ == "__main__":
    unittest.main()
