import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hotkey_dialog import ACTION_LABELS, ACTIONS, HotkeyDialog, HotkeyDialogController


class FakeEntry:
    def __init__(self, value):
        self.value = value
        self.focused = False

    def get(self):
        return self.value

    def focus_set(self):
        self.focused = True


class HotkeyDialogControllerTests(unittest.TestCase):
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
