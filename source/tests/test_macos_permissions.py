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


if __name__ == "__main__":
    unittest.main()
