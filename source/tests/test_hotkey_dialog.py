import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hotkey_dialog import ACTION_LABELS, ACTIONS, HotkeyDialogController


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
        controller, controls = self._controller({"open_manager": "m"})

        self.assertFalse(controller.save())
        self.assertIsNone(controller.result)
        self.assertEqual("open_manager", controller.invalid_action)
        self.assertTrue(controls["open_manager"].focused)
        self.assertIn(ACTION_LABELS["open_manager"], controller.error)

    def test_duplicate_binding_focuses_the_second_action(self):
        controller, controls = self._controller({
            "open_manager": "<ctrl>+m",
            "edit_last": "<CTRL>+M",
        })

        self.assertFalse(controller.save())
        self.assertEqual("edit_last", controller.invalid_action)
        self.assertFalse(controls["open_manager"].focused)
        self.assertTrue(controls["edit_last"].focused)
        self.assertIn("duplicates", controller.error)

    def test_cancel_discards_a_previous_save(self):
        controller, _controls = self._controller({"open_manager": "<ctrl>+m"})
        self.assertTrue(controller.save())
        controller.cancel()
        self.assertIsNone(controller.result)
        self.assertIsNone(controller.error)

    def test_controller_accepts_injected_normalizer_for_a_tk_free_seam(self):
        normalizer = mock.Mock(return_value=({action: None for action in ACTIONS}, {}))
        controls = {action: FakeEntry("value") for action in ACTIONS}
        controller = HotkeyDialogController({}, controls, normalizer=normalizer)

        self.assertTrue(controller.save())
        normalizer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
