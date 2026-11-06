import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pynput.keyboard import Key, KeyCode

from hotkey_support import ACTIONS, HotkeyRouter, dom_hotkey, normalize_hotkeys


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


class DomHotkeyTests(unittest.TestCase):
    """The manager window's key events become the same stored syntax as the Tk dialog's."""

    def test_letters_and_digits_come_from_the_physical_key(self):
        self.assertEqual("<ctrl>+<shift>+m", dom_hotkey("M", "KeyM", ctrl=True, shift=True))
        self.assertEqual("<alt>+1", dom_hotkey("!", "Digit1", alt=True))
        self.assertEqual("<cmd>+e", dom_hotkey("e", "KeyE", meta=True))

    def test_named_and_function_keys(self):
        self.assertEqual("<ctrl>+<page_up>", dom_hotkey("PageUp", "PageUp", ctrl=True))
        self.assertEqual("<f8>", dom_hotkey("F8", "F8"))
        self.assertEqual("<ctrl>+<space>", dom_hotkey(" ", "Space", ctrl=True))

    def test_modifiers_alone_and_tab_are_ignored_and_backspace_clears(self):
        for key in ("Control", "Shift", "Alt", "Meta", "Tab"):
            self.assertIsNone(dom_hotkey(key, key + "Left", ctrl=key == "Control"))
        self.assertEqual("", dom_hotkey("Backspace", "Backspace"))
        self.assertEqual("", dom_hotkey("Delete", "Delete"))
        self.assertEqual("<ctrl>+<delete>", dom_hotkey("Delete", "Delete", ctrl=True))

    def test_what_it_stores_passes_normalization(self):
        binding = dom_hotkey("M", "KeyM", ctrl=True, shift=True)
        bindings, invalid = normalize_hotkeys({"open_manager": binding})
        self.assertEqual({}, invalid)
        self.assertEqual(binding, bindings["open_manager"])


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

    def test_named_keys_fire_as_the_listener_reports_them(self):
        actions = []
        router = HotkeyRouter({"toggle_enabled": "<ctrl>+<f8>", "edit_last": "<alt>+<page_up>"}, actions.append)
        router.press(Key.ctrl_l)
        self.assertTrue(router.press(Key.f8))
        router.release(Key.f8)
        router.release(Key.ctrl_l)
        router.press(Key.alt_l)
        self.assertTrue(router.press(Key.page_up))
        self.assertEqual(["toggle_enabled", "edit_last"], actions)

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
