"""Headless seams for manager navigation and persistence orchestration."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_module import sniptype as tx
from manager_actions import toggle_favorite
from workflow_support import SnippetRef


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
        return app

    def test_manager_target_resolves_stable_static_mapping_and_dynamic_refs(self):
        app = self._app()
        self.assertEqual("static", tx.Sniptype._manager_target(app, SnippetRef("static", "hello")).kind)
        mapping = tx.Sniptype._manager_target(app, SnippetRef("mapping", "city", "_codes"))
        self.assertEqual("mapping", mapping.kind)
        self.assertEqual("ccity", mapping.effective_trigger)
        self.assertEqual("dynamic", tx.Sniptype._manager_target(app, SnippetRef("dynamic", "xdate")).kind)

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


if __name__ == "__main__":
    unittest.main()
