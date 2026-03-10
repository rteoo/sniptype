import unittest

from gui_support import (
    DATETIME_SNIPPETS,
    ECONOMY_SNIPPETS,
    STOCK_SNIPPETS,
    WHATSAPP_SNIPPETS,
    filter_static_snippets,
    iter_filtered_mapping_items,
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

    def test_reference_lists_are_not_empty(self):
        self.assertGreater(len(DATETIME_SNIPPETS), 0)
        self.assertGreater(len(ECONOMY_SNIPPETS), 0)
        self.assertGreater(len(STOCK_SNIPPETS), 0)
        self.assertGreater(len(WHATSAPP_SNIPPETS), 0)
        whatsapp_triggers = {trigger for trigger, _ in WHATSAPP_SNIPPETS}

        self.assertIn("xwapp", whatsapp_triggers)
        self.assertIn("xlwapp", whatsapp_triggers)
        self.assertIn("xpwapp", whatsapp_triggers)


if __name__ == "__main__":
    unittest.main()
