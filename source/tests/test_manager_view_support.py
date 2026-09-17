import unittest

from manager_view_support import (
    FILTER_FAVORITES,
    FILTER_RECENT,
    UNGROUPED_FILTER,
    build_manager_rows,
    filter_manager_rows,
    find_manager_target,
    format_trigger_pair,
)
from workflow_support import SnippetRef, WorkflowState


class ManagerRowBuildTests(unittest.TestCase):
    def test_builds_ordered_immutable_rows_for_static_mapping_and_dynamic_items(self):
        snippets = {
            "xhello": "Hello",
            "_codes": {"acme": "A-1", "__prefix__": "cod"},
            "xdate": lambda: "today",
        }
        metadata = {
            "groups": {"work": {"label": "Work", "prefix": "w"}},
            "items": {
                "static": {"xhello": {"group_id": "work", "favorite": True}},
                "mappings": {"_codes": {"acme": {"favorite": True}}},
            },
        }
        registry = {"xdate": {"provider": "datetime", "trigger": "xnow"}}

        rows = build_manager_rows(snippets, metadata, registry)

        self.assertEqual(
            (SnippetRef("static", "xhello"),
             SnippetRef("mapping", "acme", "_codes"),
             SnippetRef("dynamic", "xdate")),
            tuple(row.ref for row in rows),
        )
        self.assertEqual("wxhello", rows[0].effective_trigger)
        self.assertEqual("Work", rows[0].group_label)
        self.assertTrue(rows[0].favorite)
        self.assertEqual("codacme", rows[1].effective_trigger)
        self.assertTrue(rows[1].favorite)
        self.assertEqual("xnow", rows[2].effective_trigger)
        self.assertFalse(rows[2].favorite)
        self.assertEqual("xhello → wxhello", format_trigger_pair(rows[0]))
        self.assertEqual("acme → codacme", format_trigger_pair(rows[1]))
        self.assertEqual("xdate → xnow", format_trigger_pair(rows[2]))
        with self.assertRaises(AttributeError):
            rows[0].favorite = False

    def test_reserved_metadata_mapping_containers_and_callables_are_not_static_rows(self):
        rows = build_manager_rows(
            {
                "plain": "value",
                "__sniptype__": {"groups": {}},
                "_codes": {"item": "value"},
                "dynamic": lambda: "value",
            }
        )

        static_rows = tuple(row for row in rows if row.kind == "static")
        self.assertEqual(("plain",), tuple(row.stored_trigger for row in static_rows))
        self.assertEqual("static", static_rows[0].kind)


class ManagerFilterTests(unittest.TestCase):
    def setUp(self):
        self.rows = build_manager_rows(
            {
                "one": "1",
                "two": "2",
                "_codes": {"city": "GYN"},
                "xnow": lambda: "now",
            },
            {
                "groups": {"work": {"label": "Work"}},
                "items": {
                    "static": {
                        "one": {"favorite": True, "group_id": "work"},
                        "two": {"favorite": False},
                    },
                    "mappings": {"_codes": {"city": {"favorite": True}}},
                },
            },
            {"xnow": {"provider": "datetime"}},
        )

    def test_favorites_include_static_and_mapping_but_not_registry_dynamic(self):
        favorite_rows = filter_manager_rows(self.rows, FILTER_FAVORITES)

        self.assertEqual(
            (SnippetRef("static", "one"), SnippetRef("mapping", "city", "_codes")),
            tuple(row.ref for row in favorite_rows),
        )

    def test_recent_follows_workflow_order_and_skips_deleted_rows(self):
        state = WorkflowState()
        state.record_success(SnippetRef("dynamic", "xnow"))
        state.record_success(SnippetRef("static", "deleted"))
        state.record_success(SnippetRef("mapping", "city", "_codes"))

        recent_rows = filter_manager_rows(self.rows, FILTER_RECENT, workflow_state=state)

        self.assertEqual(
            (SnippetRef("mapping", "city", "_codes"), SnippetRef("dynamic", "xnow")),
            tuple(row.ref for row in recent_rows),
        )

    def test_group_filter_applies_only_to_direct_static_rows(self):
        work_rows = filter_manager_rows(self.rows, "group", group_id="work")
        work_rows_by_id = filter_manager_rows(self.rows, group_id="work")

        self.assertEqual((SnippetRef("static", "one"),), tuple(row.ref for row in work_rows))
        self.assertEqual(tuple(work_rows), tuple(work_rows_by_id))

    def test_ungrouped_filter_is_explicit_and_excludes_mapping_rows(self):
        rows = filter_manager_rows(self.rows, UNGROUPED_FILTER)

        self.assertEqual(
            (SnippetRef("static", "two"),),
            tuple(row.ref for row in rows),
        )


class ManagerNavigationTests(unittest.TestCase):
    def test_navigation_descriptors_select_static_mapping_and_dynamic_rows(self):
        rows = build_manager_rows(
            {"hello": "Hello", "_codes": {"city": "GYN"}, "xdate": lambda: "today"},
            {},
            {"xdate": {"provider": "datetime", "trigger": "xnow"}},
        )

        static_target = find_manager_target(rows, SnippetRef("static", "hello"))
        mapping_target = find_manager_target(rows, SnippetRef("mapping", "city", "_codes"))
        dynamic_target = find_manager_target(rows, SnippetRef("dynamic", "xdate"))

        self.assertEqual(("static", "hello", "hello"),
                         (static_target.tab, static_target.row_id, static_target.effective_trigger))
        self.assertEqual(("mapping", "_codes:city", "codescity"),
                         (mapping_target.tab, mapping_target.row_id, mapping_target.effective_trigger))
        self.assertEqual(("dynamic", "xdate", "xnow"),
                         (dynamic_target.tab, dynamic_target.row_id, dynamic_target.effective_trigger))
        self.assertIsNone(find_manager_target(rows, SnippetRef("static", "deleted")))


if __name__ == "__main__":
    unittest.main()
