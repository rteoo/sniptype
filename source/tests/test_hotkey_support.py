import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pynput.keyboard import Key, KeyCode

from hotkey_support import ACTIONS, HotkeyRouter, normalize_hotkeys


class NormalizeHotkeysTests(unittest.TestCase):
    def test_missing_configuration_disables_every_action(self):
        bindings, invalid = normalize_hotkeys(None)
        self.assertEqual({action: None for action in ACTIONS}, bindings)
        self.assertEqual({}, invalid)

    def test_valid_bindings_are_normalized_and_unknown_actions_ignored(self):
        bindings, invalid = normalize_hotkeys({
            "open_manager": "  <CTRL>+<SHIFT>+M  ",
            "edit_last": "<alt>+<shift>+e",
            "future_action": "<ctrl>+f",
        })
        self.assertEqual("<ctrl>+<shift>+m", bindings["open_manager"])
        self.assertEqual("<alt>+<shift>+e", bindings["edit_last"])
        self.assertIsNone(bindings["toggle_enabled"])
        self.assertEqual({}, invalid)

    def test_rejects_unmodified_printable_modifier_only_and_duplicates(self):
        bindings, invalid = normalize_hotkeys({
            "open_manager": "m",
            "edit_last": "<ctrl>+<alt>",
            "toggle_enabled": "<ctrl>+m",
        })
        self.assertIsNone(bindings["open_manager"])
        self.assertIsNone(bindings["edit_last"])
        self.assertEqual("<ctrl>+m", bindings["toggle_enabled"])
        self.assertEqual({"open_manager", "edit_last"}, set(invalid))

        bindings, invalid = normalize_hotkeys({
            "open_manager": "<ctrl>+m",
            "edit_last": "<CTRL>+M",
        })
        self.assertEqual("<ctrl>+m", bindings["open_manager"])
        self.assertIsNone(bindings["edit_last"])
        self.assertIn("edit_last", invalid)

    def test_wrong_root_and_unparseable_values_are_reported(self):
        bindings, invalid = normalize_hotkeys("<ctrl>+m")
        self.assertEqual({action: None for action in ACTIONS}, bindings)
        self.assertIn("hotkeys", invalid)

        bindings, invalid = normalize_hotkeys({"open_manager": "<not-a-key>+m"})
        self.assertIsNone(bindings["open_manager"])
        self.assertIn("open_manager", invalid)

    def test_rejects_ctrl_alt_printable_chords_that_collide_with_altgr(self):
        bindings, invalid = normalize_hotkeys({
            "open_manager": "<ctrl>+<alt>+m",
            "edit_last": "<ctrl>+<shift>+m",
        })

        self.assertIsNone(bindings["open_manager"])
        self.assertIn("open_manager", invalid)
        self.assertEqual("<ctrl>+<shift>+m", bindings["edit_last"])


class HotkeyRouterTests(unittest.TestCase):
    def setUp(self):
        self.actions = []
        self.router = HotkeyRouter(
            {"open_manager": "<ctrl>+<shift>+m"},
            self.actions.append,
        )

    def test_dispatches_once_and_consumes_repeated_final_key(self):
        self.assertFalse(self.router.press(Key.ctrl))
        self.assertFalse(self.router.press(Key.shift))
        self.assertTrue(self.router.press(KeyCode.from_char("m")))
        self.assertTrue(self.router.press(KeyCode.from_char("m")))
        self.assertEqual(["open_manager"], self.actions)

        self.router.release(KeyCode.from_char("m"))
        self.assertTrue(self.router.press(KeyCode.from_char("m")))
        self.assertEqual(["open_manager", "open_manager"], self.actions)

    def test_modifier_order_does_not_matter(self):
        self.router.press(Key.shift)
        self.router.press(Key.ctrl)
        self.assertTrue(self.router.press(KeyCode.from_char("M")))
        self.assertEqual(["open_manager"], self.actions)

    def test_unrelated_key_is_not_consumed(self):
        self.router.press(Key.ctrl)
        self.router.press(Key.shift)
        self.assertFalse(self.router.press(KeyCode.from_char("x")))
        self.assertEqual([], self.actions)

    def test_unrelated_key_is_not_consumed_while_chord_remains_held(self):
        self.router.press(Key.ctrl)
        self.router.press(Key.shift)
        self.assertTrue(self.router.press(KeyCode.from_char("m")))
        self.assertFalse(self.router.press(KeyCode.from_char("x")))
        self.assertEqual(["open_manager"], self.actions)

    def test_release_resets_chord_state(self):
        self.router.press(Key.ctrl)
        self.router.press(Key.shift)
        self.router.release(Key.ctrl)
        self.assertFalse(self.router.press(KeyCode.from_char("m")))
        self.assertEqual([], self.actions)


if __name__ == "__main__":
    unittest.main()
