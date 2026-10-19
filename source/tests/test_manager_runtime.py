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
from workflow_support import SnippetRef

SOURCE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class InlineGui:
    """A GuiThread stand-in that runs work inline, as submit does on the GUI thread."""

    def __init__(self):
        self.root = object()

    def submit(self, func):
        func(self.root)


def make_real_app(test, snippets):
    """A real Sniptype on a temporary data home with the bundled dynamic registry."""
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
        json.dump(snippets, handle)
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

    def test_tray_reload_queues_open_manager_refresh_on_gui_thread(self):
        app = self._app()
        app.manager_window = object()
        app.gui = mock.Mock()
        app.load_snippets = mock.Mock(return_value={"updated": "value"})
        app.notify_status = mock.Mock()

        tx.Sniptype.reload_snippets(app, None, None)

        self.assertEqual({"updated": "value"}, app.snippets)
        app.refresh_runtime_indexes.assert_called_once_with()
        app.gui.submit.assert_called_once_with(app._refresh_manager_lists)

    def test_release_manager_ui_refs_drops_widget_callbacks_and_controllers(self):
        app = self._app()
        app._manager_notebook = object()
        app.manager_window = object()
        app._manager_refreshers = [object()]
        app._manager_tab_selectors = {"static": object()}
        app._manager_preview_controller = object()

        tx.Sniptype._release_manager_ui_refs(app)

        self.assertIsNone(app._manager_notebook)
        self.assertIsNone(app.manager_window)
        self.assertEqual([], app._manager_refreshers)
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

        app.toggle_enabled(None, None)

        self.assertFalse(app.enabled)
        app.gui.submit.assert_called_once_with(app._refresh_manager_status)
        app._manager_status_var.set.assert_not_called()
        app._refresh_manager_status()
        app._manager_status_var.set.assert_called_once_with("Expansão pausada")
        app._manager_toggle_button.configure.assert_called_once_with(
            text="Retomar expansão"
        )

    def test_capture_failure_shows_on_the_manager_and_disables_the_toggle(self):
        app = self._app()
        app.enabled = False
        app.capture_error = OSError("hook unavailable")
        app._manager_status_var = mock.Mock()
        app._manager_toggle_button = mock.Mock()

        with mock.patch.object(tx.ui_widgets, "set_icon") as set_icon:
            app._refresh_manager_status()

        app._manager_status_var.set.assert_called_once_with("Captura de teclado falhou")
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
            "Snippets recarregados com sucesso.", key="reload-snippets",
        )


if __name__ == "__main__":
    unittest.main()
