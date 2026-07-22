"""Which loop owns the main thread at startup (issue #24).

Windows and macOS need mirror-image startups: on Windows ``icon.run()`` blocks
the main thread while the Tk root lives on a spawned one; on macOS Tk owns the
main thread and the tray attaches to the ``NSApplication`` it created, running
detached. Both branches are asserted here because the failure mode of getting
one wrong is a process that either aborts (Tk off-main on macOS) or never shows
a window — neither of which a unit test of the parts alone would catch.
"""

import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_module import txt_xpander as tx  # .pyw is not importable off Windows


def make_startup_app():
    """A TextExpander with only what ``run()`` touches, and nothing real behind it."""
    app = tx.TextExpander.__new__(tx.TextExpander)
    app.logger = mock.Mock()
    app.gui = mock.Mock()
    app.task_runner = mock.Mock()
    app.snippets = {}
    app.enabled = True
    app.icon = None
    app._autostart_lock = threading.Lock()
    app._autostart_state = tx.AUTOSTART_ABSENT
    app.is_admin = mock.Mock(return_value=False)
    app.load_tray_icon = mock.Mock(return_value="icon-image")
    return app


class RunStartupTests(unittest.TestCase):
    def setUp(self):
        # run() prints a startup banner to the console; silence it so the runner
        # output stays readable.
        patcher = mock.patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, main_thread, options=None):
        app = make_startup_app()
        icon = mock.Mock()
        with mock.patch.object(tx.pystray, "Icon", return_value=icon) as icon_cls, \
                mock.patch.object(
                    tx.platform_support, "tk_runs_on_main_thread", return_value=main_thread
                ), \
                mock.patch.object(
                    tx.platform_support, "hide_dock_icon", return_value=True
                ), \
                mock.patch.object(
                    tx.platform_support, "tray_icon_options", return_value=dict(options or {})
                ):
            app.run()
        return app, icon, icon_cls

    def test_windows_keeps_the_tray_on_the_main_thread(self):
        app, icon, icon_cls = self._run(main_thread=False)

        app.gui.ensure_started.assert_called_once_with()
        app.gui.adopt_main_thread.assert_not_called()
        app.gui.run_mainloop.assert_not_called()
        icon.run.assert_called_once_with(setup=app.on_tray_ready)
        icon.run_detached.assert_not_called()
        self.assertEqual(icon_cls.call_args.kwargs, {})

    def test_macos_gives_tk_the_main_thread_and_runs_the_tray_detached(self):
        shared = object()
        app, icon, icon_cls = self._run(
            main_thread=True, options={"darwin_nsapplication": shared}
        )

        app.gui.adopt_main_thread.assert_called_once_with()
        app.gui.ensure_started.assert_not_called()
        icon.run_detached.assert_called_once_with(setup=app.on_tray_ready)
        icon.run.assert_not_called()
        app.gui.run_mainloop.assert_called_once_with()
        self.assertEqual(icon_cls.call_args.kwargs, {"darwin_nsapplication": shared})

    def test_macos_drops_the_dock_icon_after_the_root_exists(self):
        """Order is the whole point: Tk sets the Regular policy as it starts.

        Reversing the policy before ``tk.Tk()`` would simply be overwritten,
        and the menu-bar-only bundle would still show a Dock icon.
        """
        order = []
        app = make_startup_app()
        app.gui.adopt_main_thread.side_effect = lambda: order.append("root") or True
        with mock.patch.object(tx.pystray, "Icon", return_value=mock.Mock()), \
                mock.patch.object(
                    tx.platform_support, "tk_runs_on_main_thread", return_value=True
                ), \
                mock.patch.object(
                    tx.platform_support,
                    "hide_dock_icon",
                    side_effect=lambda: order.append("dock") or True,
                ), \
                mock.patch.object(tx.platform_support, "tray_icon_options", return_value={}):
            app.run()
        self.assertEqual(order, ["root", "dock"])
        app.logger.warning.assert_not_called()

    def test_windows_never_touches_the_activation_policy(self):
        app = make_startup_app()
        with mock.patch.object(tx.pystray, "Icon", return_value=mock.Mock()), \
                mock.patch.object(
                    tx.platform_support, "tk_runs_on_main_thread", return_value=False
                ), \
                mock.patch.object(tx.platform_support, "hide_dock_icon") as hide, \
                mock.patch.object(tx.platform_support, "tray_icon_options", return_value={}):
            app.run()
        hide.assert_not_called()

    def test_a_dock_icon_that_will_not_hide_only_warns(self):
        """Cosmetic failure: the tray must still come up."""
        app = make_startup_app()
        icon = mock.Mock()
        with mock.patch.object(tx.pystray, "Icon", return_value=icon), \
                mock.patch.object(
                    tx.platform_support, "tk_runs_on_main_thread", return_value=True
                ), \
                mock.patch.object(
                    tx.platform_support, "hide_dock_icon", return_value=False
                ), \
                mock.patch.object(tx.platform_support, "tray_icon_options", return_value={}):
            app.run()
        app.logger.warning.assert_called_once()
        icon.run_detached.assert_called_once_with(setup=app.on_tray_ready)

    def test_the_root_exists_before_the_nsapplication_is_read(self):
        """``sharedApplication()`` creates a bare NSApplication when none exists.

        Reading it before ``tk.Tk()`` would hand pystray an application object
        that no loop ever runs, so the icon would simply never appear.
        """
        order = []
        app = make_startup_app()
        app.gui.adopt_main_thread.side_effect = lambda: order.append("root") or True
        with mock.patch.object(tx.pystray, "Icon", return_value=mock.Mock()), \
                mock.patch.object(
                    tx.platform_support, "tk_runs_on_main_thread", return_value=True
                ), \
                mock.patch.object(
                    tx.platform_support,
                    "tray_icon_options",
                    side_effect=lambda: order.append("nsapp") or {},
                ):
            app.run()
        self.assertEqual(order, ["root", "nsapp"])

    def test_a_failed_gui_start_still_raises_a_windows_tray(self):
        """pystray owns its own loop there, so a dialog-less tray still works."""
        app = make_startup_app()
        icon = mock.Mock()
        app.gui.ensure_started.side_effect = RuntimeError("no display")
        with mock.patch.object(tx.pystray, "Icon", return_value=icon), \
                mock.patch.object(
                    tx.platform_support, "tk_runs_on_main_thread", return_value=False
                ), \
                mock.patch.object(tx.platform_support, "tray_icon_options", return_value={}):
            app.run()
        app.logger.error.assert_called_once()
        icon.run.assert_called_once()

    def test_a_failed_gui_start_on_macos_gives_up_instead_of_a_loopless_tray(self):
        """There the Tk loop *is* the tray's loop: no root, nothing to run."""
        app = make_startup_app()
        app.gui.adopt_main_thread.side_effect = RuntimeError("no display")
        with mock.patch.object(tx.pystray, "Icon") as icon_cls, \
                mock.patch.object(
                    tx.platform_support, "tk_runs_on_main_thread", return_value=True
                ), \
                mock.patch.object(
                    tx.platform_support, "tray_icon_options"
                ) as options:
            app.run()
        self.assertEqual(app.logger.error.call_count, 2)
        icon_cls.assert_not_called()
        # Reading sharedApplication() with no root would mint a bare
        # NSApplication nobody runs; the early return must precede it.
        options.assert_not_called()


if __name__ == "__main__":
    unittest.main()
