import os
import subprocess
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_indicator import VISIBLE_STATES, indicator_content


class VoiceIndicatorContentTests(unittest.TestCase):
    def test_visible_states_have_copy(self):
        for state in VISIBLE_STATES:
            with self.subTest(state=state):
                self.assertIsNotNone(indicator_content(state))

    def test_recording_explains_release_and_cancel(self):
        title, detail, accent = indicator_content("recording", "dictation")
        self.assertEqual(title, "Ouvindo…")
        self.assertIn("Solte para transcrever", detail)
        self.assertIn("Esc para cancelar", detail)
        self.assertEqual(accent, "warning")

    def test_command_mode_is_distinct(self):
        title, detail, _accent = indicator_content("recording", "command")
        self.assertIn("comando", title)
        self.assertIn("Solte para executar", detail)

    def test_idle_is_hidden(self):
        self.assertIsNone(indicator_content("idle"))
        self.assertIsNone(indicator_content("unavailable"))


class VoiceIndicatorGuiSmokeTests(unittest.TestCase):
    def test_overlay_shows_and_hides_in_an_isolated_tk_process(self):
        script = textwrap.dedent(
            """
            import tkinter as tk
            from platform_support import current_os
            from voice_indicator import (
                VoiceStatusIndicator,
                _GWL_EXSTYLE,
                _WS_EX_NOACTIVATE,
                _windows_user32,
            )

            root = tk.Tk()
            root.withdraw()
            indicator = VoiceStatusIndicator(root)
            indicator.update("recording", "dictation")
            root.update()
            assert indicator.window.state() == "normal"
            assert indicator.title_label.cget("text") == "Ouvindo…"
            if current_os() == "windows":
                user32 = _windows_user32()
                widget_hwnd = indicator.window.winfo_id()
                hwnd = user32.GetParent(widget_hwnd) or widget_hwnd
                assert user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_NOACTIVATE
            indicator.update("idle")
            root.update()
            assert indicator.window.state() == "withdrawn"
            root.destroy()
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
