"""The text expander remains independent of the extracted transcription app."""

import ast
import sys
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_module import sniptype
import macos_permissions


class VoiceExtractionTests(unittest.TestCase):
    def test_expander_has_no_microphone_permission_surface(self):
        self.assertFalse(hasattr(macos_permissions, "check_microphone"))
        self.assertEqual(set(macos_permissions.SETTINGS_PANE_URLS), {"input_monitoring", "accessibility"})

    def test_expander_does_not_import_or_construct_voice(self):
        tree = ast.parse((SOURCE / "sniptype.pyw").read_text(encoding="utf-8"))
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(name and name.startswith("voice_") for name in imports))
        self.assertFalse(hasattr(sniptype, "VoiceController"))
        self.assertFalse(hasattr(sniptype.Sniptype, "toggle_voice"))
        self.assertTrue(hasattr(sniptype.Sniptype, "on_press"))

    def test_expander_builds_do_not_require_transcription_runtime(self):
        for name in ("build_release.bat", "build_release_macos.sh"):
            with self.subTest(script=name):
                text = (SOURCE.parent / name).read_text(encoding="utf-8")
                self.assertNotIn("requirements-voice.txt", text)
                self.assertNotIn("--voice-runtime-probe", text)
                self.assertNotIn("NSMicrophoneUsageDescription", text)
                self.assertNotIn("--collect-all sounddevice", text)


if __name__ == "__main__":
    unittest.main()
