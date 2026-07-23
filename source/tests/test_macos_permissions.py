"""macOS permission onboarding for the keyboard listener (issue #25).

Real TCC cannot run in CI — the grant lives in a system database that no test
can write — so the platform probes are mocked and everything asserted here is
the decision logic sitting on top of them: what counts as missing, what the
user is told, and how the startup path and the tray react. The one thing that
must never regress is silence: a denied Mac has to end up logged, notified and
visible in the tray, because pynput itself reports nothing.
"""

import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import macos_permissions as mp
from app_module import txt_xpander as tx  # .pyw is not importable off Windows


GRANTED = mp.GRANTED
DENIED = mp.DENIED
UNKNOWN = mp.UNKNOWN


def status(listen=GRANTED, accessibility=GRANTED):
    return {mp.INPUT_MONITORING: listen, mp.ACCESSIBILITY: accessibility}


class ProbeTests(unittest.TestCase):
    """The ctypes layer, with the frameworks stubbed."""

    def test_input_monitoring_maps_the_iokit_access_codes(self):
        for code, expected in ((0, GRANTED), (1, DENIED), (2, UNKNOWN), (99, UNKNOWN)):
            with mock.patch.object(mp, "IS_MAC", True), \
                    mock.patch.object(mp, "_framework_symbol", return_value=mock.Mock(return_value=code)):
                self.assertEqual(mp.check_input_monitoring(), expected, code)

    def test_input_monitoring_asks_iokit_for_the_listen_event_request_type(self):
        # kIOHIDRequestTypeListenEvent is 0; passing PostEvent instead would
        # report the state of a permission the listener does not need.
        check = mock.Mock(return_value=0)
        with mock.patch.object(mp, "IS_MAC", True), \
                mock.patch.object(mp, "_framework_symbol", return_value=check):
            mp.check_input_monitoring()
        check.assert_called_once_with(0)

    def test_accessibility_reads_ax_is_process_trusted(self):
        for trusted, expected in ((True, GRANTED), (False, DENIED)):
            with mock.patch.object(mp, "IS_MAC", True), \
                    mock.patch.object(mp, "_framework_symbol", return_value=mock.Mock(return_value=trusted)):
                self.assertEqual(mp.check_accessibility(), expected)

    def test_missing_symbols_report_unknown_rather_than_denied(self):
        with mock.patch.object(mp, "IS_MAC", True), \
                mock.patch.object(mp, "_framework_symbol", return_value=None):
            self.assertEqual(mp.check_input_monitoring(), UNKNOWN)
            self.assertEqual(mp.check_accessibility(), UNKNOWN)

    def test_a_raising_framework_call_reports_unknown(self):
        with mock.patch.object(mp, "IS_MAC", True), \
                mock.patch.object(mp, "_framework_symbol", return_value=mock.Mock(side_effect=OSError("boom"))):
            self.assertEqual(mp.check_input_monitoring(), UNKNOWN)
            self.assertEqual(mp.check_accessibility(), UNKNOWN)

    def test_off_mac_nothing_is_probed(self):
        symbol = mock.Mock()
        with mock.patch.object(mp, "IS_MAC", False), \
                mock.patch.object(mp, "_framework_symbol", symbol):
            self.assertEqual(mp.check_permissions(), status(UNKNOWN, UNKNOWN))
        symbol.assert_not_called()

    def test_framework_symbol_survives_a_missing_library(self):
        with mock.patch.object(mp.ctypes.util, "find_library", return_value=None):
            self.assertIsNone(mp._framework_symbol("IOKit", "IOHIDCheckAccess"))
        with mock.patch.object(mp.ctypes.util, "find_library", return_value="/nope"), \
                mock.patch.object(mp.ctypes.cdll, "LoadLibrary", side_effect=OSError("missing")):
            self.assertIsNone(mp._framework_symbol("IOKit", "IOHIDCheckAccess"))


class DecisionTests(unittest.TestCase):
    def test_only_a_denial_asks_the_user_for_anything(self):
        self.assertFalse(mp.needs_onboarding(status()))
        self.assertFalse(mp.needs_onboarding(status(UNKNOWN, UNKNOWN)))
        self.assertTrue(mp.needs_onboarding(status(DENIED, GRANTED)))
        self.assertTrue(mp.needs_onboarding(status(GRANTED, DENIED)))

    def test_denied_and_unknown_are_reported_separately(self):
        report = status(DENIED, UNKNOWN)
        self.assertEqual(mp.denied_permissions(report), [mp.INPUT_MONITORING])
        self.assertEqual(mp.unknown_permissions(report), [mp.ACCESSIBILITY])

    def test_an_absent_key_counts_as_unknown_not_granted(self):
        self.assertEqual(mp.unknown_permissions({}), list(mp.PERMISSIONS))
        self.assertEqual(mp.denied_permissions({}), [])

    def test_input_monitoring_is_listed_before_accessibility(self):
        listed = mp.denied_permissions(status(DENIED, DENIED))
        self.assertEqual(listed, [mp.INPUT_MONITORING, mp.ACCESSIBILITY])

    def test_the_prompt_names_only_what_is_missing(self):
        message = mp.build_prompt_message(status(DENIED, GRANTED))
        self.assertIn(mp.PERMISSION_LABELS[mp.INPUT_MONITORING], message)
        self.assertNotIn(mp.PERMISSION_LABELS[mp.ACCESSIBILITY], message)
        # The privacy claim from the module docstring must survive here: it is
        # what makes granting a keylogger-shaped permission reasonable.
        self.assertIn("não armazena nem envia", message)

    def test_the_prompt_is_empty_when_nothing_is_missing(self):
        self.assertEqual(mp.build_prompt_message(status()), "")
        self.assertEqual(mp.build_tray_message(status()), "")

    def test_the_tray_message_states_the_consequence(self):
        message = mp.build_tray_message(status(DENIED, DENIED))
        self.assertIn(mp.PERMISSION_LABELS[mp.ACCESSIBILITY], message)
        self.assertIn("não vai funcionar", message)

    def test_every_permission_has_a_pane_a_label_and_a_reason(self):
        for name in mp.PERMISSIONS:
            self.assertIn(name, mp.SETTINGS_PANE_URLS)
            self.assertIn(name, mp.PERMISSION_LABELS)
            self.assertIn(name, mp.PERMISSION_REASONS)

    def test_the_panes_are_the_two_distinct_privacy_deep_links(self):
        self.assertIn("Privacy_ListenEvent", mp.SETTINGS_PANE_URLS[mp.INPUT_MONITORING])
        self.assertIn("Privacy_Accessibility", mp.SETTINGS_PANE_URLS[mp.ACCESSIBILITY])


class RecheckTests(unittest.TestCase):
    def test_a_full_grant_asks_for_a_restart_instead_of_claiming_it_works(self):
        state, message = mp.recheck_outcome(status(DENIED, DENIED), status())
        self.assertEqual(state, mp.RECHECK_RESOLVED)
        self.assertIn("Reinicie", message)

    def test_a_partial_grant_names_what_is_left(self):
        state, message = mp.recheck_outcome(status(DENIED, DENIED), status(GRANTED, DENIED))
        self.assertEqual(state, mp.RECHECK_PARTIAL)
        self.assertIn(mp.PERMISSION_LABELS[mp.ACCESSIBILITY], message)
        self.assertNotIn(mp.PERMISSION_LABELS[mp.INPUT_MONITORING], message)

    def test_no_change_says_so(self):
        state, message = mp.recheck_outcome(status(DENIED, GRANTED), status(DENIED, GRANTED))
        self.assertEqual(state, mp.RECHECK_PENDING)
        self.assertIn("Nada mudou", message)

    def test_an_unreadable_recheck_is_never_reported_as_resolved(self):
        # A probe that stopped answering is not a grant.
        state, _ = mp.recheck_outcome(status(DENIED, DENIED), status(UNKNOWN, UNKNOWN))
        self.assertEqual(state, mp.RECHECK_PENDING)

    def test_a_permission_denied_only_on_the_recheck_is_picked_up(self):
        state, message = mp.recheck_outcome(status(DENIED, GRANTED), status(GRANTED, DENIED))
        self.assertEqual(state, mp.RECHECK_PENDING)
        self.assertIn(mp.PERMISSION_LABELS[mp.ACCESSIBILITY], message)


class OpenPaneTests(unittest.TestCase):
    def test_the_pane_is_opened_through_launch_services(self):
        runner = mock.Mock(return_value=mock.Mock(returncode=0))
        self.assertTrue(mp.open_settings_pane(mp.ACCESSIBILITY, runner=runner))
        argv = runner.call_args.args[0]
        self.assertEqual(argv[0], "open")
        self.assertEqual(argv[1], mp.SETTINGS_PANE_URLS[mp.ACCESSIBILITY])

    def test_a_failed_launch_is_reported(self):
        runner = mock.Mock(return_value=mock.Mock(returncode=1))
        self.assertFalse(mp.open_settings_pane(mp.INPUT_MONITORING, runner=runner))

    def test_a_raising_launch_is_reported(self):
        runner = mock.Mock(side_effect=OSError("no open(1)"))
        self.assertFalse(mp.open_settings_pane(mp.INPUT_MONITORING, runner=runner))

    def test_an_unknown_permission_launches_nothing(self):
        runner = mock.Mock()
        self.assertFalse(mp.open_settings_pane("camera", runner=runner))
        runner.assert_not_called()


def make_app():
    """A TextExpander with only what the permission flow touches."""
    app = tx.TextExpander.__new__(tx.TextExpander)
    app.logger = mock.Mock()
    app.task_runner = mock.Mock()
    app.gui = mock.Mock()
    app.notify_error = mock.Mock()
    app.refresh_tray_menu = mock.Mock()
    app.open_macos_permission_window = mock.Mock()
    app._macos_permission_status = {}
    app.macos_permission_window = None
    return app


class AppFlowTests(unittest.TestCase):
    def _resolve(self, probe, is_mac=True):
        app = make_app()
        with mock.patch.object(tx, "IS_MAC", is_mac), \
                mock.patch.object(tx.macos_permissions, "check_permissions", probe):
            app.resolve_macos_permissions()
        return app

    def test_a_denied_grant_is_logged_notified_and_shown(self):
        app = self._resolve(mock.Mock(return_value=status(DENIED, DENIED)))
        self.assertTrue(app.logger.error.called)
        self.assertTrue(app.notify_error.called)
        app.open_macos_permission_window.assert_called_once_with()
        # The tray entry reads the cache, so it must be filled before the render.
        self.assertTrue(app.macos_permissions_pending())
        app.refresh_tray_menu.assert_called_once_with()

    def test_a_granted_mac_is_silent(self):
        app = self._resolve(mock.Mock(return_value=status()))
        app.open_macos_permission_window.assert_not_called()
        app.notify_error.assert_not_called()
        self.assertFalse(app.macos_permissions_pending())

    def test_an_unreadable_probe_logs_but_never_nags(self):
        app = self._resolve(mock.Mock(return_value=status(UNKNOWN, UNKNOWN)))
        self.assertTrue(app.logger.warning.called)
        app.open_macos_permission_window.assert_not_called()
        app.notify_error.assert_not_called()

    def test_off_mac_the_flow_does_nothing_at_all(self):
        probe = mock.Mock()
        app = self._resolve(probe, is_mac=False)
        probe.assert_not_called()
        app.open_macos_permission_window.assert_not_called()
        self.assertFalse(app.macos_permissions_pending())

    def test_a_raising_probe_never_escapes_the_worker(self):
        app = self._resolve(mock.Mock(side_effect=OSError("tcc down")))
        self.assertTrue(app.logger.warning.called)
        app.open_macos_permission_window.assert_not_called()

    def test_the_tray_entry_is_hidden_until_a_denial_is_cached(self):
        app = make_app()
        self.assertFalse(app.macos_permissions_pending())
        app._macos_permission_status = status(UNKNOWN, UNKNOWN)
        self.assertFalse(app.macos_permissions_pending())
        app._macos_permission_status = status(GRANTED, DENIED)
        self.assertTrue(app.macos_permissions_pending())

    def test_the_recheck_updates_the_cache_and_the_tray(self):
        app = make_app()
        app._macos_permission_status = status(DENIED, DENIED)
        app._update_permission_feedback = mock.Mock()
        with mock.patch.object(tx.macos_permissions, "check_permissions", return_value=status()):
            app._recheck_macos_permissions(status(DENIED, DENIED), mock.Mock(), mock.Mock())
        self.assertEqual(app._macos_permission_status, status())
        self.assertFalse(app.macos_permissions_pending())
        app.refresh_tray_menu.assert_called_once_with()
        message = app._update_permission_feedback.call_args.args[2]
        self.assertIn("Reinicie", message)

    def test_a_raising_recheck_reports_instead_of_dying(self):
        app = make_app()
        app._update_permission_feedback = mock.Mock()
        with mock.patch.object(tx.macos_permissions, "check_permissions", side_effect=OSError("boom")):
            app._recheck_macos_permissions(status(DENIED, DENIED), mock.Mock(), mock.Mock())
        self.assertTrue(app.logger.warning.called)
        self.assertTrue(app._update_permission_feedback.called)

    def test_a_failed_pane_launch_tells_the_user_where_to_go(self):
        app = make_app()
        with mock.patch.object(tx.macos_permissions, "open_settings_pane", return_value=False):
            app._open_macos_settings_pane(mp.INPUT_MONITORING)
        self.assertTrue(app.logger.error.called)
        self.assertTrue(app.notify_error.called)

    def test_the_window_is_opened_on_the_gui_thread_never_inline(self):
        app = make_app()
        app.open_macos_permission_window = tx.TextExpander.open_macos_permission_window.__get__(app)
        app.open_macos_permission_window()
        app.gui.submit.assert_called_once_with(app._show_macos_permission_window)

    def test_a_gui_failure_while_opening_is_logged_not_raised(self):
        app = make_app()
        app.gui.submit.side_effect = RuntimeError("no root")
        app.open_macos_permission_window = tx.TextExpander.open_macos_permission_window.__get__(app)
        app.open_macos_permission_window()
        self.assertTrue(app.logger.error.called)


class StartupWiringTests(unittest.TestCase):
    def test_the_probe_is_scheduled_once_the_tray_icon_exists(self):
        app = tx.TextExpander.__new__(tx.TextExpander)
        app.task_runner = mock.Mock()
        app.icon = None
        icon = mock.Mock()
        app.on_tray_ready(icon)
        names = [call.kwargs.get("name") for call in app.task_runner.start.call_args_list]
        self.assertIn("macos-permissions", names)
        self.assertIs(app.icon, icon)


class SecureInputProbeTests(unittest.TestCase):
    """Secure Keyboard Entry: a gate that cannot be granted, only waited out."""

    def test_off_macos_never_probes(self):
        symbol = mock.Mock()
        with mock.patch.object(mp, "IS_MAC", False), \
                mock.patch.object(mp, "_framework_symbol", symbol):
            self.assertFalse(mp.secure_input_enabled())
        symbol.assert_not_called()

    def test_a_missing_symbol_reports_not_secure(self):
        # An old macOS without the Carbon symbol must not block every expansion.
        with mock.patch.object(mp, "IS_MAC", True), \
                mock.patch.object(mp, "_framework_symbol", return_value=None):
            self.assertFalse(mp.secure_input_enabled())

    def test_the_carbon_answer_is_returned_as_a_bool(self):
        for answer, expected in ((1, True), (0, False)):
            with self.subTest(answer=answer):
                symbol = mock.Mock(return_value=answer)
                with mock.patch.object(mp, "IS_MAC", True), \
                        mock.patch.object(mp, "_framework_symbol", return_value=symbol):
                    self.assertIs(expected, mp.secure_input_enabled())

    def test_a_raising_probe_reports_not_secure(self):
        symbol = mock.Mock(side_effect=OSError("boom"))
        with mock.patch.object(mp, "IS_MAC", True), \
                mock.patch.object(mp, "_framework_symbol", return_value=symbol):
            self.assertFalse(mp.secure_input_enabled())

    @unittest.skipUnless(mp.IS_MAC, "Carbon is macOS-only")
    def test_the_real_symbol_resolves_on_this_host(self):
        # The probe is worthless if the binding is wrong; this is the only part
        # of it a test can exercise for real.
        self.assertIsInstance(mp.secure_input_enabled(), bool)


class SymbolResolutionCacheTests(unittest.TestCase):
    """secure_input_enabled() runs per detected trigger on the listener thread;
    the framework symbol is resolved once, the C probe stays live (PR #52)."""

    def setUp(self):
        mp._SYMBOL_CACHE.clear()

    def tearDown(self):
        mp._SYMBOL_CACHE.clear()

    def test_resolution_is_cached_but_the_probe_runs_every_call(self):
        probe = mock.Mock(return_value=0)  # 0 == not secure
        lib = mock.Mock(IsSecureEventInputEnabled=probe)
        with mock.patch.object(mp, "IS_MAC", True), \
                mock.patch.object(mp.ctypes.util, "find_library", return_value="/Carbon") as find, \
                mock.patch.object(mp.ctypes.cdll, "LoadLibrary", return_value=lib) as load:
            for _ in range(5):
                self.assertFalse(mp.secure_input_enabled())
        # The expensive resolution (find_library + LoadLibrary) happens once...
        self.assertEqual(find.call_count, 1)
        self.assertEqual(load.call_count, 1)
        # ...but the live IsSecureEventInputEnabled() call must run every time, or
        # the probe would go stale and report a frozen secure-input state.
        self.assertEqual(probe.call_count, 5)

    def test_a_failed_resolution_is_retried_not_cached(self):
        # A missing library must stay retryable: the documented answer to an
        # unresolved symbol is "not secure / unknown", never a permanent one.
        with mock.patch.object(mp.ctypes.util, "find_library", return_value=None) as find:
            self.assertIsNone(mp._framework_symbol("IOKit", "IOHIDCheckAccess"))
            self.assertIsNone(mp._framework_symbol("IOKit", "IOHIDCheckAccess"))
        self.assertEqual(find.call_count, 2)
        self.assertEqual(mp._SYMBOL_CACHE, {})


class SecureInputExpansionGateTests(unittest.TestCase):
    """A trigger typed under secure input is left exactly as typed."""

    def _app(self):
        app = tx.TextExpander.__new__(tx.TextExpander)
        app.logger = mock.Mock()
        app.notify = mock.Mock()
        app.task_runner = mock.Mock()
        app.keyboard_controller = mock.Mock()
        app.typed_text = "xhi"
        app._erase_chars = mock.Mock()
        return app

    def test_secure_input_blocks_the_erase_and_the_expansion(self):
        app = self._app()
        with mock.patch.object(tx, "IS_MAC", True), \
                mock.patch.object(tx.macos_permissions, "secure_input_enabled", return_value=True):
            app._dispatch_expansion("xhi", 3)

        # Nothing synthesized: the backspaces would be swallowed here but could
        # land somewhere else, and a half-erased trigger is worse than none.
        app._erase_chars.assert_not_called()
        self.assertEqual("", app.typed_text)

        # The expansion is not dispatched; the only background work scheduled is
        # the notification, which is deferred off the listener thread (notify()
        # writes to disk and calls the tray) rather than run inline.
        app.task_runner.start.assert_called_once()
        args, kwargs = app.task_runner.start.call_args
        self.assertIs(args[0], app.notify)
        self.assertIsNot(args[0], app._run_expansion)
        self.assertEqual(kwargs.get("name"), "secure-input-notify")
        self.assertEqual(kwargs.get("key"), "secure-input")
        # Not called inline on the listener thread.
        app.notify.assert_not_called()

    def test_normal_input_expands_as_usual(self):
        app = self._app()
        with mock.patch.object(tx, "IS_MAC", True), \
                mock.patch.object(tx.macos_permissions, "secure_input_enabled", return_value=False):
            app._dispatch_expansion("xhi", 3)

        app._erase_chars.assert_called_once_with(3)
        app.task_runner.start.assert_called_once()
        app.notify.assert_not_called()

    def test_off_macos_the_gate_is_never_consulted(self):
        app = self._app()
        probe = mock.Mock()
        with mock.patch.object(tx, "IS_MAC", False), \
                mock.patch.object(tx.macos_permissions, "secure_input_enabled", probe):
            app._dispatch_expansion("xhi", 3)

        probe.assert_not_called()
        app._erase_chars.assert_called_once_with(3)


class SecureInputNotifyDeferralTests(unittest.TestCase):
    """The secure-input gate runs on the keyboard listener thread; its
    notification (history JSON write + tray call) must be deferred (PR #52)."""

    def _app(self):
        app = tx.TextExpander.__new__(tx.TextExpander)
        app.logger = mock.Mock()
        app.task_runner = mock.Mock()
        app.icon = mock.Mock()
        app._notification_lock = threading.Lock()
        app.notification_timestamps = {}
        app.notification_history = []
        app.notification_history_file = "unused.json"
        return app

    def test_no_disk_write_runs_on_the_listener_thread(self):
        app = self._app()
        with mock.patch.object(tx, "IS_MAC", True), \
                mock.patch.object(tx.macos_permissions, "secure_input_enabled", return_value=True), \
                mock.patch.object(tx, "save_notification_history") as save:
            blocked = app._secure_input_blocks_expansion()

        self.assertTrue(blocked)
        # The JSON write never runs inline on the listener thread; notify() is
        # handed to the task runner, which does the I/O on a worker.
        save.assert_not_called()
        app.task_runner.start.assert_called_once()
        deferred = app.task_runner.start.call_args.args[0]
        # A bound method is re-created on each attribute access, so compare by
        # value (same function, same instance) rather than identity.
        self.assertEqual(deferred, app.notify)
        self.assertEqual(deferred.__func__, tx.TextExpander.notify)


class NotifySerializationTests(unittest.TestCase):
    """notify()'s cooldown check and history append are shared state touched by
    the listener and worker threads at once; a lock keeps them atomic (PR #52)."""

    def _app(self):
        app = tx.TextExpander.__new__(tx.TextExpander)
        app.logger = mock.Mock()
        app.icon = mock.Mock()
        app._notification_lock = threading.Lock()
        app.notification_timestamps = {}
        app.notification_history = []
        app.notification_history_file = "unused.json"
        return app

    def test_notify_serializes_its_state_mutation_on_the_lock(self):
        """While another thread holds ``_notification_lock``, notify() must not
        touch the shared timestamps/history — proving the cooldown check and the
        append happen under the lock. A pure-timing race is unreliable here: the
        critical section is a handful of bytecodes, shorter than CPython's thread
        switch interval, so it stays effectively atomic unless something blocks
        inside it. Holding the lock is that block, and it is deterministic."""
        app = self._app()
        started = threading.Event()
        finished = threading.Event()

        def worker():
            started.set()
            with mock.patch.object(tx, "save_notification_history"):
                app.notify("segura", key="secure-input", cooldown_seconds=0)
            finished.set()

        app._notification_lock.acquire()
        thread = threading.Thread(target=worker)
        try:
            thread.start()
            self.assertTrue(started.wait(1))
            # notify() is blocked on the lock we hold: no state mutation yet.
            self.assertFalse(finished.wait(0.2))
            self.assertEqual(app.notification_history, [])
            self.assertEqual(app.notification_timestamps, {})
            self.assertEqual(app.icon.notify.call_count, 0)
        finally:
            app._notification_lock.release()

        thread.join(1)
        self.assertTrue(finished.is_set())
        self.assertEqual(len(app.notification_history), 1)
        self.assertEqual(app.icon.notify.call_count, 1)

    def test_a_second_trigger_in_the_cooldown_window_records_once(self):
        app = self._app()
        with mock.patch.object(tx, "save_notification_history"):
            first = app.notify("segura", key="secure-input", cooldown_seconds=60)
            second = app.notify("segura", key="secure-input", cooldown_seconds=60)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(app.notification_history), 1)
        self.assertEqual(app.icon.notify.call_count, 1)


if __name__ == "__main__":
    unittest.main()
