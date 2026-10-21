"""Headless seams for manager navigation and persistence orchestration."""

import json
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_module import sniptype as tx
import manager_actions
from manager_actions import toggle_favorite
from runtime_support import LOGGER_NAME
from sync_export import ExportOutcome
from workflow_support import SnippetRef

SOURCE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class InlineGui:
    """A GuiThread stand-in that runs work inline, as submit does on the GUI thread."""

    def __init__(self):
        self.root = object()

    def submit(self, func):
        func(self.root)


def make_real_app(test, snippets, *, raw=None, backups=()):
    """A real Sniptype on a temporary data home with the bundled dynamic registry.

    ``raw`` is written as snippets.json instead of ``snippets`` (a corrupt
    file, say); ``backups`` are ``(file name, text)`` pairs placed in
    ``backups/``, the last one the newest.
    """
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    test.addCleanup(tmp.cleanup)
    home = tmp.name

    def close_log_handlers():
        # The app's log file lives in the temp home; release it so the
        # directory can be removed.
        logger = logging.getLogger(LOGGER_NAME)
        prefix = os.path.normcase(os.path.abspath(home))
        for handler in list(logger.handlers):
            filename = getattr(handler, "baseFilename", None)
            if filename and os.path.normcase(os.path.abspath(filename)).startswith(prefix):
                logger.removeHandler(handler)
                handler.close()

    test.addCleanup(close_log_handlers)
    with open(os.path.join(home, "snippets.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(snippets) if raw is None else raw)
    if backups:
        os.makedirs(os.path.join(home, "backups"))
    for age, (name, text) in enumerate(backups):
        path = os.path.join(home, "backups", name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.utime(path, (1_700_000_000 + age, 1_700_000_000 + age))
    with mock.patch.dict(os.environ, {"SNIPTYPE_HOME": home}), \
            mock.patch.object(tx, "get_runtime_base_dir", return_value=home), \
            mock.patch.object(tx, "get_runtime_resource_dir", return_value=SOURCE_DIR):
        return tx.Sniptype()


class ManagerRuntimeTests(unittest.TestCase):
    def _app(self):
        app = object.__new__(tx.Sniptype)
        app.snippets = {
            "hello": "Hello",
            "_codes": {"__prefix__": "c", "city": "Goiânia"},
        }
        app.library_metadata = {
            "groups": {"work": {"label": "Work", "prefix": "w"}},
            "items": {"static": {"hello": {"group_id": "work"}}, "mappings": {}},
        }
        app.dynamic_registry = {"xdate": {"trigger": "today", "enabled": True}}
        app._manager_tab_selectors = {}
        app._manager_refreshers = []
        app.trigger_index = {}
        app.refresh_runtime_indexes = mock.Mock()
        app._refresh_manager_lists = mock.Mock()
        app.capture_error = None
        app.icon = None
        return app

    def test_manager_target_resolves_stable_static_mapping_and_dynamic_refs(self):
        app = self._app()
        self.assertEqual("static", tx.Sniptype._manager_target(app, SnippetRef("static", "hello")).kind)
        mapping = tx.Sniptype._manager_target(app, SnippetRef("mapping", "city", "_codes"))
        self.assertEqual("mapping", mapping.kind)
        self.assertEqual("ccity", mapping.effective_trigger)
        self.assertEqual("dynamic", tx.Sniptype._manager_target(app, SnippetRef("dynamic", "xdate")).kind)

    def test_manager_collision_set_excludes_invalid_dynamic_enabled_value(self):
        app = self._app()
        app.dynamic_registry = {
            "invalid": {"trigger": "today", "enabled": "false"},
            "disabled": {"trigger": "tomorrow", "enabled": False},
            "active": {"trigger": "now", "enabled": True},
        }

        self.assertEqual(
            {"ccity", "now"},
            tx.Sniptype._manager_dynamic_triggers(app),
        )

    def test_failed_manager_save_does_not_publish_copy_on_write_state(self):
        app = self._app()
        original_snippets, original_metadata = app.snippets, app.library_metadata
        result = toggle_favorite(app.snippets, app.library_metadata, "hello", True)
        app.save_snippets = mock.Mock(return_value=False)

        self.assertFalse(tx.Sniptype._persist_manager_action(app, result))
        self.assertIs(original_snippets, app.snippets)
        self.assertIs(original_metadata, app.library_metadata)
        app.refresh_runtime_indexes.assert_not_called()

    def test_successful_manager_save_publishes_content_and_metadata_after_save(self):
        app = self._app()
        result = toggle_favorite(app.snippets, app.library_metadata, "hello", True)
        observed = []

        def save(snippets, metadata=None):
            observed.append((app.snippets, app.library_metadata, snippets, metadata))
            return True

        app.save_snippets = save
        self.assertTrue(tx.Sniptype._persist_manager_action(app, result))
        self.assertIs(result.snippets, app.snippets)
        self.assertIs(result.metadata, app.library_metadata)
        self.assertIsNot(observed[0][0], result.snippets)
        self.assertIsNot(observed[0][1], result.metadata)
        app.refresh_runtime_indexes.assert_called_once_with()
        app._refresh_manager_lists.assert_called_once_with()

    def test_tray_reload_with_the_manager_open_runs_on_the_gui_thread(self):
        # The open manager may hold drafts, which it settles on the GUI
        # thread before the library is read again.
        app = self._app()
        app.manager_window = object()
        app.gui = mock.Mock()
        app.load_snippets = mock.Mock(return_value={"updated": "value"})
        app.notify_status = mock.Mock()
        before = app.snippets

        tx.Sniptype.reload_snippets(app, None, None)

        app.gui.submit.assert_called_once_with(app._reload_snippets_in_manager)
        app.load_snippets.assert_not_called()
        self.assertIs(before, app.snippets)

    def test_tray_reload_with_the_manager_closed_reads_the_library_at_once(self):
        app = self._app()
        app.manager_window = None
        app.gui = mock.Mock()
        app.load_snippets = mock.Mock(return_value={"updated": "value"})
        app.notify_status = mock.Mock()

        tx.Sniptype.reload_snippets(app, None, None)

        self.assertEqual({"updated": "value"}, app.snippets)
        app.refresh_runtime_indexes.assert_called_once_with()
        app.gui.submit.assert_not_called()
        app._refresh_manager_lists.assert_not_called()
        app.notify_status.assert_called_once_with("Biblioteca atualizada.", key="reload-snippets")

    def test_tray_reload_refreshes_a_manager_that_opened_while_it_read(self):
        # Regression: the manager built from the snapshot taken before the
        # reload and nothing refreshed it afterwards.
        app = self._app()
        app.manager_window = None
        app.gui = mock.Mock()

        def read_library():
            app.manager_window = object()
            return {"updated": "value"}

        app.load_snippets = mock.Mock(side_effect=read_library)
        app.notify_status = mock.Mock()

        tx.Sniptype.reload_snippets(app, None, None)

        self.assertEqual({"updated": "value"}, app.snippets)
        app.gui.submit.assert_called_once_with(app._refresh_manager_lists)
        app.notify_status.assert_called_once_with("Biblioteca atualizada.", key="reload-snippets")

    def test_a_failed_tray_reload_leaves_the_manager_alone(self):
        app = self._app()
        app.manager_window = None
        app.gui = mock.Mock()

        def fail_after_the_manager_opened():
            app.manager_window = object()
            raise OSError("unreadable")

        app.load_snippets = mock.Mock(side_effect=fail_after_the_manager_opened)
        app.notify_status = mock.Mock()
        app.notify_error = mock.Mock()

        tx.Sniptype.reload_snippets(app, None, None)

        app.notify_error.assert_called_once()
        app.notify_status.assert_not_called()
        app.gui.submit.assert_not_called()

    def test_release_manager_ui_refs_drops_widget_callbacks_and_controllers(self):
        app = self._app()
        app._manager_notebook = object()
        app.manager_window = object()
        app._manager_refreshers = [object()]
        app._manager_editors = [object()]
        app._manager_tab_selectors = {"static": object()}
        app._manager_preview_controller = object()

        tx.Sniptype._release_manager_ui_refs(app)

        self.assertIsNone(app._manager_notebook)
        self.assertIsNone(app.manager_window)
        self.assertEqual([], app._manager_refreshers)
        self.assertEqual([], app._manager_editors)
        self.assertEqual({}, app._manager_tab_selectors)
        self.assertIsNone(app._manager_preview_controller)

    def test_pause_command_updates_visible_state_on_the_gui_thread(self):
        app = self._app()
        app.enabled = True
        app.icon = None
        app.gui = mock.Mock()
        app.notify_status = mock.Mock()
        app._manager_status_var = mock.Mock()
        app._manager_toggle_button = mock.Mock()
        app._manager_status_label = mock.Mock()
        app._manager_status_icon = mock.Mock()

        app.toggle_enabled(None, None)

        self.assertFalse(app.enabled)
        app.gui.submit.assert_called_once_with(app._refresh_manager_status)
        app._manager_status_var.set.assert_not_called()
        with mock.patch.object(tx.ui_widgets, "signal_image") as signal_image:
            app._refresh_manager_status()
        app._manager_status_var.set.assert_called_once_with("Expansão pausada")
        app._manager_toggle_button.configure.assert_called_once_with(
            text="Retomar expansão"
        )
        # A paused state is drawn with the warning tone and its pause icon.
        ui = tx.ui_theme.theme()
        self.assertEqual(ui.warning, app._manager_status_label.configure.call_args.kwargs["fg"])
        self.assertEqual((ui.warning, "pause"), signal_image.call_args.args[1:3])

    def test_capture_failure_shows_on_the_manager_and_disables_the_toggle(self):
        app = self._app()
        app.enabled = False
        app.capture_error = OSError("hook unavailable")
        app._manager_status_var = mock.Mock()
        app._manager_toggle_button = mock.Mock()
        app._manager_status_label = mock.Mock()
        app._manager_status_icon = mock.Mock()

        with mock.patch.object(tx.ui_widgets, "set_icon") as set_icon, mock.patch.object(
                tx.ui_widgets, "signal_image") as signal_image:
            app._refresh_manager_status()

        app._manager_status_var.set.assert_called_once_with("Captura falhou")
        ui = tx.ui_theme.theme()
        self.assertEqual(ui.danger, app._manager_status_label.configure.call_args.kwargs["fg"])
        self.assertEqual((ui.danger, "error"), signal_image.call_args.args[1:3])
        app._manager_toggle_button.configure.assert_called_once_with(
            text="Reinicie o SnipType", state=tx.tk.DISABLED,
        )
        set_icon.assert_called_once_with(app._manager_toggle_button, "refresh")

    def test_resume_is_refused_after_a_capture_failure_and_says_why(self):
        # Regression: Retomar flipped the flag and showed "Expansão ativa"
        # while no listener existed to expand anything.
        app = self._app()
        app.enabled = False
        app.capture_error = OSError("hook unavailable")
        app.gui = mock.Mock()
        app.notify_status = mock.Mock()
        app.notify_error = mock.Mock()

        app.toggle_enabled(None, None)

        self.assertFalse(app.enabled)
        app.notify_status.assert_not_called()
        app.notify_error.assert_called_once()
        self.assertIn("Reinicie o SnipType", app.notify_error.call_args.args[0])
        app.gui.submit.assert_not_called()

    def _failing_listener_app(self):
        app = self._app()
        app.enabled = True
        app.listener = None
        app.logger = mock.Mock()
        app.mouse_monitor = mock.Mock()
        app.notify_error = mock.Mock()
        app.gui = mock.Mock()
        return app

    def test_a_listener_failure_records_the_error_and_refreshes_an_open_manager(self):
        app = self._failing_listener_app()
        app._manager_status_var = mock.Mock()
        error = OSError("hook unavailable")

        with mock.patch.object(tx.keyboard, "Listener", side_effect=error):
            app.run_keyboard_listener()

        self.assertIs(error, app.capture_error)
        self.assertFalse(app.enabled)
        app.gui.submit.assert_called_once_with(app._refresh_manager_status)

    def test_a_listener_failure_with_the_manager_closed_queues_no_gui_work(self):
        app = self._failing_listener_app()
        app._manager_status_var = None

        with mock.patch.object(tx.keyboard, "Listener", side_effect=OSError("hook")):
            app.run_keyboard_listener()

        self.assertIsNotNone(app.capture_error)
        app.gui.submit.assert_not_called()


class FakeTrayIcon:
    visible = True

    def __init__(self):
        self.toasts = []

    def notify(self, text, title=None):
        self.toasts.append(text)


class FakeReceiptLine:
    def __init__(self):
        self.shown = []

    def show(self, text, *args, **kwargs):
        self.shown.append(text)


class FakeNotebook:
    def select(self):
        return ".manager.page"


class FakeWindow:
    def __init__(self, focused=True):
        self.focused = focused

    def focus_displayof(self):
        return object() if self.focused else None


class ReceiptRoutingTests(unittest.TestCase):
    """Routine success is a receipt while the person is in the window, a toast otherwise."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        app = object.__new__(tx.Sniptype)
        app.logger = mock.Mock()
        app.icon = FakeTrayIcon()
        app.gui = InlineGui()
        app._notification_lock = tx.threading.Lock()
        app.notification_timestamps = {}
        app.notification_history = []
        app.notification_history_file = os.path.join(tmp.name, "notifications.json")
        app.manager_window = FakeWindow()
        app._manager_notebook = FakeNotebook()
        self.line = FakeReceiptLine()
        app._manager_receipts = {".manager.page": self.line}
        app._manager_visible = True
        self.app = app

    def test_a_manager_command_writes_its_receipt_and_sends_no_toast(self):
        self.assertTrue(self.app.receipt(tx.N_("Salvo às {time}"), "xola", key="save"))

        self.assertRegex(self.line.shown[0], r"^Salvo às \d\d:\d\d · xola$")
        self.assertEqual([], self.app.icon.toasts)

    def test_every_receipt_is_kept_in_the_dated_history(self):
        self.app.receipt(tx.N_("Salvo às {time}"), "xola", key="save")

        (entry,) = self.app.notification_history
        self.assertEqual("status", entry["kind"])
        self.assertRegex(entry["message"], r"^Salvo às \d\d:\d\d · xola$")
        # The date travels with the clock, in ISO.
        self.assertRegex(entry["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertRegex(entry["time"], r"^\d\d:\d\d:\d\d$")
        saved = tx.load_notification_history(self.app.notification_history_file)
        self.assertEqual(entry, saved[0])

    def test_two_receipts_in_a_row_both_show(self):
        # The cooldown protects the tray from spam; the status line wants the latest.
        self.app.receipt(tx.N_("Salvo às {time}"), "a", key="save")
        self.app.receipt(tx.N_("Salvo às {time}"), "b", key="save")

        self.assertEqual(2, len(self.line.shown))

    def test_fast_manager_pause_and_resume_show_the_latest_receipt_without_toasts(self):
        self.app.enabled = True
        self.app.capture_error = None
        self.app.typed_text = "partial trigger"
        self.app.refresh_tray_state = mock.Mock()
        self.app._refresh_manager_status = mock.Mock()

        with mock.patch.object(tx.time, "time", return_value=100):
            self.app.toggle_enabled(self.app.icon, None, in_manager=True)
            self.app.toggle_enabled(self.app.icon, None, in_manager=True)

        self.assertTrue(self.app.enabled)
        self.assertEqual("", self.app.typed_text)
        self.assertEqual(2, len(self.line.shown))
        self.assertRegex(self.line.shown[0], r"^Expansão pausada às \d\d:\d\d$")
        self.assertRegex(self.line.shown[1], r"^Expansão retomada às \d\d:\d\d$")
        self.assertEqual([], self.app.icon.toasts)

    def test_replacing_the_library_resets_every_page_receipt(self):
        self.app._request_health_refresh = mock.Mock()
        self.line.reset = mock.Mock()
        another_line = mock.Mock()
        self.app._manager_receipts[".manager.another-page"] = another_line

        self.app._library_replaced()

        self.app._request_health_refresh.assert_called_once_with()
        self.line.reset.assert_called_once_with()
        another_line.reset.assert_called_once_with()

    def test_a_status_that_can_still_toast_keeps_its_cooldown(self):
        self.app.manager_window.focused = False

        self.app.notify_status("Biblioteca atualizada.", key="reload")
        self.app.notify_status("Biblioteca atualizada.", key="reload")

        self.assertEqual(["Biblioteca atualizada."], self.app.icon.toasts)

    def test_an_outcome_without_an_object_is_just_the_outcome(self):
        self.app.receipt(tx.N_("Backup criado às {time}"))

        self.assertRegex(self.line.shown[0], r"^Backup criado às \d\d:\d\d$")

    def test_a_status_from_elsewhere_is_a_receipt_only_while_the_window_has_focus(self):
        self.app.notify_status("Biblioteca atualizada.", key="reload")
        self.assertEqual(["Biblioteca atualizada."], self.line.shown)
        self.assertEqual([], self.app.icon.toasts)

        self.app.manager_window.focused = False
        self.app.notify_status("Expansão pausada.", key="toggle")
        self.assertEqual(["Biblioteca atualizada."], self.line.shown)
        self.assertEqual(["Expansão pausada."], self.app.icon.toasts)

    def test_a_closed_or_minimized_manager_leaves_status_to_the_tray(self):
        self.app._manager_visible = False

        self.app.notify_status("Biblioteca atualizada.", key="reload")

        self.assertEqual([], self.line.shown)
        self.assertEqual(["Biblioteca atualizada."], self.app.icon.toasts)

    def test_errors_always_reach_the_tray(self):
        self.app.pending_notifications = []

        self.app.notify_error("Falhou.", key="boom")

        self.assertEqual(["Falhou."], self.app.icon.toasts)
        self.assertEqual([], self.line.shown)

    def test_a_manager_that_closed_in_between_falls_back_to_the_tray(self):
        self.app._manager_receipts = {}

        self.app.receipt(tx.N_("Salvo às {time}"), "xola", key="save")

        self.assertEqual(1, len(self.app.icon.toasts))
        self.assertTrue(self.app.icon.toasts[0].startswith("Salvo às "))

    def test_a_receipt_needs_no_tray_icon(self):
        self.app.icon = None

        self.assertTrue(self.app.receipt(tx.N_("Salvo às {time}"), "xola", key="save"))

        self.assertEqual(1, len(self.line.shown))

    def test_a_status_with_no_icon_and_no_window_is_dropped_as_before(self):
        self.app.icon = None
        self.app._manager_visible = False

        self.assertFalse(self.app.notify_status("x", key="k"))
        self.assertEqual([], self.app.notification_history)


class HealthFactsTests(unittest.TestCase):
    """The app records what the health projection reads, at the place it happens."""

    GOOD_BACKUP = ("snippets-20261018-090000.json", json.dumps({"xbackup": "from backup"}))

    def test_a_library_restored_from_a_backup_is_recorded_with_what_was_set_aside(self):
        app = make_real_app(self, {}, raw="{ not json", backups=(self.GOOD_BACKUP,))

        recovery = app.library_recovery
        self.assertEqual("backup", recovery["kind"])
        self.assertTrue(recovery["quarantined"].startswith("snippets.corrupt-"))
        self.assertTrue(os.path.exists(os.path.join(app.data_dir, recovery["quarantined"])))
        self.assertEqual("2026-10-18T09:00:00", recovery["backup_at"])
        self.assertIn("xbackup", app.snippets)
        (issue,) = app._manager_issues()
        self.assertEqual("info", issue.severity)
        self.assertTrue(issue.title.startswith("Biblioteca restaurada do backup · "), issue.title)
        self.assertTrue(issue.title.endswith("18/10 09:00"), issue.title)

    def test_sample_defaults_in_use_are_recorded_as_an_error_naming_the_file(self):
        app = make_real_app(self, {}, raw="{ not json")

        recovery = app.library_recovery
        self.assertEqual("samples", recovery["kind"])
        (issue,) = app._manager_issues()
        self.assertEqual("error", issue.severity)
        self.assertIn(recovery["quarantined"], issue.body)

    def test_a_clean_start_has_nothing_to_report(self):
        app = make_real_app(self, {"xhi": "hello"})

        self.assertIsNone(app.library_recovery)
        self.assertEqual([], app._manager_issues())

    def test_a_plain_reload_does_not_forget_a_recovery(self):
        # The file on disk is valid sample data by now; the person has not
        # replaced it, so the recovery still stands.
        app = make_real_app(self, {}, raw="{ not json")
        recovery = app.library_recovery

        app.reload_snippets_from_disk()

        self.assertIs(recovery, app.library_recovery)

    def test_restoring_a_backup_or_importing_ends_a_recovery(self):
        for label, replace in (
            ("restore", lambda app, path: app.restore_backup(path)),
            ("import", lambda app, path: app.import_library(path, "replace")),
        ):
            with self.subTest(label):
                app = make_real_app(self, {}, raw="{ not json")
                source = os.path.join(app.data_dir, "wanted.json")
                with open(source, "w", encoding="utf-8") as handle:
                    json.dump({"xwanted": "text"}, handle)

                ok, error = replace(app, source)

                self.assertTrue(ok, error)
                self.assertIsNone(app.library_recovery)

    def test_a_failed_save_is_recorded_until_a_save_goes_through(self):
        app = make_real_app(self, {"xhi": "hello"})
        app._request_health_refresh = mock.Mock()

        with mock.patch.object(tx, "write_json_atomic", side_effect=OSError("disk full")):
            self.assertFalse(app.save_snippets(app.snippets))

        self.assertEqual("disk full", app.last_save_error["error"])
        self.assertRegex(app.last_save_error["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertEqual(["save-failed"], [issue.id for issue in app._manager_issues()])
        app._request_health_refresh.assert_called()

        self.assertTrue(app.save_snippets(app.snippets))
        self.assertIsNone(app.last_save_error)
        self.assertEqual([], app._manager_issues())

    def test_a_save_that_cannot_back_up_the_prior_file_is_recorded_too(self):
        app = make_real_app(self, {"xhi": "hello"})

        with mock.patch.object(tx, "create_backup", side_effect=OSError("no space")):
            self.assertFalse(app.save_snippets(app.snippets))

        self.assertEqual("no space", app.last_save_error["error"])

    def test_the_mirror_result_is_recorded_for_each_outcome(self):
        app = make_real_app(self, {"xhi": "hello"})
        self.assertIsNone(app.last_mirror)
        mirror = os.path.join(app.data_dir, "mirror")

        app.settings["mirror_dir"] = mirror
        app.mirror_snippets_file()
        self.assertTrue(app.last_mirror["ok"])
        self.assertEqual(mirror, app.last_mirror["path"])
        self.assertTrue(os.path.exists(os.path.join(mirror, "snippets.json")))

        with mock.patch.object(tx.shutil, "copyfile", side_effect=OSError("denied")):
            app.mirror_snippets_file()
        self.assertEqual((False, "denied"), (app.last_mirror["ok"], app.last_mirror["error"]))
        self.assertEqual(["mirror-failed"], [issue.id for issue in app._manager_issues()])

        app.settings.pop("mirror_dir")
        app.mirror_snippets_file()
        self.assertIsNone(app.last_mirror, "no mirror configured means nothing to report")

    def test_the_sync_export_result_is_recorded_for_each_outcome(self):
        app = make_real_app(self, {"xhi": "hello"})
        self.assertIsNone(app.last_sync)
        export_dir = os.path.join(app.data_dir, "cloud")
        os.makedirs(export_dir)

        app.settings["sync_export_dir"] = export_dir
        app.export_sync_bundle()
        self.assertTrue(app.last_sync["ok"])
        # Skipping an up-to-date bundle is still a good result.
        app.export_sync_bundle()
        self.assertTrue(app.last_sync["ok"])

        failed = ExportOutcome(tx.EXPORT_FAILED, export_dir, "disk full")
        with mock.patch.object(tx, "export_bundle_outcome", return_value=failed):
            app.export_sync_bundle()
        self.assertEqual((False, "disk full"), (app.last_sync["ok"], app.last_sync["error"]))
        self.assertEqual(["sync-failed"], [issue.id for issue in app._manager_issues()])

        app.settings["sync_export_dir"] = os.path.join(app.data_dir, "missing")
        app.export_sync_bundle()
        self.assertFalse(app.last_sync["ok"])
        self.assertIn("pasta", app.last_sync["error"])
        self.assertFalse(os.path.exists(app.settings["sync_export_dir"]), "never created")

        app.settings.pop("sync_export_dir")
        app.export_sync_bundle()
        self.assertIsNone(app.last_sync)

    def test_a_corrupt_library_makes_the_sync_export_fail_loudly(self):
        app = make_real_app(self, {"xhi": "hello"})
        export_dir = os.path.join(app.data_dir, "cloud")
        os.makedirs(export_dir)
        app.settings["sync_export_dir"] = export_dir
        with open(app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write("{ not json")

        app.export_sync_bundle()

        self.assertFalse(app.last_sync["ok"])
        self.assertTrue(app.last_sync["error"])

    def test_retrying_runs_the_mirror_and_the_export_again(self):
        app = make_real_app(self, {"xhi": "hello"})
        app.mirror_snippets_file = mock.Mock()
        app.export_sync_bundle = mock.Mock()

        app.retry_sync()

        app.mirror_snippets_file.assert_called_once_with()
        app.export_sync_bundle.assert_called_once_with()

    def test_the_facts_the_app_holds_feed_the_projection_and_a_dismissal_hides_info(self):
        app = make_real_app(self, {"xhi": "hello"})
        app.enabled = False
        app.library_recovery = {
            "kind": "backup", "at": "2026-10-20T10:00:00", "backup_at": None, "quarantined": None}
        app.shadowed_static_snippets = {"xdup": "text"}

        self.assertEqual(
            ["paused", "shadowed", "restored:2026-10-20T10:00:00"],
            [issue.id for issue in app._manager_issues()])
        app._dismissed_health.add("restored:2026-10-20T10:00:00")
        self.assertEqual(["paused", "shadowed"], [issue.id for issue in app._manager_issues()])

    def test_every_action_an_issue_offers_has_a_handler(self):
        app = make_real_app(self, {"xhi": "hello"})
        app.toggle_enabled = mock.Mock()
        app.open_data_folder = mock.Mock()
        app.open_log = mock.Mock()
        app.retry_sync = mock.Mock()
        app._refresh_manager_health = mock.Mock()
        app._show_manager_page = mock.Mock()
        import health_support

        for action in (health_support.RESUME, health_support.OPEN_BACKUPS,
                       health_support.OPEN_FOLDER, health_support.OPEN_LOG,
                       health_support.RETRY_SYNC, health_support.OPEN_DYNAMIC):
            with self.subTest(action):
                app._run_health_action(action)
        app.toggle_enabled.assert_called_once_with(app.icon, None, in_manager=True)
        app.open_data_folder.assert_called_once_with()
        app.open_log.assert_called_once_with()
        app.retry_sync.assert_called_once_with()
        self.assertEqual(
            [mock.call("backups"), mock.call("dynamic")], app._show_manager_page.call_args_list)
        with self.assertRaises(ValueError):
            app._run_health_action("nope")


class BundledRegistryManagerTests(unittest.TestCase):
    """The manager against the real bundled providers, not a hand-built map."""

    def setUp(self):
        self.app = make_real_app(self, {
            "xhi": "hello",
            "_codes": {"__prefix__": "c", "city": "Cidade"},
        })

    def test_library_actions_keep_every_bundled_provider_by_reference(self):
        # Regression: these raised "cannot pickle '_thread.RLock'" because
        # every bound provider was deep-copied into the working copy.
        app = self.app
        providers = {key: value for key, value in app.snippets.items() if callable(value)}
        self.assertIn("xhoje", providers)
        self.assertIn("xdolar", providers)
        metadata = app.library_metadata
        for name, operation in (
            ("toggle_favorite",
             lambda: manager_actions.toggle_favorite(app.snippets, metadata, "xhi", True)),
            ("create_group",
             lambda: manager_actions.create_group(app.snippets, metadata, group_id="g", label="G")),
            ("duplicate_static",
             lambda: manager_actions.duplicate_static(app.snippets, metadata, "xhi", "xhi2")),
            ("rename_static",
             lambda: manager_actions.rename_static(app.snippets, metadata, "xhi", "xola")),
            ("set_form",
             lambda: manager_actions.set_form(app.snippets, metadata, "xhi", {"fields": []})),
            ("toggle_mapping_favorite",
             lambda: manager_actions.toggle_mapping_favorite(
                 app.snippets, metadata, "_codes", "city", True)),
        ):
            with self.subTest(name):
                result = operation()
                for key, provider in providers.items():
                    self.assertIs(provider, result.snippets[key], key)

    def test_registry_toggle_refreshes_the_open_manager_and_exports(self):
        # Regression: _refresh_manager_lists took no root, so a GUI-thread
        # submit raised TypeError before the sync export and the receipt.
        app = self.app
        app.gui = InlineGui()
        app.manager_window = object()
        refresher = mock.Mock()
        app._manager_refreshers = [refresher]
        app.export_sync_bundle = mock.Mock()
        app.notify_status = mock.Mock()

        self.assertTrue(app._toggle_registry_entry("xhoje", False))

        refresher.assert_called_once_with()
        app.export_sync_bundle.assert_called_once_with()
        app.notify_status.assert_called_once()
        self.assertNotIn("xhoje", app.snippets)

    def test_tray_reload_refreshes_the_open_manager_before_its_receipt(self):
        app = self.app
        app.gui = InlineGui()
        app.manager_window = object()
        refresher = mock.Mock()
        app._manager_refreshers = [refresher]
        app.notify_status = mock.Mock()
        app.notify_error = mock.Mock()

        app.reload_snippets(None, None)

        refresher.assert_called_once_with()
        app.notify_error.assert_not_called()
        app.notify_status.assert_called_once_with(
            "Biblioteca atualizada.", key="reload-snippets",
        )

    def test_tray_reload_keeps_the_library_when_a_draft_is_kept(self):
        app = self.app
        app.gui = InlineGui()
        app.manager_window = object()
        refresher = mock.Mock()
        app._manager_refreshers = [refresher]
        draft = mock.Mock()
        draft.resolve.return_value = False
        app._manager_editors = [draft]
        app.load_snippets = mock.Mock()
        app.notify_status = mock.Mock()

        app.reload_snippets(None, None)

        draft.resolve.assert_called_once_with(app.manager_window)
        app.load_snippets.assert_not_called()
        refresher.assert_not_called()
        app.notify_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
