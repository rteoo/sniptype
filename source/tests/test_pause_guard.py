"""Pausing expansion must leave typed text untouched.

These drive the real ``Sniptype.on_press`` with real pynput key objects; only
the erase, the worker runner, and the GUI/tray seams are mocked, so nothing is
injected into the live session.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_module import sniptype as tx  # .pyw is not importable off Windows
from pynput.keyboard import Key, KeyCode
from test_hotpath import make_app


class PauseGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = make_app(self.tmp, {"xhi": "hello"})
        self.app._erase_chars = mock.Mock()
        self.app._secure_input_blocks_expansion = mock.Mock(return_value=False)
        self.app.gui = mock.Mock()
        self.app.icon = None
        self.app.notify_status = mock.Mock()
        self.app.hotkey_router = tx.HotkeyRouter(
            {"toggle_enabled": "<ctrl>+<shift>+e"},
            self.app._dispatch_hotkey_action,
        )

    def _type(self, text):
        for char in text:
            self.app.on_press(KeyCode.from_char(char))
            self.app.on_release(KeyCode.from_char(char))

    def _expansion_starts(self):
        return [
            call for call in self.app.task_runner.start.call_args_list
            if call.args and call.args[0] == self.app._run_expansion
        ]

    def test_paused_typing_neither_erases_nor_dispatches(self):
        self.app.enabled = False

        self._type("xhi")

        self.app._erase_chars.assert_not_called()
        self.app.task_runner.start.assert_not_called()
        self.app.keyboard_controller.press.assert_not_called()

    def test_toggle_hotkey_still_reenables_while_paused(self):
        self.app.enabled = False

        self.app.on_press(Key.ctrl)
        self.app.on_press(Key.shift)
        self.app.on_press(KeyCode.from_char("e"))

        self.app.task_runner.start.assert_called_once()
        call = self.app.task_runner.start.call_args
        self.assertEqual(self.app._run_hotkey_action, call.args[0])
        self.assertEqual("toggle_enabled", call.args[1])
        self.app._run_hotkey_action("toggle_enabled")
        self.app.gui.submit.assert_called_once_with(self.app._toggle_enabled_from_hotkey)
        self.app._toggle_enabled_from_hotkey()
        self.assertTrue(self.app.enabled)
        self.app._erase_chars.assert_not_called()

    def test_trigger_half_typed_while_paused_does_not_fire_after_resume(self):
        self.app.toggle_enabled(None, None)
        self.assertFalse(self.app.enabled)
        self._type("xh")
        self.app.toggle_enabled(None, None)
        self.assertTrue(self.app.enabled)

        self._type("i")

        self.app._erase_chars.assert_not_called()
        self.assertEqual([], self._expansion_starts())

        self._type("xhi")

        self.app._erase_chars.assert_called_once_with(3)
        starts = self._expansion_starts()
        self.assertEqual(1, len(starts))
        self.assertEqual("xhi", starts[0].args[1])

    def test_trigger_half_typed_before_pause_does_not_fire_after_resume(self):
        self._type("xh")
        self.app.toggle_enabled(None, None)
        self.app.toggle_enabled(None, None)
        self.assertTrue(self.app.enabled)

        self._type("i")

        self.app._erase_chars.assert_not_called()
        self.assertEqual([], self._expansion_starts())


if __name__ == "__main__":
    unittest.main()
