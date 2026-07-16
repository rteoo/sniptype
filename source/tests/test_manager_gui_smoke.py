"""GUI construction smoke test.

Builds every manager tab and the notification window against a hidden Tk root
(no mainloop), catching widget-wiring bugs that the headless unit tests miss.
Skipped automatically where Tk cannot open a display (e.g. headless CI).
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import txt_xpander as tx

try:
    import tkinter as tk
    from tkinter import ttk
    _root = tk.Tk()
    _root.destroy()
    TK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False


def _make_app(base_dir):
    with open(os.path.join(base_dir, "snippets.json"), "w", encoding="utf-8") as handle:
        handle.write('{"xhi": "hello"}')
    previous_home = os.environ.get("TXT_XPANDER_HOME")
    os.environ["TXT_XPANDER_HOME"] = base_dir
    try:
        with mock.patch.object(tx, "get_runtime_base_dir", return_value=base_dir), \
                mock.patch.object(tx, "get_runtime_resource_dir",
                                  return_value=os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))):
            return tx.TextExpander()
    finally:
        if previous_home is None:
            os.environ.pop("TXT_XPANDER_HOME", None)
        else:
            os.environ["TXT_XPANDER_HOME"] = previous_home


@unittest.skipUnless(TK_AVAILABLE, "Tk display not available")
class ManagerGuiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.app = _make_app(tempfile.mkdtemp())
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_all_tabs_build(self):
        self.app._configure_manager_styles(self.root)
        frames = {name: tk.Frame(self.root) for name in
                  ("static", "dyn", "eco", "stocks", "wapp", "backups")}
        self.app._create_static_snippets_tab(frames["static"], self.root)
        self.app._create_dynamic_mappings_tab(frames["dyn"], self.root)
        self.app._create_datetime_eco_tab(frames["eco"])
        self.app._create_stocks_tab(frames["stocks"])
        self.app._create_whatsapp_tab(frames["wapp"])
        self.app._create_backups_tab(frames["backups"], self.root)
        self.root.update_idletasks()

    def test_notification_history_window_builds(self):
        self.app._open_notification_history(self.root)
        self.root.update_idletasks()


if __name__ == "__main__":
    unittest.main()
