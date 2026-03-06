import unittest

from trigger_index import compile_trigger_index, find_direct_trigger, find_dynamic_trigger


class TriggerIndexTests(unittest.TestCase):
    def setUp(self):
        self.snippets = {
            "abc": "first",
            "xbc": "second",
            "xname": "Example User",
            "_cpf_numbers": {
                "fulano": "123.456.789-00",
            },
            "_openclaw_codes": {
                "__prefix__": "clw",
                "gtw": "openclaw gateway restart",
            },
        }
        self.slow_triggers = {"xname"}
        self.index = compile_trigger_index(self.snippets, self.slow_triggers)

    def test_compile_trigger_index_preserves_direct_trigger_order(self):
        self.assertEqual(("abc", "xbc", "xname"), self.index["direct_triggers"])

    def test_compile_trigger_index_groups_by_last_character(self):
        self.assertEqual(("abc", "xbc"), self.index["direct_by_last_char"]["c"])
        self.assertEqual(("xname",), self.index["direct_by_last_char"]["e"])

    def test_find_direct_trigger_only_checks_matching_last_char_bucket(self):
        self.assertEqual("abc", find_direct_trigger("zzabc", self.index))
        self.assertIsNone(find_direct_trigger("zzab", self.index))

    def test_find_direct_trigger_preserves_original_precedence(self):
        self.assertEqual("abc", find_direct_trigger("prefixabc", self.index))

    def test_find_dynamic_trigger_resolves_builtin_mapping(self):
        trigger, value = find_dynamic_trigger(self.snippets, "xxcpffulano", self.index)

        self.assertEqual("cpffulano", trigger)
        self.assertEqual("123.456.789-00", value)

    def test_find_dynamic_trigger_resolves_custom_prefix(self):
        trigger, value = find_dynamic_trigger(self.snippets, "abcclwgtw", self.index)

        self.assertEqual("clwgtw", trigger)
        self.assertEqual("openclaw gateway restart", value)

    def test_find_dynamic_trigger_returns_none_for_non_match(self):
        trigger, value = find_dynamic_trigger(self.snippets, "clwmissing", self.index)

        self.assertIsNone(trigger)
        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
