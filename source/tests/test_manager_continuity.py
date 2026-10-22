"""Manager continuity contracts without constructing a Tk interpreter."""

import os
import sys
import types
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_module import sniptype as tx
from manager_view_support import geometry_intersects_monitors, manager_geometry_for_tk
from workflow_support import SnippetRef, WorkflowState


class ManagerContinuityTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(tx.Sniptype)
        self.app.snippets = {"xfirst": "Synthetic first response"}
        self.app.library_metadata = {}
        self.app.dynamic_registry = {}
        self.app.shadowed_static_snippets = {}
        self.app.trigger_index = {"direct_targets": []}
        self.app.rebuild_trigger_index = mock.Mock()
        self.app._refresh_manager_lists = mock.Mock()
        self.app._manager_rows_revision = 0
        self.app._manager_rows_cache = None
        self.app._manager_search_jobs = {}
        self.app._manager_pending_search = {}
        self.app._manager_appearance_poll = None

    def test_projection_reuses_revision_and_publishes_manager_changes_after_save(self):
        initial = self.app._manager_rows()
        self.assertIs(initial, self.app._manager_rows())
        result = types.SimpleNamespace(snippets={"xsecond": "Synthetic second response"}, metadata={})
        def save(*_args, **_kwargs):
            # A save may cause a refresh before its caller publishes the new map.
            self.app._invalidate_manager_rows()
            self.assertEqual(["xfirst"], [row.key for row in self.app._manager_rows()])
            return True
        self.app.save_snippets = mock.Mock(side_effect=save)
        self.assertTrue(self.app._persist_manager_action(result))
        self.assertEqual(["xsecond"], [row.key for row in self.app._manager_rows()])
        self.assertIsNot(initial, self.app._manager_rows())

    def test_failed_manager_write_keeps_published_rows_and_cache(self):
        initial = self.app._manager_rows()
        self.app.save_snippets = mock.Mock(return_value=False)
        result = types.SimpleNamespace(snippets={"xunwritten": "Never persisted"}, metadata={})
        self.assertFalse(self.app._persist_manager_action(result))
        self.assertIs(initial, self.app._manager_rows())
        self.assertEqual({"xfirst": "Synthetic first response"}, self.app.snippets)

    def test_disk_reload_invalidates_after_replacing_library(self):
        old = self.app._manager_rows()
        self.app.load_snippets = mock.Mock(return_value={"xloaded": "Synthetic restored response"})
        self.app.reload_snippets_from_disk()
        self.assertEqual(["xloaded"], [row.key for row in self.app._manager_rows()])
        self.assertIsNot(old, self.app._manager_rows())

    def test_real_save_restore_import_and_registry_publication_retire_cached_rows(self):
        from test_manager_runtime import make_real_app
        app = make_real_app(self, {"xoriginal": "Synthetic original"})
        initial = app._manager_rows()
        backup = app.backup_now()
        self.assertIsNotNone(backup)
        app.snippets["xsaved"] = "Synthetic saved"
        self.assertTrue(app.save_snippets(app.snippets))
        saved = app._manager_rows()
        self.assertIsNot(initial, saved)
        self.assertIn(SnippetRef("static", "xsaved"), {row.ref for row in saved})
        ok, error = app.restore_backup(backup)
        self.assertTrue(ok, error)
        restored = app._manager_rows()
        self.assertIsNot(saved, restored)
        self.assertNotIn(SnippetRef("static", "xsaved"), {row.ref for row in restored})
        ok, error = app.apply_import(({"ximported": "Synthetic imported"}, {}), "replace")
        self.assertTrue(ok, error)
        imported = app._manager_rows()
        self.assertIsNot(restored, imported)
        self.assertIn(SnippetRef("static", "ximported"), {row.ref for row in imported})
        app.dynamic_registry = {"xsynthetic": {"trigger": "xrenamed", "enabled": True}}
        app.refresh_runtime_indexes()
        self.assertIn("xrenamed", {row.effective_trigger for row in app._manager_rows()})
        self.assertIsNot(imported, app._manager_rows())

    def test_real_failed_atomic_save_keeps_published_projection(self):
        from test_manager_runtime import make_real_app
        app = make_real_app(self, {"xoriginal": "Synthetic original"})
        initial = app._manager_rows()
        with mock.patch.object(tx, "write_json_atomic", side_effect=OSError("synthetic denied")):
            self.assertFalse(app.save_snippets({"xunwritten": "Never persisted"}))
        self.assertIs(initial, app._manager_rows())
        self.assertIn(SnippetRef("static", "xoriginal"), {row.ref for row in app._manager_rows()})

    def test_debounce_coalesces_and_withdraw_cancels_without_rescheduling(self):
        window = mock.Mock()
        window.winfo_viewable.return_value = True
        window.after.side_effect = ("first", "second")
        first, latest = mock.Mock(), mock.Mock()
        self.app._schedule_manager_search(window, "static", first)
        self.app._schedule_manager_search(window, "static", latest)
        window.after_cancel.assert_called_once_with("first")
        self.assertEqual([100, 100], [call.args[0] for call in window.after.call_args_list])
        self.app._cancel_manager_search(window)
        window.after_cancel.assert_called_with("second")
        window.winfo_viewable.return_value = False
        self.app._schedule_manager_search(window, "static", latest)
        self.assertEqual(2, window.after.call_count)
        first.assert_not_called()
        latest.assert_not_called()
        window.winfo_viewable.return_value = True
        self.app._flush_manager_search()
        latest.assert_called_once_with()

    def test_render_that_loses_visibility_keeps_latest_query_for_reopen(self):
        window = mock.Mock()
        window.winfo_viewable.return_value = True
        callback = mock.Mock()
        self.app._schedule_manager_search(window, "static", callback)
        render = window.after.call_args.args[1]
        window.winfo_viewable.return_value = False
        render()
        callback.assert_not_called()
        self.assertEqual({}, self.app._manager_search_jobs)
        self.app._flush_manager_search()
        callback.assert_called_once_with()

    def test_cancel_only_removes_timers_owned_by_the_window(self):
        manager, picker = mock.Mock(), mock.Mock()
        self.app._schedule_manager_search(manager, "static", mock.Mock())
        self.app._schedule_manager_search(picker, "switcher", mock.Mock())
        self.app._cancel_manager_search(manager)
        self.assertEqual({"switcher"}, set(self.app._manager_search_jobs))
        manager.after_cancel.assert_called_once()
        picker.after_cancel.assert_not_called()

    def test_keyed_flush_renders_current_query_once_without_touching_other_collections(self):
        window = mock.Mock()
        static, mapping = mock.Mock(), mock.Mock()
        window.after.side_effect = ("static-job", "mapping-job")
        self.app._schedule_manager_search(window, "static", static)
        self.app._schedule_manager_search(window, "mapping", mapping)
        self.app._flush_manager_search("static")
        window.after_cancel.assert_called_once_with("static-job")
        static.assert_called_once_with()
        mapping.assert_not_called()
        self.assertEqual({"mapping"}, set(self.app._manager_pending_search))
        self.assertEqual({"mapping"}, set(self.app._manager_search_jobs))
        self.app._flush_manager_search("static")
        static.assert_called_once_with()

    def test_close_cancel_and_failed_view_write_leave_window_open(self):
        window = mock.Mock()
        self.app._resolve_manager_drafts = mock.Mock(return_value=False)
        self.app._persist_settings = mock.Mock(return_value=False)
        self.app._capture_manager_view = mock.Mock(return_value={"page": "mapping"})
        self.assertFalse(self.app._hide_manager_window(window))
        self.app._persist_settings.assert_not_called()
        self.app._resolve_manager_drafts.return_value = True
        with mock.patch.object(tx.ui_widgets, "alert") as alert:
            self.assertFalse(self.app._hide_manager_window(window))
        alert.assert_called_once()
        window.withdraw.assert_not_called()

    def test_close_persists_before_withdraw_and_cancels_poll_and_search(self):
        window = mock.Mock()
        self.app._manager_appearance_poll = (window, "poll")
        self.app._manager_search_jobs = {"static": (window, "search")}
        self.app._capture_manager_view = mock.Mock(return_value={"page": "mapping"})
        self.app._resolve_manager_drafts = mock.Mock(return_value=True)
        def persist(update):
            window.withdraw.assert_not_called()
            self.assertEqual({"manager_view": {"page": "mapping"}}, update)
            return True
        self.app._persist_settings = mock.Mock(side_effect=persist)
        self.assertTrue(self.app._hide_manager_window(window))
        self.assertEqual([mock.call("poll"), mock.call("search")], window.after_cancel.call_args_list)
        window.withdraw.assert_called_once_with()
        self.assertIsNone(self.app._manager_appearance_poll)
        self.assertEqual({}, self.app._manager_search_jobs)

    def test_hidden_window_starts_no_appearance_loop(self):
        window = mock.Mock()
        window.winfo_viewable.return_value = False
        self.app._start_system_appearance_poll(window)
        window.after.assert_not_called()
        self.assertIsNone(self.app._manager_appearance_poll)

    def test_remap_reuses_command_bindings_and_new_controls_still_receive_commands(self):
        class Widget:
            def __init__(self, name, owner=None):
                self.name, self.owner = name, owner or self
                self.tags, self.children = (name, "Frame", "all"), []
                self.child_reads, self.bindings, self.commands = 0, {}, {}

            def __str__(self):
                return self.name

            def bindtags(self, tags=None):
                if tags is not None:
                    self.tags = tags
                return self.tags

            def winfo_children(self):
                self.child_reads += 1
                return self.children

            def winfo_toplevel(self):
                return self.owner

            def grab_current(self):
                return None

            def bind(self, sequence, callback, **_kwargs):
                self.bindings[sequence] = callback

            def bind_class(self, tag, sequence, callback):
                self.commands[tag, sequence] = callback

        window = Widget(".manager")
        child = Widget(".manager.existing", window)
        window.children.append(child)
        notebook = mock.Mock()
        notebook.select.return_value = "static-page"
        new_action = mock.Mock()
        self.app._manager_commands = {"static-page": {"new": new_action}}
        self.app._manager_edit_last_control = mock.Mock()
        self.app._shortcut_hint = mock.Mock()
        self.app._bind_manager_commands(window, notebook)
        initial_reads = window.child_reads, child.child_reads
        for widget in (window, child, window):
            window.bindings["<Map>"](types.SimpleNamespace(widget=widget))
        self.assertEqual((window.child_reads, child.child_reads), initial_reads)

        added = Widget(".manager.new_notice_action", window)
        child.children.append(added)
        window.bindings["<Map>"](types.SimpleNamespace(widget=added))
        tag = "ManagerCommands:" + str(window)
        self.assertEqual(added.bindtags().count(tag), 1)
        self.assertEqual(window.commands[tag, "<Control-n>"](
            types.SimpleNamespace(widget=added)), "break")
        new_action.assert_called_once_with()

    def test_restore_checks_the_current_monitor_inventory_every_time(self):
        window = mock.Mock()
        self.app._manager_pages = {"mapping": "mapping-tab"}
        self.app._manager_notebook = mock.Mock()
        self.app._manager_views = {}
        self.app._manager_monitors = mock.Mock(side_effect=[[(0, 0, 1920, 1080)], []])
        view = {"page": "mapping", "geometry": "800x600+20+20"}
        self.app._restore_manager_view(window, view)
        window.geometry.assert_called_once_with(view["geometry"])
        window.geometry.reset_mock()
        self.app._restore_manager_view(window, view)
        window.geometry.assert_not_called()
        self.assertEqual(2, self.app._manager_monitors.call_count)

    def test_quit_is_marshaled_and_cancel_preserves_the_app(self):
        window = self.app.manager_window = mock.Mock()
        self.app.gui = mock.Mock()
        self.app.task_runner = mock.Mock()
        self.app._resolve_manager_drafts = mock.Mock(return_value=False)
        icon = mock.Mock()
        self.app.quit_app(icon, None)
        self.app.gui.submit.assert_called_once()
        self.app.gui.submit.call_args.args[0](mock.Mock())
        window.destroy.assert_not_called()
        self.app.task_runner.start.assert_not_called()

    def test_quit_releases_ui_before_destroy_then_stops_off_gui_thread(self):
        window = self.app.manager_window = mock.Mock()
        self.app.task_runner = mock.Mock()
        self.app._resolve_manager_drafts = mock.Mock(return_value=True)
        self.app._persist_settings = mock.Mock(return_value=True)
        self.app._capture_manager_view = mock.Mock(return_value={})
        self.app._release_manager_ui_refs = mock.Mock()
        icon = mock.Mock()
        with mock.patch.object(tx.gc, "collect") as collect:
            self.app._quit_with_manager(icon)
        self.app._release_manager_ui_refs.assert_called_once_with()
        window.destroy.assert_called_once_with()
        collect.assert_called_once_with()
        self.app.task_runner.start.assert_called_once_with(self.app._finish_quit, icon, name="quit-app")

    def test_edit_last_requires_existing_target_and_shows_date_and_time(self):
        self.app.workflow_state = WorkflowState()
        self.app._manager_edit_last_control = mock.Mock()
        self.app._manager_last_expansion_var = mock.Mock()
        with mock.patch.object(tx, "_set_enabled") as enabled:
            self.app._refresh_edit_last()
            enabled.assert_called_with(self.app._manager_edit_last_control, False)
            self.app.workflow_state.record_success(SnippetRef("static", "xfirst"))
            self.app._last_successful_expansion_at = datetime(2026, 10, 20, 14, 35)
            self.app._refresh_edit_last()
            enabled.assert_called_with(self.app._manager_edit_last_control, True)
            stamp = self.app._manager_last_expansion_var.set.call_args.args[0]
            self.assertIn("20/10", stamp)
            self.assertIn("14:35", stamp)
            self.app.snippets = {}
            self.app._invalidate_manager_rows()
            self.app._refresh_edit_last()
            enabled.assert_called_with(self.app._manager_edit_last_control, False)

    def test_geometry_requires_a_real_monitor_not_the_virtual_desktop_gap(self):
        monitors = [(-1920, 0, 0, 1080), (1000, 0, 2920, 1080)]
        self.assertTrue(geometry_intersects_monitors("1180x760-1500+20", monitors))
        self.assertFalse(geometry_intersects_monitors("800x600+100+20", monitors))
        self.assertFalse(geometry_intersects_monitors("800x600+5000+20", monitors))
        self.assertFalse(geometry_intersects_monitors("800x600+0+1080", monitors))
        self.assertFalse(geometry_intersects_monitors("800x600+0+0", []))
        self.assertFalse(geometry_intersects_monitors("bad geometry", monitors))

    def test_absolute_negative_coordinates_use_explicit_tk_left_top_offsets(self):
        self.assertEqual("1180x760+-1400+20", manager_geometry_for_tk("1180x760-1400+20"))
        self.assertEqual("800x600+-1400+-700", manager_geometry_for_tk("800x600-1400-700"))
        self.assertEqual("800x600+100+20", manager_geometry_for_tk("800x600+100+20"))
        self.assertIsNone(manager_geometry_for_tk("800x600+-1400+20"))

    def test_capture_uses_absolute_frame_position_instead_of_wm_edge_offsets(self):
        window = mock.Mock()
        window.winfo_width.return_value = 800
        window.winfo_height.return_value = 600
        window.winfo_x.return_value = -1400
        window.winfo_y.return_value = -700
        self.app._manager_notebook = mock.Mock()
        self.app._manager_notebook.select.return_value = "static-tab"
        self.app._manager_pages = {"static": "static-tab"}
        self.app._manager_views = {}
        view = self.app._capture_manager_view(window)
        self.assertEqual("800x600-1400-700", view["geometry"])
        window.geometry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
