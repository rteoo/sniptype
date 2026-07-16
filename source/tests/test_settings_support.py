import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from settings_support import load_settings, save_settings


class SettingsSupportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "settings.json")

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_settings(self.path), {})

    def test_load_invalid_returns_empty(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        self.assertEqual(load_settings(self.path), {})

    def test_load_non_object_returns_empty(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("[1, 2]")
        self.assertEqual(load_settings(self.path), {})

    def test_save_and_load_roundtrip(self):
        self.assertTrue(save_settings(self.path, {"mirror_dir": "D:/cloud"}))
        self.assertEqual(load_settings(self.path), {"mirror_dir": "D:/cloud"})


if __name__ == "__main__":
    unittest.main()
