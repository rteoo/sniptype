import unittest
from unittest import mock

from gui_support import (
    filter_static_snippets,
    focus_modal_input,
    iter_filtered_mapping_items,
    snippet_row_values,
)
import gui_support


class GuiSupportTests(unittest.TestCase):
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

    def test_filter_static_snippets_without_query_keeps_only_persisted_static_entries(self):
        for old_test, snippets, query, expected in (
            ("test_filter_static_snippets_without_query_keeps_only_persisted_static_entries",
             {"xname": "Alex", "_cpf_numbers": {"fulano": "123"}, "xdyn": lambda: "value"},
             "", {"xname": "Alex"}),
            ("test_whitespace_only_query_behaves_like_an_empty_query",
             {"xname": "Alex", "xemail": "a@b.com"},
             "   \t ", {"xname": "Alex", "xemail": "a@b.com"}),
        ):
            with self.subTest(old_test):
                self.assertEqual(expected, filter_static_snippets(snippets, query))

    def test_filter_static_snippets_query_matching(self):
        rich_signature = {
            "__kind__": "rich_text",
            "text": "Assinatura principal",
            "spans": [],
        }
        for old_test, snippets, query, expected in (
            ("test_filter_static_snippets_matches_key_and_value",
             {"xname": "Alex", "xemail": "contato@example.com"},
             "example", {"xemail": "contato@example.com"}),
            ("test_filter_static_snippets_matches_key_and_value",
             {"xname": "Alex", "xemail": "contato@example.com"},
             "name", {"xname": "Alex"}),
            ("test_filter_static_snippets_matches_rich_text_plain_value",
             {"xsig": rich_signature}, "assinatura", {"xsig": rich_signature}),
            # A blind re.search would treat "(net)" as a group and ".*" as
            # match-all; the filter must compare literally.
            ("test_query_is_a_literal_substring_not_a_regex",
             {"xa": "Total (net) due", "xb": "plain text"},
             "(net)", {"xa": "Total (net) due"}),
            ("test_query_is_a_literal_substring_not_a_regex",
             {"xa": "Total (net) due", "xb": "plain text"}, ".*", {}),
            # An unbalanced bracket would blow up re.compile; str.__contains__ is safe.
            ("test_regex_metacharacter_query_does_not_raise",
             {"xa": "array[0] value"}, "[", {"xa": "array[0] value"}),
            # Case folds: an all-caps accented query still matches.
            ("test_matching_is_case_insensitive_but_accent_sensitive",
             {"xinsc": "Inscrição estadual", "xother": "Cadastro"},
             "INSCRIÇÃO", {"xinsc": "Inscrição estadual"}),
            # Accents are not folded: the de-accented spelling does not match.
            ("test_matching_is_case_insensitive_but_accent_sensitive",
             {"xinsc": "Inscrição estadual", "xother": "Cadastro"}, "inscricao", {}),
            ("test_unicode_key_match_is_case_insensitive",
             {"xcafé": "espresso"}, "CAFÉ", {"xcafé": "espresso"}),
        ):
            with self.subTest(old_test, query=query):
                self.assertEqual(expected, filter_static_snippets(snippets, query))

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
