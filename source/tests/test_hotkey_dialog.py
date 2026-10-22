import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hotkey_dialog import ACTION_LABELS, ACTIONS, HotkeyDialog, HotkeyDialogController
from hotkey_support import capture_hotkey, display_hotkey


class FakeEntry:
    def __init__(self, value):
        self.value = value
        self.focused = False

    def get(self):
        return self.value

    def focus_set(self):
        self.focused = True


class HotkeyDialogControllerTests(unittest.TestCase):
    def test_windows_lock_bits_do_not_turn_ctrl_shift_into_alt(self):
        # Windows: CapsLock=Lock, NumLock=Mod1, ScrollLock=Mod3.
        for locks in (0, 0x2, 0x8, 0x20, 0x2 | 0x8 | 0x20):
            with self.subTest(locks=locks):
                self.assertEqual(capture_hotkey("M", 0x5 | locks, "win32"),
                                 "<ctrl>+<shift>+m")

    def test_alt_masks_and_cmd_follow_the_actual_tk_windowing_system(self):
        for system, state, expected in (
            ("win32", 0x10, "<alt>+m"),
            ("win32", 0x20000, "<alt>+m"),
            ("win32", 0x10000, "<cmd>+m"),
            ("aqua", 0x8, "<cmd>+m"),
            ("aqua", 0x10, "<alt>+m"),
            ("aqua", 0x20 | 0x40, "m"),
            ("x11", 0x10, "m"),
        ):
            with self.subTest(system=system, state=state):
                self.assertEqual(capture_hotkey("m", state, system), expected)
        self.assertEqual(capture_hotkey("m", 0, "win32", ("Super_L",)), "<cmd>+m")
        self.assertEqual(capture_hotkey("m", 0, "x11", ("Alt_L",)), "<alt>+m")
        self.assertEqual(capture_hotkey("m", 0, "x11", ("Super_L",)), "<cmd>+m")

    def test_modified_escape_and_delete_are_recordable(self):
        self.assertEqual(capture_hotkey("Escape", 0x4, "win32"), "<ctrl>+<esc>")
        self.assertEqual(capture_hotkey("Delete", 0x10, "win32"), "<alt>+<delete>")

    def test_synthetic_chord_captures_storage_and_friendly_display(self):
        chord = capture_hotkey("M", 0x4 | 0x1)
        self.assertEqual(chord, "<ctrl>+<shift>+m")
        self.assertEqual(display_hotkey(chord), "Ctrl+Shift+M")
        controller, _controls = self._controller({"open_manager": chord})
        self.assertTrue(controller.save())
        self.assertEqual(controller.result["open_manager"], chord)
        self.assertIsNone(capture_hotkey("Shift_L", 0x1))
        self.assertIsNone(capture_hotkey("Tab", 0))
        self.assertEqual(capture_hotkey("BackSpace", 0), "")

    def _controller(self, values):
        controls = {action: FakeEntry(values.get(action, "")) for action in ACTIONS}
        return HotkeyDialogController(values, controls), controls

    def test_save_returns_normalized_bindings_and_preserves_disabled_actions(self):
        controller, _controls = self._controller({
            "open_manager": " <CTRL>+<SHIFT>+M ",
            "edit_last": "",
            "toggle_enabled": "<alt>+<shift>+e",
        })

        self.assertTrue(controller.save())
        self.assertEqual("<ctrl>+<shift>+m", controller.result["open_manager"])
        self.assertIsNone(controller.result["edit_last"])
        self.assertEqual("<alt>+<shift>+e", controller.result["toggle_enabled"])
        self.assertIsNone(controller.error)

    def test_invalid_binding_keeps_dialog_open_and_focuses_offending_action(self):
        for old_test, values, invalid_action, fragment, unfocused in (
            ("test_invalid_binding_keeps_dialog_open_and_focuses_offending_action",
             {"open_manager": "m"}, "open_manager", ACTION_LABELS["open_manager"], ()),
            ("test_duplicate_binding_focuses_the_second_action",
             {"open_manager": "<ctrl>+m", "edit_last": "<CTRL>+M"},
             "edit_last", "duplicates", ("open_manager",)),
        ):
            with self.subTest(old_test):
                controller, controls = self._controller(values)

                self.assertFalse(controller.save())
                self.assertIsNone(controller.result)
                self.assertEqual(invalid_action, controller.invalid_action)
                self.assertTrue(controls[invalid_action].focused)
                for action in unfocused:
                    self.assertFalse(controls[action].focused)
                self.assertIn(fragment, controller.error)

    def test_cancel_discards_a_previous_save(self):
        controller, _controls = self._controller({"open_manager": "<ctrl>+m"})
        self.assertTrue(controller.save())
        controller.cancel()
        self.assertIsNone(controller.result)
        self.assertIsNone(controller.error)


class HotkeyDialogWindowTests(unittest.TestCase):
    def test_close_explicitly_returns_focus_after_destroying_the_owned_prompt(self):
        dialog = HotkeyDialog.__new__(HotkeyDialog)
        dialog.window = mock.Mock()
        dialog._opener = mock.Mock()
        dialog._opener.winfo_exists.return_value = True
        calls = mock.Mock()
        calls.attach_mock(dialog.window, "window")
        calls.attach_mock(dialog._opener, "opener")
        dialog._close()
        self.assertEqual(calls.mock_calls, [
            mock.call.window.grab_release(), mock.call.window.destroy(),
            mock.call.opener.winfo_exists(), mock.call.opener.focus_force(),
        ])

    def test_run_does_not_grab_the_shared_tk_root(self):
        window = mock.Mock(spec=["focus_force", "wait_window"])
        first_control = mock.Mock()
        dialog = HotkeyDialog.__new__(HotkeyDialog)
        dialog._owner_thread = threading.current_thread()
        dialog.window = window
        dialog._controls = {"open_manager": first_control}
        dialog.controller = mock.Mock(result=None)

        self.assertIsNone(dialog.run())

        window.focus_force.assert_called_once_with()
        first_control.focus_set.assert_called_once_with()
        window.wait_window.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
