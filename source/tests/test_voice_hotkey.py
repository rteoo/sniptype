import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_hotkey import (
    DEFAULT_COMMAND_HOTKEY,
    DEFAULT_DICTATION_HOTKEY,
    MODE_COMMAND,
    MODE_DICTATION,
    VoiceHotkeyMonitor,
    chord_is_held,
    parse_chord,
)
from voice_settings import resolve_voice_settings


class ParseChordTests(unittest.TestCase):
    def test_default_chords_parse(self):
        dictation = parse_chord(DEFAULT_DICTATION_HOTKEY)
        command = parse_chord(DEFAULT_COMMAND_HOTKEY)
        self.assertEqual(dictation.modifiers, frozenset({"ctrl", "alt"}))
        self.assertEqual(dictation.key, "space")
        self.assertEqual(command.modifiers, frozenset({"ctrl", "alt", "shift"}))

    def test_rejects_empty_and_modifier_only(self):
        for spec in ("", "space", "ctrl", "ctrl+alt"):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    parse_chord(spec)

    def test_unknown_modifier_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_chord("hyper+space")


class ChordMatchTests(unittest.TestCase):
    def test_requires_every_modifier(self):
        chord = parse_chord("ctrl+alt+space")
        self.assertFalse(chord_is_held(chord, {"ctrl"}, "space"))
        self.assertTrue(chord_is_held(chord, {"ctrl", "alt"}, "space"))
        self.assertFalse(chord_is_held(chord, {"ctrl", "alt"}, "enter"))


class MonitorTests(unittest.TestCase):
    def test_press_and_release_report_the_matching_mode(self):
        events = []
        monitor = VoiceHotkeyMonitor(
            parse_chord("ctrl+alt+space"),
            parse_chord("ctrl+alt+shift+space"),
            on_press=lambda mode: events.append(("press", mode)),
            on_release=lambda mode: events.append(("release", mode)),
        )
        from pynput.keyboard import Key

        monitor._handle_press(Key.ctrl)
        monitor._handle_press(Key.alt)
        monitor._handle_press(Key.space)
        monitor._handle_release(Key.space)
        self.assertEqual(
            events,
            [("press", MODE_DICTATION), ("release", MODE_DICTATION)],
        )

    def test_command_chord_wins_over_the_shorter_dictation_chord(self):
        events = []
        monitor = VoiceHotkeyMonitor(
            parse_chord("ctrl+alt+space"),
            parse_chord("ctrl+alt+shift+space"),
            on_press=lambda mode: events.append(mode),
            on_release=lambda mode: None,
        )
        from pynput.keyboard import Key

        monitor._handle_press(Key.ctrl)
        monitor._handle_press(Key.alt)
        monitor._handle_press(Key.shift)
        monitor._handle_press(Key.space)
        self.assertEqual(events, [MODE_COMMAND])

    def test_dictation_chord_can_be_more_specific_than_command(self):
        events = []
        monitor = VoiceHotkeyMonitor(
            parse_chord("ctrl+alt+shift+space"),
            parse_chord("ctrl+alt+space"),
            on_press=lambda mode: events.append(mode),
            on_release=lambda mode: None,
        )
        from pynput.keyboard import Key

        monitor._handle_press(Key.ctrl)
        monitor._handle_press(Key.alt)
        monitor._handle_press(Key.shift)
        monitor._handle_press(Key.space)
        self.assertEqual(events, [MODE_DICTATION])

    def test_auto_repeat_does_not_rearm_while_held(self):
        events = []
        monitor = VoiceHotkeyMonitor(
            parse_chord("ctrl+alt+space"),
            parse_chord("ctrl+alt+shift+space"),
            on_press=lambda mode: events.append("press"),
            on_release=lambda mode: events.append("release"),
        )
        from pynput.keyboard import Key

        monitor._handle_press(Key.ctrl)
        monitor._handle_press(Key.alt)
        monitor._handle_press(Key.space)
        monitor._handle_press(Key.space)
        self.assertEqual(events, ["press"])


class SettingsTests(unittest.TestCase):
    def test_defaults_are_off_and_balanced(self):
        resolved = resolve_voice_settings({})
        self.assertFalse(resolved.enabled)
        self.assertEqual(resolved.profile, "balanced")
        self.assertEqual(resolved.hotkey, DEFAULT_DICTATION_HOTKEY)

    def test_bad_profile_and_hotkey_fall_back(self):
        warnings = []
        resolved = resolve_voice_settings(
            {"voice_profile": "turbo", "voice_hotkey": "space"},
            warnings,
        )
        self.assertEqual(resolved.profile, "balanced")
        self.assertEqual(resolved.hotkey, DEFAULT_DICTATION_HOTKEY)
        self.assertEqual(len(warnings), 2)

    def test_colliding_hotkeys_are_separated(self):
        warnings = []
        resolved = resolve_voice_settings(
            {
                "voice_hotkey": "ctrl+alt+space",
                "voice_command_hotkey": "ctrl+alt+space",
            },
            warnings,
        )
        self.assertNotEqual(resolved.hotkey, resolved.command_hotkey)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
