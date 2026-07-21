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
import time
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

    def _static_rows(self, frame):
        """{trigger: (preview, markers)} from the static tab's Treeview."""
        trees = [w for w in _descendants(frame) if isinstance(w, ttk.Treeview)]
        self.assertTrue(trees, "expected a snippet Treeview")
        tree = trees[0]
        return {iid: tuple(tree.item(iid, "values"))[1:] for iid in tree.get_children()}

    def test_static_tree_shows_preview_and_markers(self):
        self.app.snippets["xsig"] = {
            "__kind__": "rich_text",
            "text": "Assinatura\nprincipal",
            "spans": [],
        }
        self.app.snippets["xgreet"] = "Olá %%nome%%, tudo bem?"

        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_static_snippets_tab(frame, root)
            root.update_idletasks()
            return self._static_rows(frame)

        rows = self._on_gui(build)
        self.assertEqual(("Assinatura principal", "RT"), rows["xsig"])
        self.assertEqual(("Olá %%nome%%, tudo bem?", "%%"), rows["xgreet"])
        self.assertEqual(("hello", ""), rows["xhi"])

    def test_selecting_a_tree_row_loads_the_editor(self):
        self.app.snippets["xsig"] = {
            "__kind__": "rich_text", "text": "Assinatura principal", "spans": [],
        }

        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_static_snippets_tab(frame, root)
            root.update_idletasks()

            tree = [w for w in _descendants(frame) if isinstance(w, ttk.Treeview)][0]
            tree.selection_set("xsig")
            root.update()

            # Entry order follows widget creation: search box, then trigger.
            entries = [w for w in _descendants(frame) if isinstance(w, tk.Entry)]
            text = [w for w in _descendants(frame) if isinstance(w, tk.Text)][0]
            return entries[1].get(), text.get("1.0", "end-1c")

        trigger, value = self._on_gui(build)
        self.assertEqual("xsig", trigger)
        self.assertEqual("Assinatura principal", value)

    def test_static_tab_reports_visible_count(self):
        self.app.snippets["xone"] = "one"
        self.app.snippets["xtwo"] = "two"
        counts = []

        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_static_snippets_tab(frame, root, set_count=counts.append)
            root.update_idletasks()

        self._on_gui(build)
        # xhi (seeded) + xone + xtwo; dynamic callables are filtered out.
        self.assertEqual([3], counts)

    def test_refresh_hook_repopulates_lists_after_library_swap(self):
        """Restore/import rebind self.snippets; registered lists must rebuild."""
        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_static_snippets_tab(frame, root)
            root.update_idletasks()
            return frame

        frame = self._on_gui(build)
        self.assertNotIn("ximported", self._on_gui(lambda _r: self._static_rows(frame)))

        # Stand in for restore_backup/import_library, which rebind the dict.
        self.app.snippets = {"ximported": "from backup"}

        def refresh(_root):
            self.app._refresh_manager_lists()
            return self._static_rows(frame)

        rows = self._on_gui(refresh)
        self.assertEqual({"ximported": ("from backup", "")}, rows)

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


def _form_windows(root):
    return [c for c in root.winfo_children()
            if isinstance(c, tk.Toplevel) and c.title() == "Preencher campos"]


def _find_form(root, label_text):
    for window in _form_windows(root):
        for widget in _descendants(window):
            if isinstance(widget, tk.Label) and label_text in str(widget.cget("text")):
                return window
    return None


@unittest.skipUnless(TK_AVAILABLE, "Tk display not available")
class ModalDialogSerializationTests(unittest.TestCase):
    """A second expansion dialog must be refused, never stacked.

    Stacked dialogs block their workers in nested event loops that unwind
    strictly LIFO: answering the older one first stranded its caller and lost
    its result. See TextExpander._run_modal_dialog.
    """

    def setUp(self):
        self.app = _make_app(tempfile.mkdtemp())
        self.app.gui.ensure_started()
        self.results = {}

    def tearDown(self):
        self.app.gui.stop()

    def _open_form(self, field):
        def worker():
            self.results[field] = self.app._show_form_dialog([field])

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread

    def _wait_for_form(self, label, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.app.gui.call(lambda root: _find_form(root, label) is not None, timeout=10):
                return
            time.sleep(0.05)
        self.fail(f"form dialog {label!r} never appeared")

    def _answer_form(self, label, value):
        def act(root):
            window = _find_form(root, label)
            if window is None:
                return False
            entry = [w for w in _descendants(window) if isinstance(w, tk.Entry)][0]
            entry.insert(0, value)
            window.event_generate("<Return>")
            return True

        self.assertTrue(self.app.gui.call(act, timeout=10), f"could not answer {label!r}")

    def test_second_dialog_is_refused_while_one_is_open(self):
        first = self._open_form("first")
        self._wait_for_form("First")

        second = self._open_form("second")
        second.join(10)
        self.assertFalse(second.is_alive(), "second dialog call should return immediately")
        self.assertIsNone(self.results["second"], "a refused dialog reports like a cancel")
        self.assertEqual(self.app.gui.call(lambda root: len(_form_windows(root)), timeout=10), 1)

        # The first dialog stays fully usable.
        self._answer_form("First", "one")
        first.join(10)
        self.assertEqual(self.results["first"], {"first": "one"})

    def test_dialog_lock_is_released_for_the_next_expansion(self):
        first = self._open_form("first")
        self._wait_for_form("First")
        self._answer_form("First", "one")
        first.join(10)

        later = self._open_form("later")
        self._wait_for_form("Later")
        self._answer_form("Later", "two")
        later.join(10)
        self.assertEqual(self.results["later"], {"later": "two"})


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

    def test_stop_wakes_callers_whose_work_never_ran(self):
        """Regression: a call still queued when the loop exits must fail its
        caller instead of leaving it blocked forever on ``done``."""
        self.gui.stop()

        # Inject a stranded item the way call() would have queued it.
        box = {}
        done = threading.Event()
        self.gui._queue.put((lambda _root: "never runs", box, done))

        self.gui.stop()
        self.assertTrue(done.is_set(), "stranded caller was never woken")
        self.assertIsInstance(box.get("error"), RuntimeError)


if __name__ == "__main__":
    unittest.main()
