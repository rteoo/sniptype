"""Tray-side autostart policy: what the menu shows and when the entry is repaired.

Classification itself lives in ``platform_support`` (see test_platform_support);
these tests cover the app's decisions on top of it — the cached ``checked=``
state, and repairing only an entry whose target is gone.
"""

import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import platform_support as ps
from app_module import sniptype as tx  # .pyw is not importable off Windows


def make_tray_app():
    """A Sniptype with only what the autostart path touches.

    Bypasses __init__: constructing the real app loads snippets, starts the GUI
    thread and installs a keyboard listener, none of which this policy involves.
    """
    app = tx.Sniptype.__new__(tx.Sniptype)
    app._autostart_lock = threading.Lock()
    app._autostart_state = tx.AUTOSTART_ABSENT
    app.logger = mock.Mock()
    app.icon = None  # refresh_tray_menu returns early without a tray icon
    return app


class MenuStateTests(unittest.TestCase):
    def test_checked_reads_the_cache_without_touching_disk(self):
        app = make_tray_app()
        with mock.patch.object(tx, "read_autostart_command") as read:
            app._autostart_state = tx.AUTOSTART_CURRENT
            self.assertTrue(app.autostart_is_enabled())
            for state in (tx.AUTOSTART_ABSENT, tx.AUTOSTART_STALE):
                app._autostart_state = state
                self.assertFalse(app.autostart_is_enabled())
        # pystray re-evaluates checked= on every menu render; a read here is the
        # freeze that #17 removed.
        read.assert_not_called()


class ResolveStateTests(unittest.TestCase):
    def setUp(self):
        self.app = make_tray_app()
        self.current = ps.default_autostart_command()

    def _resolve(self, existing, install=None):
        with mock.patch.object(tx, "read_autostart_command", return_value=existing) as read, \
                mock.patch.object(tx, "install_autostart", side_effect=install) as install_mock:
            self.app.resolve_autostart_state()
        self.assertEqual(read.call_count, 1, "startup must read the entry exactly once")
        return install_mock

    def test_absent_entry_stays_absent(self):
        install = self._resolve(None)
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_ABSENT)
        install.assert_not_called()

    def test_entry_for_this_install_is_current(self):
        install = self._resolve(list(self.current))
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_CURRENT)
        install.assert_not_called()

    def test_dead_target_is_repaired(self):
        """Case 1/3: a deleted dist folder or a removed interpreter."""
        gone = [os.path.join(os.path.dirname(__file__), "no-such-dir", "app.exe")]
        install = self._resolve(gone, install=lambda *a, **k: r"C:\Startup\Sniptype.lnk")
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_CURRENT)
        install.assert_called_once()

    def test_repair_failure_leaves_it_unchecked(self):
        gone = [os.path.join(os.path.dirname(__file__), "no-such-dir", "app.exe")]
        self._resolve(gone, install=OSError("access denied"))
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_STALE)
        self.app.logger.error.assert_called_once()

    def test_another_live_install_is_stale_but_untouched(self):
        """Case 2: the packaged release's shortcut must survive a dev-mode run."""
        # This test file stands in for the other install's script: it must be a
        # real file, or the entry would classify as dead and get repaired.
        other = [sys.executable, os.path.abspath(__file__)]
        install = self._resolve(other)
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_STALE)
        install.assert_not_called()
        self.app.logger.info.assert_called_once()

    def test_dead_script_with_live_interpreter_is_repaired(self):
        """Case 1 from the source side: the checkout is gone but its
        interpreter survives — the entry is just as dead at login."""
        gone = [sys.executable,
                os.path.join(os.path.dirname(__file__), "no-such-dir", "sniptype.pyw")]
        install = self._resolve(gone, install=lambda *a, **k: r"C:\Startup\Sniptype.lnk")
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_CURRENT)
        install.assert_called_once()

    def test_resolve_skips_when_the_lock_is_already_held(self):
        """A toggle in flight holds the lock; the startup resolve must back off
        rather than race it — and must not touch disk or change the cache."""
        self.app._autostart_state = tx.AUTOSTART_CURRENT
        self.app._autostart_lock.acquire()
        try:
            with mock.patch.object(tx, "read_autostart_command") as read, \
                    mock.patch.object(tx, "install_autostart") as install:
                self.app.resolve_autostart_state()
            read.assert_not_called()
            install.assert_not_called()
        finally:
            self.app._autostart_lock.release()
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_CURRENT)

    def test_unexpected_error_is_not_reported_as_enabled(self):
        """Reading a corrupt entry can raise more than OSError (decode/parse
        errors); none of it may kill the worker or leave the box checked."""
        with mock.patch.object(tx, "read_autostart_command", side_effect=ValueError("plist corrompida")), \
                mock.patch.object(tx, "install_autostart") as install:
            self.app.resolve_autostart_state()
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_STALE)
        install.assert_not_called()
        self.app.logger.warning.assert_called_once()

    def test_unreadable_entry_is_not_reported_as_enabled(self):
        with mock.patch.object(tx, "read_autostart_command", side_effect=OSError("boom")), \
                mock.patch.object(tx, "install_autostart") as install:
            self.app.resolve_autostart_state()
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_STALE)
        install.assert_not_called()
        self.app.logger.warning.assert_called_once()


class ToggleTests(unittest.TestCase):
    def setUp(self):
        self.app = make_tray_app()
        self.app.notify_status = mock.Mock()
        self.app.notify_error = mock.Mock()

    def test_toggle_off_removes_and_updates_the_cache(self):
        self.app._autostart_state = tx.AUTOSTART_CURRENT
        with mock.patch.object(tx, "remove_autostart") as remove, \
                mock.patch.object(tx, "install_autostart") as install:
            self.app._apply_autostart_toggle()
        remove.assert_called_once()
        install.assert_not_called()
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_ABSENT)

    def test_toggle_on_from_absent_installs_and_marks_current(self):
        """The happy activation path: no entry yet, so install and check the box."""
        self.app._autostart_state = tx.AUTOSTART_ABSENT
        with mock.patch.object(tx, "install_autostart", return_value="p") as install, \
                mock.patch.object(tx, "remove_autostart") as remove:
            self.app._apply_autostart_toggle()
        install.assert_called_once()
        remove.assert_not_called()
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_CURRENT)
        self.app.notify_status.assert_called_once()
        self.app.notify_error.assert_not_called()

    def test_toggle_on_a_stale_entry_overwrites_instead_of_removing(self):
        self.app._autostart_state = tx.AUTOSTART_STALE
        with mock.patch.object(tx, "remove_autostart") as remove, \
                mock.patch.object(tx, "install_autostart", return_value="p") as install:
            self.app._apply_autostart_toggle()
        install.assert_called_once()
        remove.assert_not_called()
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_CURRENT)

    def test_failed_install_does_not_claim_enabled(self):
        self.app._autostart_state = tx.AUTOSTART_ABSENT
        with mock.patch.object(tx, "install_autostart", side_effect=OSError("denied")):
            self.app._apply_autostart_toggle()
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_ABSENT)
        self.app.notify_error.assert_called_once()

    def test_unexpected_install_error_is_surfaced_not_swallowed(self):
        """Non-OSError failures must also notify instead of dying silently
        on the worker thread and eating the click."""
        self.app._autostart_state = tx.AUTOSTART_ABSENT
        with mock.patch.object(tx, "install_autostart", side_effect=ValueError("boom")):
            self.app._apply_autostart_toggle()
        self.assertEqual(self.app._autostart_state, tx.AUTOSTART_ABSENT)
        self.app.notify_error.assert_called_once()

    def test_busy_click_notifies_instead_of_dropping_silently(self):
        """The startup resolve can hold the lock for a PowerShell round-trip;
        a click landing then must say "wait", not vanish."""
        self.app._autostart_lock.acquire()
        try:
            with mock.patch.object(tx, "install_autostart") as install, \
                    mock.patch.object(tx, "remove_autostart") as remove:
                self.app._apply_autostart_toggle()
        finally:
            self.app._autostart_lock.release()
        install.assert_not_called()
        remove.assert_not_called()
        self.app.notify_status.assert_called_once()


class RefreshMenuTests(unittest.TestCase):
    """refresh_tray_menu runs after every resolve/toggle; a dying tray icon must
    not take the worker thread down with it, and on macOS the AppKit-touching
    update must be marshaled onto the main (GUI) thread rather than run on the
    calling worker thread (PR #50)."""

    def test_no_icon_is_a_noop(self):
        app = make_tray_app()  # icon is None
        app.gui = mock.Mock()
        app.refresh_tray_menu()  # must not raise
        app.logger.warning.assert_not_called()
        app.gui.submit.assert_not_called()

    def test_windows_updates_the_menu_directly_on_the_calling_thread(self):
        app = make_tray_app()
        app.icon = mock.Mock()
        app.gui = mock.Mock()
        with mock.patch.object(
            tx.platform_support, "tray_menu_updates_on_gui_thread", return_value=False
        ):
            app.refresh_tray_menu()
        # win32 posts a message internally, so no pump hop and no behavior change.
        app.icon.update_menu.assert_called_once()
        app.gui.submit.assert_not_called()

    def test_update_menu_error_is_swallowed_and_logged(self):
        app = make_tray_app()
        app.icon = mock.Mock()
        app.gui = mock.Mock()
        app.icon.update_menu.side_effect = RuntimeError("tray gone")
        with mock.patch.object(
            tx.platform_support, "tray_menu_updates_on_gui_thread", return_value=False
        ):
            app.refresh_tray_menu()  # must not raise
        app.icon.update_menu.assert_called_once()
        app.logger.warning.assert_called_once()

    def test_macos_routes_the_update_through_the_gui_pump(self):
        """pystray's darwin update_menu mutates AppKit (setMenu_) on the calling
        thread; a task-runner caller must hand it to the pump, which runs it on
        the main thread from inside the Tk loop."""
        app = make_tray_app()
        app.icon = mock.Mock()
        app.gui = mock.Mock()
        with mock.patch.object(
            tx.platform_support, "tray_menu_updates_on_gui_thread", return_value=True
        ):
            app.refresh_tray_menu()
        # Not touched on the worker thread; deferred to the pump instead.
        app.icon.update_menu.assert_not_called()
        app.gui.submit.assert_called_once_with(app._update_tray_menu)
        # The submitted callable is what actually rebuilds the menu, and the pump
        # passes it the Tk root as its single argument.
        submitted = app.gui.submit.call_args.args[0]
        submitted(object())
        app.icon.update_menu.assert_called_once()

    def test_macos_pump_side_swallows_and_logs_an_update_error(self):
        app = make_tray_app()
        app.icon = mock.Mock()
        app.icon.update_menu.side_effect = RuntimeError("tray gone")
        app._update_tray_menu(object())  # must not raise
        app.logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
