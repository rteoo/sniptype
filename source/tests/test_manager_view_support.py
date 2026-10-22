import unittest

from manager_view_support import (
    FILTER_FAVORITES,
    FILTER_DISABLED,
    FILTER_PROBLEMS,
    FILTER_RECENT,
    UNGROUPED_FILTER,
    build_manager_rows,
    filter_manager_rows,
    filter_static_rows,
    find_manager_target,
    format_trigger_pair,
    manager_row_preview,
    search_manager_rows,
)
from workflow_support import SnippetRef, WorkflowState


class ManagerRowBuildTests(unittest.TestCase):
    def test_direct_statics_win_mapping_routes_and_only_live_dynamics_shadow(self):
        rows = build_manager_rows(
            {"codeitem": "Static wins", "_codes": {"__prefix__": "code", "item": "Mapping"},
             "xdisabled": "Still active", "xlive": lambda: "Runtime"},
            dynamic_registry={"xdisabled": {"provider": "datetime", "enabled": False}},
            shadowed_statics={"xlive": "Preserved"},
        )
        static = {row.key: row for row in rows if row.kind == "static"}
        self.assertFalse(static["codeitem"].shadowed)
        self.assertFalse(static["xdisabled"].shadowed)
        self.assertTrue(static["xlive"].shadowed)

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
    def test_disabled_and_conflicting_rows_keep_their_distinct_causes(self):
        rows = build_manager_rows(
            {"off": "saved", "collision": lambda: "runtime", "normal": "saved"},
            {"groups": {"off-group": {"label": "Disabled", "enabled": False}},
             "items": {"static": {"off": {"group_id": "off-group"}}}},
            shadowed_statics={"collision": "preserved"},
        )
        self.assertEqual(["off"], [row.key for row in filter_manager_rows(rows, FILTER_DISABLED)])
        self.assertEqual(["collision"], [row.key for row in filter_manager_rows(rows, FILTER_PROBLEMS)])
        self.assertTrue(next(row for row in rows if row.kind == "dynamic").enabled)

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


class StaticSearchTests(unittest.TestCase):
    def _search(self, snippets, query, metadata=None):
        rows = build_manager_rows(snippets, metadata)
        return [row.stored_trigger for row in filter_static_rows(rows, query, snippets)]

    def test_the_effective_trigger_the_list_shows_is_searchable(self):
        # Regression: "sig → assig" was listed but "assig" found nothing.
        metadata = {
            "groups": {"mail": {"label": "Mail", "prefix": "as"}},
            "items": {"static": {"sig": {"group_id": "mail"}}, "mappings": {}},
        }

        self.assertEqual(["sig"], self._search({"sig": "Atenciosamente"}, "assig", metadata))

    def test_a_blank_query_keeps_every_static_row_in_trigger_order(self):
        snippets = {
            "xname": "Alex", "_cpf_numbers": {"fulano": "123"},
            "xdyn": lambda: "value", "xemail": "a@b.com",
        }
        for query in ("", "   \t "):
            with self.subTest(query=query):
                self.assertEqual(["xemail", "xname"], self._search(snippets, query))

    def test_triggers_rank_before_groups_and_content_then_exact_prefix_substring(self):
        snippets = {
            "zz": "texto com mail no meio",
            "xmail2": "segundo",
            "amail": "termina em mail",
            "mail": "exato",
            "grouped": "nada",
            "mailbox": "prefixo",
        }
        metadata = {
            "groups": {"g": {"label": "Mail"}},
            "items": {"static": {"grouped": {"group_id": "g"}}, "mappings": {}},
        }

        self.assertEqual(
            ["mail", "mailbox", "amail", "xmail2", "grouped", "zz"],
            self._search(snippets, "MAIL", metadata),
        )

    def test_ungrouped_rows_do_not_match_the_placeholder_group_label(self):
        self.assertEqual([], self._search({"xhi": "hello"}, "ungrouped"))

    def test_content_matching_follows_the_literal_case_insensitive_rules(self):
        rich_signature = {
            "__kind__": "rich_text",
            "text": "Assinatura principal",
            "spans": [],
        }
        for case, snippets, query, expected in (
            ("matches key and value",
             {"xname": "Alex", "xemail": "contato@example.com"}, "example", ["xemail"]),
            ("matches key and value",
             {"xname": "Alex", "xemail": "contato@example.com"}, "name", ["xname"]),
            ("matches rich text plain value", {"xsig": rich_signature}, "assinatura", ["xsig"]),
            # A blind re.search would treat "(net)" as a group and ".*" as
            # match-all; the filter must compare literally.
            ("literal, not a regex",
             {"xa": "Total (net) due", "xb": "plain text"}, "(net)", ["xa"]),
            ("literal, not a regex", {"xa": "Total (net) due", "xb": "plain text"}, ".*", []),
            ("metacharacter does not raise", {"xa": "array[0] value"}, "[", ["xa"]),
            ("case-insensitive",
             {"xinsc": "Inscrição estadual", "xother": "Cadastro"}, "INSCRIÇÃO", ["xinsc"]),
            ("accent-sensitive",
             {"xinsc": "Inscrição estadual", "xother": "Cadastro"}, "inscricao", []),
            ("unicode key", {"xcafé": "espresso"}, "CAFÉ", ["xcafé"]),
        ):
            with self.subTest(case, query=query):
                self.assertEqual(expected, self._search(snippets, query))


class SwitcherSearchTests(unittest.TestCase):
    def test_searches_all_kinds_and_saved_text_without_running_providers(self):
        def forbidden():
            self.fail("Searching must never execute a provider")

        snippets = {"sig": "Signature", "_codes": {"__prefix__": "code", "mail": "Saved signature"},
                    "clock": forbidden}
        metadata = {"groups": {"g": {"label": "Mail", "prefix": "as"}},
                    "items": {"static": {"sig": {"group_id": "g"}}}}
        rows = build_manager_rows(snippets, metadata, {"clock": {"trigger": "now"}})
        self.assertEqual(["sig"], [r.key for r in search_manager_rows(rows, "ASSIG", snippets)])
        self.assertEqual(["mail", "sig"], [r.key for r in search_manager_rows(rows, "mail", snippets)])
        self.assertEqual(["sig", "mail"], [r.key for r in search_manager_rows(rows, "signature", snippets)])
        self.assertEqual(["clock"], [r.key for r in search_manager_rows(rows, "now", snippets)])
        self.assertEqual("", manager_row_preview(rows[-1], snippets))
        self.assertEqual(rows, search_manager_rows(rows, "  ", snippets))

    def test_equal_effective_triggers_remain_distinct_and_queries_are_literal(self):
        snippets = {"codeitem": "Static [value]", "_codes": {"__prefix__": "code", "item": "Mapping"}}
        rows = build_manager_rows(snippets)
        self.assertEqual(["static", "mapping"],
                         [r.kind for r in search_manager_rows(rows, "codeitem", snippets)])
        self.assertEqual(["codeitem"], [r.key for r in search_manager_rows(rows, "[", snippets)])
        self.assertEqual((), search_manager_rows(rows, ".*", snippets))


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
