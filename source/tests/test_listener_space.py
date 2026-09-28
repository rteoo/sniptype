"""The real listener callback must treat native Space as a typed " ".

pynput delivers Space as the enum member ``Key.space``, which has no ``.char``
of its own, so these tests drive ``on_press`` with real pynput key objects
instead of calling ``_handle_char(" ")`` directly.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pynput.keyboard import Key, KeyCode
from test_hotpath import make_app


class ListenerSpaceTestBase(unittest.TestCase):
    terminator_mode = False

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.app = make_app(self.tmp, {"xhi": "hello"})
        self.app.terminator_mode = self.terminator_mode
        self.app._erase_chars = mock.Mock()
        # macOS Secure Keyboard Entry would otherwise gate dispatch on CI hosts.
        self.app._secure_input_blocks_expansion = mock.Mock(return_value=False)

    def _press_text(self, text):
        for char in text:
            if char == " ":
                self.app.on_press(Key.space)
            else:
                self.app.on_press(KeyCode.from_char(char))


class ImmediateModeSpaceTests(ListenerSpaceTestBase):
    def test_space_is_buffered_as_a_space(self):
        self._press_text("ab ")
        self.assertEqual("ab ", self.app.typed_text)

    def test_trigger_does_not_fire_across_a_space(self):
        self._press_text("box hi")
        self.app._erase_chars.assert_not_called()
        self.app.task_runner.start.assert_not_called()
        self.assertEqual("box hi", self.app.typed_text)

    def test_trigger_after_a_space_still_fires(self):
        self._press_text("ok xhi")
        self.app._erase_chars.assert_called_once_with(3)
        self.app.task_runner.start.assert_called_once()
        args = self.app.task_runner.start.call_args.args
        self.assertEqual("xhi", args[1])
        self.assertEqual("", args[2])


class TerminatorModeSpaceTests(ListenerSpaceTestBase):
    terminator_mode = True

    def test_space_terminates_trigger_exactly_once(self):
        self._press_text("xhi")
        self.app.task_runner.start.assert_not_called()

        self.app.on_press(Key.space)

        self.app._erase_chars.assert_called_once_with(len("xhi") + 1)
        self.app.task_runner.start.assert_called_once()
        args = self.app.task_runner.start.call_args.args
        self.assertEqual(self.app._run_expansion, args[0])
        self.assertEqual("xhi", args[1])
        self.assertEqual(" ", args[2])
        self.assertEqual("", self.app.typed_text)

        # A second Space is plain typing, not a second expansion.
        self.app.on_press(Key.space)
        self.app.task_runner.start.assert_called_once()
        self.app._erase_chars.assert_called_once()

    def _run_dispatched_worker(self, inserted):
        self._press_text("xhi ")
        func, *worker_args = self.app.task_runner.start.call_args.args
        with mock.patch.object(self.app, "expand_snippet", return_value=inserted):
            func(*worker_args)

    def test_space_reemitted_after_successful_insertion(self):
        self._run_dispatched_worker(inserted=True)
        self.app.keyboard_controller.type.assert_called_once_with(" ")

    def test_space_not_reemitted_when_insertion_fails(self):
        self._run_dispatched_worker(inserted=False)
        self.app.keyboard_controller.type.assert_not_called()


if __name__ == "__main__":
    unittest.main()
