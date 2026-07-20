"""GUI construction smoke test.

Builds every manager tab and the notification window on the app's shared Tk
root, driven through the GUI thread exactly the way the app drives it. Catches
widget-wiring bugs that the headless unit tests miss. Skipped automatically
where Tk cannot open a display (e.g. headless CI).
"""

import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import txt_xpander as tx
from gui_thread import GuiThread

try:
    import tkinter as tk
    from tkinter import ttk
    _probe = GuiThread()
    _probe.ensure_started()
    _probe.stop()
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


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


@unittest.skipUnless(TK_AVAILABLE, "Tk display not available")
class ManagerGuiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.app = _make_app(tempfile.mkdtemp())
        self.app.gui.ensure_started()

    def tearDown(self):
        self.app.gui.stop()

    def _on_gui(self, func):
        """Run func(root) on the GUI thread, propagating assertion failures."""
        return self.app.gui.call(func, timeout=30)

    def test_all_tabs_build(self):
        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            self.app._configure_manager_styles(root)
            frames = {name: tk.Frame(root) for name in
                      ("static", "dyn", "builtin", "backups")}
            self.app._create_static_snippets_tab(frames["static"], root)
            self.app._create_dynamic_mappings_tab(frames["dyn"], root)
            self.app._create_dynamic_snippets_tab(frames["builtin"], root)
            self.app._create_backups_tab(frames["backups"], root)
            root.update_idletasks()

        self._on_gui(build)

    def test_dynamic_mappings_tab_lists_custom_types(self):
        self.app.snippets["_mail_codes"] = {"__prefix__": "mail", "team": "team@x.com"}

        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_dynamic_mappings_tab(frame, root)
            root.update_idletasks()
            listboxes = [w for w in _descendants(frame) if isinstance(w, tk.Listbox)]
            self.assertTrue(listboxes, "expected a types listbox")
            return listboxes[0].get(0, tk.END)

        labels = self._on_gui(build)
        self.assertIn("MAIL", labels)
        self.assertIn("CPF", labels)

    def test_notification_history_window_builds(self):
        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            self.app._open_notification_history(root)
            root.update_idletasks()

        self._on_gui(build)

    def test_manager_window_is_tracked_and_reused(self):
        self.app.gui.call(self.app._show_manager_window, timeout=30)
        first = self.app.manager_window
        self.assertIsNotNone(first)

        self.app.gui.call(self.app._show_manager_window, timeout=30)
        self.assertIs(self.app.manager_window, first, "second open should reuse the window")

        def close(_root):
            first.protocol  # window still alive
            self.app.manager_window = None
            first.destroy()

        self.app.gui.call(close, timeout=30)


@unittest.skipUnless(TK_AVAILABLE, "Tk display not available")
class GuiThreadTests(unittest.TestCase):
    def setUp(self):
        self.gui = GuiThread()
        self.gui.ensure_started()

    def tearDown(self):
        self.gui.stop()

    def test_call_runs_on_gui_thread_and_returns_value(self):
        caller_thread = threading.current_thread()
        seen = self.gui.call(lambda root: threading.current_thread(), timeout=10)
        self.assertIsNot(seen, caller_thread)

    def test_call_propagates_exceptions(self):
        def boom(_root):
            raise ValueError("nope")

        with self.assertRaises(ValueError):
            self.gui.call(boom, timeout=10)

    def test_call_from_gui_thread_runs_inline(self):
        def outer(_root):
            return self.gui.call(lambda _r: "inner", timeout=10)

        self.assertEqual(self.gui.call(outer, timeout=10), "inner")

    def test_submit_does_not_block_and_still_runs(self):
        done = threading.Event()
        self.gui.submit(lambda _root: done.set())
        self.assertTrue(done.wait(10))

    def test_submit_swallows_errors(self):
        def boom(_root):
            raise RuntimeError("ignored")

        self.gui.submit(boom)
        # The thread must survive a failing task.
        self.assertEqual(self.gui.call(lambda _root: "alive", timeout=10), "alive")


if __name__ == "__main__":
    unittest.main()
