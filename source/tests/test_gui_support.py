import unittest

from gui_support import (
    filter_static_snippets,
    iter_filtered_mapping_items,
    snippet_row_values,
)


class GuiSupportTests(unittest.TestCase):
    def test_filter_static_snippets_without_query_keeps_only_persisted_static_entries(self):
        snippets = {
            "xname": "Example User",
            "_cpf_numbers": {"fulano": "123"},
            "xdyn": lambda: "value",
        }

        self.assertEqual({"xname": "Example User"}, filter_static_snippets(snippets, ""))

    def test_filter_static_snippets_matches_key_and_value(self):
        snippets = {
            "xname": "Example User",
            "xemail": "contato@example.com",
        }

        self.assertEqual({"xemail": "contato@example.com"}, filter_static_snippets(snippets, "example"))
        self.assertEqual({"xname": "Example User"}, filter_static_snippets(snippets, "name"))

    def test_filter_static_snippets_matches_rich_text_plain_value(self):
        snippets = {
            "xsig": {
                "__kind__": "rich_text",
                "text": "Assinatura principal",
                "spans": [],
            }
        }

        self.assertEqual({"xsig": snippets["xsig"]}, filter_static_snippets(snippets, "assinatura"))

    def test_iter_filtered_mapping_items_ignores_prefix_metadata(self):
        mapping = {
            "__prefix__": "clw",
            "gtw": "gateway",
            "api": "api server",
        }

        self.assertEqual(["api", "gtw"], iter_filtered_mapping_items(mapping, ""))
        self.assertEqual(["gtw"], iter_filtered_mapping_items(mapping, "gate"))


class SnippetRowValuesTests(unittest.TestCase):
    def test_plain_snippet_has_no_markers(self):
        self.assertEqual(("xname", "Example User", ""), snippet_row_values("xname", "Example User"))

    def test_newlines_and_runs_of_space_collapse(self):
        _, preview, _ = snippet_row_values("xsig", "linha um\n\nlinha  dois\tfim")

        self.assertEqual("linha um linha dois fim", preview)

    def test_long_preview_is_truncated_with_ellipsis(self):
        _, preview, _ = snippet_row_values("xlong", "a" * 200, preview_chars=10)

        self.assertEqual(10, len(preview))
        self.assertTrue(preview.endswith("…"))

    def test_rich_text_payload_is_marked(self):
        value = {"__kind__": "rich_text", "text": "Assinatura", "spans": []}

        self.assertEqual(("xsig", "Assinatura", "RT"), snippet_row_values("xsig", value))

    def test_variable_bearing_snippet_is_marked(self):
        _, _, markers = snippet_row_values("xhello", "Olá %%nome%%, tudo bem?")

        self.assertEqual("%%", markers)

    def test_rich_text_with_variables_gets_both_markers(self):
        value = {"__kind__": "rich_text", "text": "Olá %%nome%%", "spans": []}

        self.assertEqual("RT %%", snippet_row_values("xboth", value)[2])

    def test_value_is_not_mutated(self):
        value = {"__kind__": "rich_text", "text": "Assinatura", "spans": []}
        snapshot = dict(value)

        snippet_row_values("xsig", value)

        self.assertEqual(snapshot, value)


if __name__ == "__main__":
    unittest.main()
