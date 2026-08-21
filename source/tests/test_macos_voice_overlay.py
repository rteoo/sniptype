import os
import sys
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from macos_voice_overlay import nonactivating_panel_style


class MacVoiceOverlayPolicyTests(unittest.TestCase):
    def test_panel_is_borderless_and_nonactivating(self):
        appkit = types.SimpleNamespace(
            NSWindowStyleMaskBorderless=0x01,
            NSWindowStyleMaskNonactivatingPanel=0x80,
        )
        self.assertEqual(nonactivating_panel_style(appkit), 0x81)


if __name__ == "__main__":
    unittest.main()
