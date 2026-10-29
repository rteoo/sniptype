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
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_module import sniptype as tx  # .pyw is not importable off Windows


class DpiAwarenessTests(unittest.TestCase):
    def setUp(self):
        # Guard both ctypes loader surfaces so a regressed implementation can
        # never call a native DPI API during this pure test class.
        windll = types.SimpleNamespace(user32=types.SimpleNamespace(), shcore=types.SimpleNamespace())
        windll_patcher = mock.patch.object(tx.ctypes, "windll", new=windll, create=True)
        windll_patcher.start()
        self.addCleanup(windll_patcher.stop)
        loader_patcher = mock.patch.object(
            tx.ctypes, "WinDLL", create=True, side_effect=OSError("native loader blocked in tests")
        )
        loader_patcher.start()
        self.addCleanup(loader_patcher.stop)

    def test_per_monitor_v2_uses_pointer_context_and_stops_on_success(self):
        user32 = types.SimpleNamespace(SetProcessDpiAwarenessContext=mock.Mock(return_value=1))
        with mock.patch.object(tx, "IS_WINDOWS", True), \
                mock.patch.object(tx.ctypes, "WinDLL", create=True, return_value=user32) as load, \
                mock.patch.object(tx.ctypes, "set_last_error", create=True) as set_error, \
                mock.patch.object(tx.ctypes, "get_last_error", create=True, return_value=0):
            tx.set_dpi_awareness()

        api = user32.SetProcessDpiAwarenessContext
        self.assertEqual([tx.ctypes.c_void_p], api.argtypes)
        self.assertIs(api.restype, tx.ctypes.c_int32)
        self.assertEqual(tx.ctypes.c_void_p(-4).value, api.call_args.args[0].value)
        set_error.assert_called_once_with(0)
        load.assert_called_once_with("user32", use_last_error=True)

    def test_context_access_denied_respects_existing_process_awareness(self):
        user32 = types.SimpleNamespace(SetProcessDpiAwarenessContext=mock.Mock(return_value=0))
        with mock.patch.object(tx, "IS_WINDOWS", True), \
                mock.patch.object(tx.ctypes, "WinDLL", create=True, return_value=user32) as load, \
                mock.patch.object(tx.ctypes, "set_last_error", create=True), \
                mock.patch.object(tx.ctypes, "get_last_error", create=True, return_value=5):
            tx.set_dpi_awareness()

        load.assert_called_once_with("user32", use_last_error=True)

    def test_non_access_context_failure_tries_shcore_with_typed_hresult(self):
        user32 = types.SimpleNamespace(SetProcessDpiAwarenessContext=mock.Mock(return_value=0))
        shcore = types.SimpleNamespace(SetProcessDpiAwareness=mock.Mock(return_value=0))

        def load(name, **_kwargs):
            return {"user32": user32, "shcore": shcore}[name]

        with mock.patch.object(tx, "IS_WINDOWS", True), \
                mock.patch.object(tx.ctypes, "WinDLL", create=True, side_effect=load), \
                mock.patch.object(tx.ctypes, "set_last_error", create=True), \
                mock.patch.object(tx.ctypes, "get_last_error", create=True, return_value=87):
            tx.set_dpi_awareness()

        self.assertEqual([tx.ctypes.c_int], shcore.SetProcessDpiAwareness.argtypes)
        self.assertIs(shcore.SetProcessDpiAwareness.restype, tx.ctypes.c_int32)
        shcore.SetProcessDpiAwareness.assert_called_once_with(2)

    def test_shcore_failure_tries_checked_legacy_api(self):
        user32 = types.SimpleNamespace(SetProcessDpiAwarenessContext=mock.Mock(return_value=0))
        shcore = types.SimpleNamespace(SetProcessDpiAwareness=mock.Mock(return_value=-1))
        legacy = mock.Mock(return_value=1)

        def load(name, **_kwargs):
            return {"user32": user32, "shcore": shcore}[name]

        user32.SetProcessDPIAware = legacy
        with mock.patch.object(tx, "IS_WINDOWS", True), \
                mock.patch.object(tx.ctypes, "WinDLL", create=True, side_effect=load) as load_dll, \
                mock.patch.object(tx.ctypes, "set_last_error", create=True), \
                mock.patch.object(tx.ctypes, "get_last_error", create=True, return_value=87):
            tx.set_dpi_awareness()

        self.assertEqual([], legacy.argtypes)
        self.assertIs(legacy.restype, tx.ctypes.c_int32)
        legacy.assert_called_once_with()
        self.assertEqual(
            [mock.call("user32", use_last_error=True), mock.call("shcore", use_last_error=True),
             mock.call("user32", use_last_error=True)],
            load_dll.call_args_list,
        )

    def test_missing_windows_apis_and_non_windows_are_graceful(self):
        missing = types.SimpleNamespace()
        with mock.patch.object(tx, "IS_WINDOWS", True), \
                mock.patch.object(tx.ctypes, "WinDLL", create=True, return_value=missing):
            tx.set_dpi_awareness()

        with mock.patch.object(tx, "IS_WINDOWS", False), \
                mock.patch.object(tx.ctypes, "WinDLL", create=True) as load:
            tx.set_dpi_awareness()
        load.assert_not_called()

    def test_missing_windows_library_is_graceful(self):
        with mock.patch.object(tx, "IS_WINDOWS", True), \
                mock.patch.object(tx.ctypes, "WinDLL", create=True, side_effect=OSError("missing DLL")):
            tx.set_dpi_awareness()

    def test_loaded_api_programming_errors_are_not_swallowed(self):
        user32 = types.SimpleNamespace(
            SetProcessDpiAwarenessContext=mock.Mock(side_effect=RuntimeError("broken prototype"))
        )
        with mock.patch.object(tx, "IS_WINDOWS", True), \
                mock.patch.object(tx.ctypes, "WinDLL", create=True, return_value=user32), \
                mock.patch.object(tx.ctypes, "set_last_error", create=True):
            with self.assertRaisesRegex(RuntimeError, "broken prototype"):
                tx.set_dpi_awareness()

    def test_shcore_access_denied_does_not_downgrade_to_legacy(self):
        user32 = types.SimpleNamespace(SetProcessDpiAwarenessContext=mock.Mock(return_value=0))
        shcore = types.SimpleNamespace(SetProcessDpiAwareness=mock.Mock(return_value=-2147024891))

        def load(name, **_kwargs):
            return {"user32": user32, "shcore": shcore}[name]

        with mock.patch.object(tx, "IS_WINDOWS", True), \
                mock.patch.object(tx.ctypes, "WinDLL", create=True, side_effect=load) as load_dll, \
                mock.patch.object(tx.ctypes, "set_last_error", create=True), \
                mock.patch.object(tx.ctypes, "get_last_error", create=True, return_value=87):
            tx.set_dpi_awareness()

        shcore.SetProcessDpiAwareness.assert_called_once_with(2)
        self.assertEqual(2, load_dll.call_count)


def make_startup_app():
    """A Sniptype with only what ``run()`` touches, and nothing real behind it."""
    app = tx.Sniptype.__new__(tx.Sniptype)
    app.logger = mock.Mock()
    app.gui = mock.Mock()
    app.task_runner = mock.Mock()
    app.snippets = {}
    app.settings = {}
    app.enabled = True
    app.capture_error = None
    app.icon = None
    app._autostart_lock = threading.Lock()
    app._autostart_state = tx.AUTOSTART_ABSENT
    app._manager_process = None
    app._manager_process_lock = threading.Lock()
    app._pending_manager_target = None
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

    @staticmethod
    def _run(main_thread, options=None, snippets=None, show_manager=False):
        app = make_startup_app()
        if snippets is not None:
            app.snippets = snippets
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
            app.run(show_manager=show_manager)
        return app, icon, icon_cls

    def test_windows_keeps_the_tray_on_the_main_thread(self):
        app, icon, icon_cls = self._run(main_thread=False)

        app.gui.ensure_started.assert_called_once_with()
        app.gui.adopt_main_thread.assert_not_called()
        app.gui.run_mainloop.assert_not_called()
        icon.run.assert_called_once_with(setup=app.on_tray_ready)
        icon.run_detached.assert_not_called()
        self.assertEqual(icon_cls.call_args.kwargs, {})


    def test_main_passes_show_manager_flag_into_startup(self):
        for arguments, requested in (([], False), (["--show-manager"], True)):
            with self.subTest(arguments=arguments):
                expander = mock.Mock()
                with mock.patch.object(tx, "IS_WINDOWS", True), \
                        mock.patch.object(tx, "acquire_single_instance_mutex", return_value=True), \
                        mock.patch.object(tx, "set_dpi_awareness"), \
                        mock.patch.object(tx, "Sniptype", return_value=expander), \
                        mock.patch.object(tx.sys, "argv", ["sniptype.pyw", *arguments]):
                    tx.main()

                expander.run.assert_called_once_with(show_manager=requested)

    def test_show_manager_flag_opens_manager_through_existing_tray_action(self):
        # (old test, run(show_manager=...) or None for the default, main thread, opened)
        rows = (
            ("test_show_manager_flag_opens_manager_through_existing_tray_action", True, False, True),
            ("test_default_startup_does_not_open_manager", None, True, False),
        )
        for name, show_manager, main_thread, opened in rows:
            with self.subTest(name):
                app = make_startup_app()
                app.manage_snippets_gui = mock.Mock()
                icon = mock.Mock()
                with mock.patch.object(tx.pystray, "Icon", return_value=icon), \
                        mock.patch.object(
                            tx.platform_support, "tk_runs_on_main_thread", return_value=main_thread
                        ), \
                        mock.patch.object(
                            tx.platform_support, "hide_dock_icon", return_value=True
                        ), \
                        mock.patch.object(tx.platform_support, "tray_icon_options", return_value={}):
                    if show_manager is None:
                        app.run()
                    else:
                        app.run(show_manager=show_manager)

                if opened:
                    app.manage_snippets_gui.assert_called_once_with(None, None)
                else:
                    app.manage_snippets_gui.assert_not_called()

    def test_macos_show_manager_uses_gui_submission_boundary(self):
        app, _icon, _icon_cls = self._run(main_thread=True, show_manager=True)

        # Other startup work (the default window icon) may also be submitted;
        # the manager itself must be, exactly once.
        manager_calls = [
            call.args[0] for call in app.gui.submit.call_args_list
            if getattr(call.args[0], "__name__", "") == "_show_manager_window"
        ]
        self.assertEqual(1, len(manager_calls))
        self.assertIs(manager_calls[0].__self__, app)


class RunStartupOutputTests(unittest.TestCase):
    def test_startup_output_does_not_include_trigger_or_payload_values(self):
        snippets = {
            "MARKER_TRIGGER_ALPHA": "MARKER_PAYLOAD_ALPHA",
            "MARKER_TRIGGER_BETA": {"__kind__": "rich_text", "text": "MARKER_PAYLOAD_BETA"},
            "_marker_mapping": {"marker": "MARKER_MAPPING_VALUE"},
            "MARKER_DYNAMIC": lambda: "MARKER_DYNAMIC_VALUE",
        }
        output = StringIO()
        with redirect_stdout(output):
            RunStartupTests._run(main_thread=False, snippets=snippets)

        rendered = output.getvalue()
        self.assertNotIn("MARKER_", rendered)
        self.assertNotIn("_marker_mapping", rendered)
        self.assertIn("Snippets carregados (estáticos, não-callable): 2", rendered)
        self.assertIn("Snippets dinâmicos: 1", rendered)


class StartupAndSingleInstanceCompatibilityTests(unittest.TestCase):
    class Kernel32:
        def __init__(self, errors):
            self.errors = iter(errors)
            self.last_error = 0
            self.created = []
            self.closed = []

        def CreateMutexW(self, _security, _owner, name):
            self.created.append(name)
            handle, self.last_error = next(self.errors)
            return handle

        def GetLastError(self):
            return self.last_error

        def CloseHandle(self, handle):
            self.closed.append(handle)

    def setUp(self):
        tx.APP_MUTEX_HANDLES = []
        # These tests exercise ``run()`` through the helper above but do not
        # inherit RunStartupTests.setUp.  Keep the startup banner out of the
        # test runner: the Windows Actions console uses cp1252 and cannot
        # encode the banner's Unicode glyphs.
        patcher = mock.patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, main_thread, options=None):
        return RunStartupTests._run(main_thread, options)

    def _acquire(self, errors):
        kernel32 = self.Kernel32(errors)
        windll = types.SimpleNamespace(kernel32=kernel32)
        # ctypes exposes ``windll`` only on Windows.  This test supplies the
        # fake Win32 surface on every runner to exercise the compatibility
        # logic without requiring the host platform to provide the attribute.
        with mock.patch.object(tx.ctypes, "windll", windll, create=True):
            acquired = tx.acquire_single_instance_mutex()
        return acquired, kernel32

    def test_holds_both_names_so_an_old_build_cannot_start_later(self):
        acquired, kernel32 = self._acquire([(101, 0), (102, 0)])

        self.assertTrue(acquired)
        self.assertEqual(
            kernel32.created,
            [tx.LEGACY_APP_MUTEX_NAME, tx.APP_MUTEX_NAME],
        )
        self.assertEqual(tx.APP_MUTEX_HANDLES, [101, 102])
        self.assertEqual(kernel32.closed, [])

    def test_refuses_startup_when_the_legacy_mutex_already_exists(self):
        acquired, kernel32 = self._acquire([(101, tx.ERROR_ALREADY_EXISTS)])

        self.assertFalse(acquired)
        self.assertEqual(kernel32.created, [tx.LEGACY_APP_MUTEX_NAME])
        self.assertEqual(kernel32.closed, [101])

    def test_closes_legacy_handle_when_new_mutex_already_exists(self):
        acquired, kernel32 = self._acquire(
            [(101, 0), (102, tx.ERROR_ALREADY_EXISTS)]
        )

        self.assertFalse(acquired)
        self.assertEqual(kernel32.closed, [102, 101])
        self.assertEqual(tx.APP_MUTEX_HANDLES, [])

    def test_tray_menu_and_tooltip_show_the_running_version(self):
        menu = object()
        with mock.patch.object(tx.pystray, "Menu", return_value=menu) as menu_cls, \
                mock.patch.object(
                    tx.pystray, "MenuItem", side_effect=lambda *args, **kwargs: object()
                ) as menu_item:
            _app, _icon, icon_cls = self._run(main_thread=False)

        display_name = tx.APP_DISPLAY_NAME
        self.assertEqual(icon_cls.call_args.args[2], display_name)
        self.assertIs(icon_cls.call_args.args[3], menu)
        menu_cls.assert_called_once()

        version_item = next(
            call for call in menu_item.call_args_list
            if call.args and call.args[0] == display_name
        )
        self.assertFalse(version_item.kwargs["enabled"])

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

        The Dock icon is dropped after the root too (formerly
        test_macos_drops_the_dock_icon_after_the_root_exists): Tk sets the
        Regular policy as it starts, so reversing it before ``tk.Tk()`` would
        simply be overwritten and the menu-bar-only bundle would still show a
        Dock icon.
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
                mock.patch.object(
                    tx.platform_support,
                    "tray_icon_options",
                    side_effect=lambda: order.append("nsapp") or {},
                ):
            app.run()
        self.assertEqual(order, ["root", "dock", "nsapp"])
        app.logger.warning.assert_not_called()

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


SOURCE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


class TrayStateTests(unittest.TestCase):
    """The tray tells the sidebar's story: icon shape and tooltip per expansion state."""

    def _app(self, *, enabled=True, capture_error=None):
        app = tx.Sniptype.__new__(tx.Sniptype)
        app.logger = mock.Mock()
        app.enabled = enabled
        app.capture_error = capture_error
        app.icon = types.SimpleNamespace(icon=None, title=None, update_menu=mock.Mock())
        app.gui = mock.Mock()
        # The shipped icon, found where the packaged app finds it.
        app.resolve_resource_path = lambda name: os.path.join(SOURCE_DIR, name)
        return app

    @staticmethod
    def _pixels(image):
        return hash(image.convert("RGBA").tobytes())

    def test_each_state_draws_a_different_icon(self):
        with tx.Image.open(os.path.join(SOURCE_DIR, "sniptype.ico")) as icon_file:
            shipped = icon_file.convert("RGBA")
        active = self._app().load_tray_icon()
        paused = self._app(enabled=False).load_tray_icon()
        failed = self._app(enabled=False, capture_error=OSError("hook")).load_tray_icon()

        self.assertEqual(self._pixels(shipped), self._pixels(active), "on is the shipped icon")
        hashes = {self._pixels(image) for image in (active, paused, failed)}
        self.assertEqual(3, len(hashes))
        for image in (paused, failed):
            self.assertEqual(shipped.size, image.size)

    def test_a_failed_capture_is_down_even_if_the_flag_says_enabled(self):
        app = self._app(enabled=True, capture_error=OSError("hook"))

        self.assertEqual(
            self._pixels(self._app(enabled=False, capture_error=OSError("x")).load_tray_icon()),
            self._pixels(app.load_tray_icon()),
        )

    def test_the_tooltip_follows_the_state_and_stays_plain_when_expansion_is_on(self):
        for label, kwargs, expected in (
            ("on", {}, tx.APP_DISPLAY_NAME),
            ("paused", {"enabled": False}, f"{tx.APP_DISPLAY_NAME} · Expansão pausada"),
            ("failed", {"enabled": False, "capture_error": OSError("x")},
             f"{tx.APP_DISPLAY_NAME} · Captura falhou"),
        ):
            with self.subTest(label):
                app = self._app(**kwargs)
                app._update_tray_menu = mock.Mock()

                app._apply_tray_state()

                self.assertEqual(expected, app.icon.title)
                self.assertEqual(self._pixels(app.load_tray_icon()), self._pixels(app.icon.icon))
                app._update_tray_menu.assert_called_once_with()

    def test_pausing_and_resuming_redraws_the_tray(self):
        app = self._app()
        app.notify_status = mock.Mock()
        app._update_tray_menu = mock.Mock()
        with mock.patch.object(tx.platform_support, "tray_menu_updates_on_gui_thread",
                               return_value=False):
            app.toggle_enabled(app.icon, None)
            paused = (app.icon.title, self._pixels(app.icon.icon))
            app.toggle_enabled(app.icon, None)
            resumed = (app.icon.title, self._pixels(app.icon.icon))

        self.assertEqual(f"{tx.APP_DISPLAY_NAME} · Expansão pausada", paused[0])
        self.assertEqual(tx.APP_DISPLAY_NAME, resumed[0])
        self.assertNotEqual(paused[1], resumed[1])

    def test_a_capture_failure_redraws_the_tray_from_the_listener_thread(self):
        app = self._app()
        app.listener = None
        app.mouse_monitor = mock.Mock()
        app.notify_error = mock.Mock()
        app._update_tray_menu = mock.Mock()
        app._manager_status_var = None
        with mock.patch.object(tx.keyboard, "Listener", side_effect=OSError("hook")), \
                mock.patch.object(tx.platform_support, "tray_menu_updates_on_gui_thread",
                                  return_value=False):
            app.run_keyboard_listener()

        self.assertEqual(f"{tx.APP_DISPLAY_NAME} · Captura falhou", app.icon.title)

    def test_where_the_menu_belongs_to_the_gui_thread_the_redraw_is_queued(self):
        # macOS may only touch its status item from the main thread.
        app = self._app(enabled=False)
        with mock.patch.object(tx.platform_support, "tray_menu_updates_on_gui_thread",
                               return_value=True):
            app.refresh_tray_state()

        app.gui.submit.assert_called_once_with(app._apply_tray_state)
        self.assertIsNone(app.icon.title)

    def test_no_icon_yet_means_nothing_to_redraw(self):
        app = self._app(enabled=False)
        app.icon = None

        app.refresh_tray_state()

        app.gui.submit.assert_not_called()

    def test_the_first_menu_line_names_the_state_with_the_native_check_only(self):
        items = []

        def menu_item(*args, **kwargs):
            items.append((args, kwargs))
            return object()

        app = make_startup_app()
        with mock.patch.object(tx.pystray, "Icon", return_value=mock.Mock()), \
                mock.patch.object(tx.pystray, "Menu", return_value=object()), \
                mock.patch.object(tx.pystray, "MenuItem", side_effect=menu_item), \
                mock.patch.object(tx.platform_support, "tk_runs_on_main_thread", return_value=False), \
                mock.patch("builtins.print"):
            app.run()
        (text, action), kwargs = items[0]

        self.assertEqual(app.toggle_enabled, action)
        for label, enabled, capture_error, shown, checked, usable in (
            ("on", True, None, "Expansão ativa", True, True),
            ("paused", False, None, "Expansão ativa", False, True),
            ("failed", False, OSError("hook"), "Captura falhou", False, False),
        ):
            with self.subTest(label):
                app.enabled, app.capture_error = enabled, capture_error
                self.assertEqual(shown, text(None))
                self.assertEqual(checked, kwargs["checked"](None))
                self.assertEqual(usable, kwargs["enabled"](None))
                self.assertNotIn("✓", text(None))
                self.assertNotIn("✗", text(None))

    def test_tray_labels_are_sentence_case(self):
        labels = []
        app = make_startup_app()
        with mock.patch.object(tx.pystray, "Icon", return_value=mock.Mock()), \
                mock.patch.object(tx.pystray, "Menu", return_value=object()), \
                mock.patch.object(tx.pystray, "MenuItem",
                                  side_effect=lambda *a, **k: labels.append(a[0]) or object()), \
                mock.patch.object(tx.platform_support, "tk_runs_on_main_thread", return_value=False), \
                mock.patch("builtins.print"):
            app.run()

        texts = [label(None) for label in labels if callable(label)]
        self.assertIn("Gerenciar snippets", texts)
        self.assertNotIn("Gerenciar Snippets", texts)


class AppVersionFormattingTests(unittest.TestCase):
    def test_format_app_version(self):
        rows = (
            ("test_stable_version_has_no_channel_suffix", ("3.2.1", "stable"), "SnipType v3.2.1"),
            ("test_beta_version_has_an_explicit_channel_suffix", ("3.3.0", "beta"), "SnipType v3.3.0 beta"),
            ("test_missing_version_has_a_clear_fallback", (None,), "SnipType — versão desconhecida"),
        )
        for name, args, expected in rows:
            with self.subTest(name):
                self.assertEqual(tx.format_app_version(*args), expected)

    def test_running_build_is_the_1_4_0_beta_release(self):
        self.assertEqual(tx.APP_VERSION, "1.4.0")
        self.assertEqual(tx.RELEASE_CHANNEL, "beta")
        self.assertEqual(tx.APP_DISPLAY_NAME, "SnipType v1.4.0 beta")

    def test_older_source_without_a_channel_is_treated_as_stable(self):
        with mock.patch.object(tx, "__doc__", "Version: 9.8.7"):
            self.assertEqual(tx._read_release_metadata(), ("9.8.7", "stable"))

    def test_unknown_release_channel_fails_loudly(self):
        with mock.patch.object(tx, "__doc__", "Version: 9.8.7\nChannel: nightly"):
            with self.assertRaisesRegex(ValueError, "Unsupported release channel"):
                tx._read_release_metadata()

    def test_windows_installer_matches_the_beta_metadata(self):
        repo_root = Path(__file__).resolve().parents[2]
        installer = (repo_root / "installer" / "sniptype.iss").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('#define MyAppVersion "1.4.0"', installer)
        self.assertIn('#define MyAppChannel "beta"', installer)
        self.assertIn('#define MyAppName "SnipType"', installer)
        self.assertIn(
            "OutputBaseFilename=SniptypeSetup-{#MyInstallerVersion}",
            installer,
        )
        self.assertIn('MyInstallerVersion MyAppVersion + "-beta"', installer)
        self.assertIn('MyAppDisplayVersion MyAppVersion + " beta"', installer)

    def test_macos_release_icon_is_the_committed_grid_icns(self):
        repo_root = Path(__file__).resolve().parents[2]
        script = (repo_root / "build_release_macos.sh").read_text(encoding="utf-8")
        self.assertIn('cp "$REPO_DIR/source/sniptype.icns" "$ICNS"', script)
        # No conversion of the edge-to-edge Windows .ico, which would render
        # ~24% larger than other Mac icons and cap out at 256px.
        self.assertNotIn("sips -s format icns", script)
        self.assertIn("CFBundleIconFile", script)
        self.assertIn('! -s "$BUNDLE_ICON"', script)

    def test_macos_icns_has_every_slot_and_follows_apples_grid(self):
        from PIL import Image

        icns_path = Path(__file__).resolve().parents[2] / "source" / "sniptype.icns"
        with Image.open(icns_path) as icns:
            sizes = set(icns.info["sizes"])
            self.assertTrue(
                {(16, 16, 2), (32, 32, 2), (128, 128, 1), (256, 256, 1),
                 (512, 512, 1), (512, 512, 2)} <= sizes,
                sizes,
            )
            icns.size = (512, 512)
            icns.load(scale=2)
            full = icns.convert("RGBA")
        self.assertEqual((1024, 1024), full.size)
        # Apple's template: an 824px body centered on the 1024px canvas, the
        # margin left for the drop shadow. Allow a few pixels for the rim.
        left, top, right, bottom = full.getchannel("A").point(
            lambda a: 255 if a > 100 else 0
        ).getbbox()
        for edge in (left, top, 1024 - right, 1024 - bottom):
            self.assertGreaterEqual(edge, 92)
            self.assertLessEqual(edge, 112)

    def test_macos_release_tries_current_then_pre_rebrand_signing_identity(self):
        # The rebrand renamed the default to "Sniptype Dev" while existing
        # machines kept the "Txt Xpander Dev" certificate, so every build there
        # silently fell back to ad-hoc and lost its TCC grants.
        repo_root = Path(__file__).resolve().parents[2]
        script = (repo_root / "build_release_macos.sh").read_text(encoding="utf-8")

        with self.subTest("test_macos_release_tries_current_then_pre_rebrand_signing_identity"):
            self.assertIn(
                'DEFAULT_SIGN_IDENTITIES=("Sniptype Dev" "Txt Xpander Dev")', script
            )
            self.assertIn('for candidate in "${DEFAULT_SIGN_IDENTITIES[@]}"', script)
            # Matched with its quotes, as `security find-identity` prints it.
            self.assertIn('grep -qF "\\"$candidate\\""', script)

        with self.subTest("test_macos_release_reports_the_signing_mode_that_was_used"):
            self.assertIn('if [[ "$SIGN_IDENTITY" == "-" ]]', script)
            self.assertIn("Every ad-hoc rebuild changes the bundle's identity", script)
            self.assertIn('The bundle is signed with \\"$SIGN_IDENTITY\\"', script)

if __name__ == "__main__":
    unittest.main()
