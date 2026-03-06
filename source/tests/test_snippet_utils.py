import json
import unittest
from pathlib import Path

from snippet_utils import (
    build_saveable_snippets,
    calculate_max_trigger_length,
    calculate_max_trigger_length_with_mappings,
    check_dynamic_pattern,
    get_default_snippets,
    get_dynamic_prefixes,
    load_json_file,
    merge_snippets,
    validate_static_snippets,
    write_json_atomic,
)


class SnippetUtilsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).resolve().parent / "tmp"
        cls.temp_root.mkdir(exist_ok=True)

    def setUp(self):
        self.snippets = {
            "xname": "Example User",
            "xsig": "Assinatura",
            "_cpf_numbers": {
                "fulano": "123.456.789-00",
            },
            "_cnpj_numbers": {
                "empresa": "12.345.678/0001-90",
            },
            "_openclaw_codes": {
                "__prefix__": "clw",
                "gtw": "openclaw gateway restart",
            },
            "_email_codes": {
                "work": "work@example.com",
            },
        }

    def tearDown(self):
        for path in self.temp_root.glob('snippet-utils-test-*.json'):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def make_test_path(self, suffix):
        return self.temp_root / f"snippet-utils-test-{suffix}.json"

    def test_default_snippets_returns_fresh_copy(self):
        first = get_default_snippets()
        second = get_default_snippets()

        first["_cpf_numbers"]["fulano"] = "changed"

        self.assertEqual("123.456.789-00", second["_cpf_numbers"]["fulano"])

    def test_validate_static_snippets_accepts_dict_root(self):
        self.assertEqual({"x": "y"}, validate_static_snippets({"x": "y"}))

    def test_validate_static_snippets_rejects_non_dict_root(self):
        self.assertIsNone(validate_static_snippets(["not", "a", "dict"]))

    def test_load_json_file_reads_utf8_json(self):
        path = self.make_test_path('load')
        path.write_text('{"x": "á"}', encoding='utf-8')

        self.assertEqual({"x": "á"}, load_json_file(path))

    def test_write_json_atomic_replaces_existing_json(self):
        path = self.make_test_path('write')
        path.write_text('{"old": true}', encoding='utf-8')

        write_json_atomic(path, {"new": "value"})

        self.assertEqual({"new": "value"}, json.loads(path.read_text(encoding='utf-8')))

    def test_build_saveable_snippets_filters_runtime_callables(self):
        saveable = build_saveable_snippets({"xname": "Example User", "xdyn": lambda: "value"})

        self.assertEqual({"xname": "Example User"}, saveable)

    def test_merge_snippets_keeps_dynamic_priority(self):
        merged = merge_snippets({"xhj": "static"}, {"xhj": "dynamic", "xnow": "dynamic-now"})

        self.assertEqual("dynamic", merged["xhj"])
        self.assertEqual("dynamic-now", merged["xnow"])

    def test_get_dynamic_prefixes_includes_builtin_and_custom_mappings(self):
        prefixes = get_dynamic_prefixes(self.snippets)

        self.assertEqual("_cpf_numbers", prefixes["cpf"])
        self.assertEqual("_cnpj_numbers", prefixes["cnpj"])
        self.assertEqual("_openclaw_codes", prefixes["clw"])
        self.assertEqual("_email_codes", prefixes["email"])

    def test_check_dynamic_pattern_resolves_builtin_mapping(self):
        value, trigger_length = check_dynamic_pattern(self.snippets, "cpffulano")

        self.assertEqual("123.456.789-00", value)
        self.assertEqual(len("cpffulano"), trigger_length)

    def test_check_dynamic_pattern_resolves_custom_prefix(self):
        prefixes = get_dynamic_prefixes(self.snippets)
        value, trigger_length = check_dynamic_pattern(self.snippets, "clwgtw", prefixes)

        self.assertEqual("openclaw gateway restart", value)
        self.assertEqual(len("clwgtw"), trigger_length)

    def test_check_dynamic_pattern_ignores_prefix_metadata(self):
        value, trigger_length = check_dynamic_pattern(self.snippets, "clw__prefix__")

        self.assertIsNone(value)
        self.assertEqual(0, trigger_length)

    def test_calculate_max_trigger_length_matches_current_direct_key_behavior(self):
        self.assertEqual(len("_openclaw_codes"), calculate_max_trigger_length(self.snippets))

    def test_calculate_max_trigger_length_with_mappings_counts_full_dynamic_trigger(self):
        snippets = {
            "x": "y",
            "_custom_codes": {
                "__prefix__": "clw",
                "verylongidentifier": "value",
            },
        }

        self.assertEqual(len("clwverylongidentifier"), calculate_max_trigger_length_with_mappings(snippets))


if __name__ == "__main__":
    unittest.main()
