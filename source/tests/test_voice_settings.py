import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_settings import resolve_voice_settings, voice_settings_payload


class VoiceSettingsTests(unittest.TestCase):
    def test_missing_file_shape_is_off(self):
        settings = resolve_voice_settings({})
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.profile, "balanced")
        self.assertEqual(settings.hotkey, "ctrl+alt+space")
        self.assertEqual(settings.command_hotkey, "ctrl+alt+shift+space")

    def test_warnings_for_bad_values(self):
        notes = []
        settings = resolve_voice_settings(
            {
                "voice_enabled": "yes",
                "voice_profile": "huge",
                "voice_language": "fr",
                "voice_hotkey": "space",
                "voice_command_hotkey": "space",
            },
            warnings=notes,
        )
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.profile, "balanced")
        self.assertEqual(settings.language, "auto")
        self.assertGreaterEqual(len(notes), 3)

    def test_payload_roundtrip_keys(self):
        settings = resolve_voice_settings({"voice_enabled": True, "voice_profile": "accuracy"})
        payload = voice_settings_payload(settings)
        self.assertTrue(payload["voice_enabled"])
        self.assertEqual(payload["voice_profile"], "accuracy")


if __name__ == "__main__":
    unittest.main()
