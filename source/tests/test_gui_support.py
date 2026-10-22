import unittest
from unittest import mock

from gui_support import (
    focus_modal_input,
    iter_filtered_mapping_items,
    snippet_row_values,
)
import gui_support


class TreeScrollAnchorTests(unittest.TestCase):
    class Tree:
        def __init__(self, rows=None, first=41, total=81):
            self.rows = tuple(rows if rows is not None else (f"sample{i:03d}" for i in range(80)))
            self.first, self.total = first, total
            self.operations = []

        def get_children(self):
            return self.rows

        def yview(self, *args):
            if args:
                self.operations.append(("row", args[0]))
                self.first = args[0]
            return self.first / self.total, min(1, (self.first + 10) / self.total)

        def yview_moveto(self, fraction):
            self.operations.append(("fraction", fraction))
            self.first = int(fraction * self.total + 0.5)

        def bbox(self, row):
            index = self.rows.index(row)
            return (0, (index - self.first) * 20, 100, 20) if self.first <= index < self.first + 10 else ()

    def test_row_identity_survives_81_to_80_total_when_fraction_loses_one_row(self):
        source = self.Tree()
        state = gui_support.capture_tree_scroll(source)
        self.assertEqual({"scroll": 41 / 81, "top_row": "sample041"}, state)
        legacy = self.Tree(first=0, total=80)
        gui_support.restore_tree_scroll(legacy, {"scroll": state["scroll"]})
        self.assertEqual(40, legacy.first)
        restored = self.Tree(first=0, total=80)
        gui_support.restore_tree_scroll(restored, state)
        self.assertEqual([("row", 41)], restored.operations)
        self.assertEqual(source.bbox("sample041"), restored.bbox("sample041"))

    def test_legacy_missing_deleted_and_detached_anchors_keep_fraction_fallback(self):
        for anchor in (None, "deleted", "detached"):
            with self.subTest(anchor=anchor):
                tree = self.Tree(rows=("attached",), first=0, total=1)
                # An existing detached widget item must not be reattached or
                # treated as a displayed row; get_children is authoritative.
                tree.exists = lambda _row: True
                state = {"scroll": 0.25}
                if anchor is not None:
                    state["top_row"] = anchor
                gui_support.restore_tree_scroll(tree, state)
                self.assertEqual([("fraction", 0.25)], tree.operations)

    def test_current_displayed_order_wins_over_old_row_index(self):
        tree = self.Tree(rows=("added", "anchor", "last"), first=0, total=3)
        gui_support.restore_tree_scroll(tree, {"top_row": "anchor", "scroll": 0})
        self.assertEqual([("row", 1)], tree.operations)

    def test_expanded_preorder_counts_children_and_excludes_collapsed_descendants(self):
        tree = self.Tree(rows=("section-a", "section-b"), first=0, total=4)
        grouped = mock.Mock()
        grouped.get_children.side_effect = lambda parent="": {
            "": ("section-a", "section-b"), "section-a": ("child-a",), "section-b": ("child-b",)}[parent]
        grouped.item.return_value = True
        expanded = gui_support.expanded_tree_rows(grouped)
        self.assertEqual(["section-a", "child-a", "section-b", "child-b"], expanded)
        source = self.Tree(rows=expanded, first=3, total=4)
        self.assertEqual({"scroll": 0.75, "top_row": "child-b"},
                         gui_support.capture_tree_scroll(source, expanded))
        gui_support.restore_tree_scroll(tree, {"top_row": "child-b"}, expanded)
        self.assertEqual([("row", 3)], tree.operations)
        tree.operations.clear()
        grouped.item.side_effect = lambda row, option: row != "section-a"
        collapsed = gui_support.expanded_tree_rows(grouped)
        self.assertEqual(["section-a", "section-b", "child-b"], collapsed)
        gui_support.restore_tree_scroll(tree, {"top_row": "child-b"}, collapsed)
        self.assertEqual([("row", 2)], tree.operations)
        tree.operations.clear()
        gui_support.restore_tree_scroll(tree, {"top_row": "child-a", "scroll": 0.25}, collapsed)
        self.assertEqual([("fraction", 0.25)], tree.operations)

    def test_backup_basename_resolves_to_new_generated_iid(self):
        source = self.Tree(rows=("I001", "I002"), first=1, total=2)
        state = gui_support.capture_tree_scroll(source, row_keys={"I001": "first.json", "I002": "saved.json"})
        self.assertEqual({"scroll": 0.5, "top_row": "saved.json"}, state)
        restored = self.Tree(rows=("I081", "I082", "I083"), first=0, total=3)
        gui_support.restore_tree_scroll(restored, state,
                                       row_keys={"I081": "new.json", "I082": "first.json", "I083": "saved.json"})
        self.assertEqual([("row", 2)], restored.operations)
        restored.operations.clear()
        gui_support.restore_tree_scroll(restored, {"scroll": 0.25}, row_keys={})
        self.assertEqual([("fraction", 0.25)], restored.operations)

    def test_empty_list_captures_no_anchor_and_keeps_legacy_default(self):
        tree = self.Tree(rows=(), first=0, total=1)
        self.assertEqual({"scroll": 0, "top_row": ""}, gui_support.capture_tree_scroll(tree))
        gui_support.restore_tree_scroll(tree, {})
        self.assertEqual([("fraction", 0)], tree.operations)


class GuiSupportTests(unittest.TestCase):
    def test_cell_ellipsis_respects_measured_width(self):
        measure = lambda value: sum(9 if char == "W" else 3 for char in value)
        self.assertEqual("Wi…", gui_support.ellipsize_text("WiWWW", 15, measure))
        self.assertEqual("Wi", gui_support.ellipsize_text("Wi", 12, measure))
        self.assertEqual("", gui_support.ellipsize_text("WWW", 2, measure))

    def test_modal_input_reveals_and_focuses_only_after_activation(self):
        events = []
        dialog = mock.Mock()
        initial_widget = mock.Mock()
        submit = mock.Mock(side_effect=lambda callback: callback(object()))
        dialog.attributes.side_effect = (
            lambda name, value: events.append((name, value))
        )
        dialog.deiconify.side_effect = lambda: events.append("deiconify")
        dialog.wait_visibility.side_effect = lambda: events.append("visible")
        dialog.lift.side_effect = lambda: events.append("lift")
        initial_widget.focus_force.side_effect = lambda: events.append("focus")
        cancel_activation = mock.Mock()
        cancel_key_focus = mock.Mock()

        with mock.patch.object(
            gui_support.platform_support,
            "activate_application_when_ready",
            return_value=cancel_activation,
        ) as activate, mock.patch.object(
            gui_support.platform_support,
            "focus_tk_window_when_ready",
            return_value=cancel_key_focus,
        ) as focus_native, mock.patch.object(
            gui_support.platform_support, "IS_MAC", True
        ):
            cancel = focus_modal_input(dialog, initial_widget, submit)
            self.assertEqual(
                [("-alpha", 0.0), "deiconify", "visible", "lift"],
                events,
            )
            focus_native.assert_not_called()
            activate.call_args.args[0]()
            focus_native.call_args.args[2]()

        self.assertEqual(
            [
                ("-alpha", 0.0),
                "deiconify",
                "visible",
                "lift",
                ("-alpha", 1.0),
                "lift",
                "focus",
            ],
            events,
        )
        cancel()
        cancel_activation.assert_called_once_with()
        cancel_key_focus.assert_called_once_with()

    def test_cancelled_modal_drops_a_queued_reveal(self):
        dialog = mock.Mock()
        initial_widget = mock.Mock()
        queued = []
        cancel_native = mock.Mock()

        with mock.patch.object(
            gui_support.platform_support,
            "activate_application_when_ready",
            side_effect=lambda on_active, _on_failed: on_active() or cancel_native,
        ), mock.patch.object(
            gui_support.platform_support,
            "focus_tk_window_when_ready",
        ), mock.patch.object(gui_support.platform_support, "IS_MAC", True):
            cancel = focus_modal_input(
                dialog,
                initial_widget,
                lambda callback: queued.append(callback),
            )

        cancel()
        queued[0](object())
        initial_widget.focus_force.assert_not_called()
        dialog.attributes.assert_called_once_with("-alpha", 0.0)
        cancel_native.assert_called_once_with()

    def test_modal_without_an_input_focuses_the_dialog_itself(self):
        dialog = mock.Mock()

        with mock.patch.object(
            gui_support.platform_support,
            "activate_application_when_ready",
            side_effect=lambda on_active, _on_failed: on_active() or (lambda: None),
        ), mock.patch.object(
            gui_support.platform_support,
            "focus_tk_window_when_ready",
            side_effect=lambda _dialog, _target, on_key, _on_failed: (
                on_key(),
                (lambda: None),
            )[-1],
        ):
            cancel = focus_modal_input(
                dialog,
                None,
                lambda callback: callback(object()),
            )

        dialog.focus_force.assert_called_once_with()
        cancel()

    def test_native_key_failure_destroys_hidden_dialog_and_raises(self):
        dialog = mock.Mock()
        initial_widget = mock.Mock()

        with mock.patch.object(
            gui_support.platform_support,
            "activate_application_when_ready",
            side_effect=lambda on_active, _on_failed: on_active() or (lambda: None),
        ), mock.patch.object(
            gui_support.platform_support,
            "focus_tk_window_when_ready",
            side_effect=lambda _dialog, _target, _on_key, on_failed: (
                on_failed("native key failed"),
                (lambda: None),
            )[-1],
        ):
            cancel = focus_modal_input(
                dialog,
                initial_widget,
                lambda callback: callback(object()),
            )

        dialog.destroy.assert_called_once_with()
        with self.assertRaisesRegex(RuntimeError, "native key failed"):
            cancel()

    def test_iter_filtered_mapping_items_query_matching(self):
        prefixed = {"__prefix__": "clw", "gtw": "gateway", "api": "api server"}
        rich_mapping = {
            "__prefix__": "c",
            "a": {"__kind__": "rich_text", "text": "Contrato assinado", "spans": []},
            "b": "outro",
        }
        accented = {"__prefix__": "c", "opcao": "Opção válida", "outro": "texto"}
        for old_test, mapping, query, expected in (
            ("test_iter_filtered_mapping_items_ignores_prefix_metadata",
             prefixed, "", ["api", "gtw"]),
            ("test_iter_filtered_mapping_items_ignores_prefix_metadata",
             prefixed, "gate", ["gtw"]),
            ("test_mapping_filter_on_non_dict_returns_empty", None, "", []),
            ("test_mapping_filter_on_non_dict_returns_empty", "not a mapping", "x", []),
            ("test_mapping_filter_matches_rich_text_plain_value",
             rich_mapping, "assinado", ["a"]),
            ("test_mapping_filter_query_is_literal_and_accent_sensitive",
             accented, "OPÇÃO", ["opcao"]),
            ("test_mapping_filter_query_is_literal_and_accent_sensitive",
             accented, "opcao válida", []),
        ):
            with self.subTest(old_test, query=query):
                self.assertEqual(expected, iter_filtered_mapping_items(mapping, query))


class SnippetRowValuesTests(unittest.TestCase):
    def test_row_values_preview_and_markers(self):
        for old_test, key, value, expected in (
            ("test_plain_snippet_has_no_markers", "xname", "Alex", ("xname", "Alex", "")),
            ("test_newlines_and_runs_of_space_collapse",
             "xsig", "linha um\n\nlinha  dois\tfim", ("xsig", "linha um linha dois fim", "")),
            ("test_rich_text_payload_is_marked",
             "xsig", {"__kind__": "rich_text", "text": "Assinatura", "spans": []},
             ("xsig", "Assinatura", "RT")),
            ("test_variable_bearing_snippet_is_marked",
             "xhello", "Olá %%nome%%, tudo bem?", ("xhello", "Olá %%nome%%, tudo bem?", "%%")),
            ("test_rich_text_with_variables_gets_both_markers",
             "xboth", {"__kind__": "rich_text", "text": "Olá %%nome%%", "spans": []},
             ("xboth", "Olá %%nome%%", "RT %%")),
        ):
            with self.subTest(old_test):
                self.assertEqual(expected, snippet_row_values(key, value))

    def test_long_preview_is_truncated_with_ellipsis(self):
        _, preview, _ = snippet_row_values("xlong", "a" * 200, preview_chars=10)

        self.assertEqual(10, len(preview))
        self.assertTrue(preview.endswith("…"))

    def test_value_is_not_mutated(self):
        value = {"__kind__": "rich_text", "text": "Assinatura", "spans": []}
        snapshot = dict(value)

        snippet_row_values("xsig", value)

        self.assertEqual(snapshot, value)


class SnippetTreeValuesTests(unittest.TestCase):
    def test_markers_lead_the_value_cell(self):
        for old_test, key, value, expected in (
            ("test_markers_lead_the_value_cell",
             "xboth", {"__kind__": "rich_text", "text": "Olá %%nome%%", "spans": []},
             ("xboth", "RT %%  ·  Olá %%nome%%")),
            ("test_plain_snippet_shows_only_its_preview", "xname", "Alex", ("xname", "Alex")),
        ):
            with self.subTest(old_test):
                self.assertEqual(expected, gui_support.snippet_tree_values(key, value))


class TreeColumnSplitTests(unittest.TestCase):
    def test_columns_exactly_fill_the_visible_width(self):
        for width in (120, 213, 307, 993):
            with self.subTest(width=width):
                trigger, preview = gui_support.split_tree_columns(width, 48, 0.36, 76, 60)
                self.assertEqual(width - 48, trigger + preview)

    def test_trigger_minimum_holds_until_the_preview_would_starve(self):
        for old_test, width, expected in (
            ("test_trigger_takes_its_share_when_there_is_room", 548, (180, 320)),
            ("test_trigger_minimum_holds_until_the_preview_would_starve", 200, (76, 76)),
            # Too narrow for both minimums: never a negative or overflowing width.
            ("test_trigger_minimum_holds_until_the_preview_would_starve", 100, (52, 0)),
            ("test_trigger_minimum_holds_until_the_preview_would_starve", 30, (0, 0)),
        ):
            with self.subTest(old_test, width=width):
                self.assertEqual(
                    expected, gui_support.split_tree_columns(width, 48, 0.36, 76, 60))


class WrappingRowTests(unittest.TestCase):
    def test_row_fits_includes_the_gap(self):
        self.assertTrue(gui_support.row_fits(316, 200, 100, 16))
        self.assertFalse(gui_support.row_fits(315, 200, 100, 16))


if __name__ == "__main__":
    unittest.main()
