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


class SuffixOrderingTests(unittest.TestCase):
    def test_longer_trigger_wins_over_suffix_regardless_of_source_order(self):
        # "ecban" is a suffix of "iecban"; the shorter one is listed first, which
        # under source-order matching would shadow the longer one.
        snippets = {"ecban": "short", "iecban": "long"}
        index = compile_trigger_index(snippets, set())
        self.assertEqual("iecban", find_direct_trigger("xiecban", index))
        self.assertEqual("ecban", find_direct_trigger("xecban", index))

    def test_bucket_is_ordered_longest_first(self):
        snippets = {"ab": "1", "xxab": "2", "zab": "3"}
        index = compile_trigger_index(snippets, set())
        self.assertEqual(("xxab", "zab", "ab"), index["direct_by_last_char"]["b"])


class FormTriggerMetadataTests(unittest.TestCase):
    def test_form_variable_snippet_is_flagged(self):
        snippets = {
            "xform": "Hello %%name%%",
            "xplain": "just text",
            "xclip": "paste %%clipboard-paste%%",
        }
        index = compile_trigger_index(snippets, set())
        self.assertIn("xform", index["form_triggers"])
        self.assertNotIn("xplain", index["form_triggers"])
        # clipboard-paste is an inline variable, not a form field.
        self.assertNotIn("xclip", index["form_triggers"])

    def test_callable_and_mapping_are_never_form_triggers(self):
        snippets = {"xcall": lambda: "x", "_codes": {"__prefix__": "c"}}
        index = compile_trigger_index(snippets, set())
        self.assertEqual(frozenset(), index["form_triggers"])

    def test_mapping_and_dynamic_refs_are_not_form_triggers(self):
        snippets = {
            "xmap": "CPF %%cpffulano%%",
            "xdyn": "hoje %%xhj%%",
            "xhj": lambda: "01/01/2026",
            "_cpf_numbers": {"fulano": "123"},
        }
        index = compile_trigger_index(snippets, set())
        self.assertNotIn("xmap", index["form_triggers"])
        self.assertNotIn("xdyn", index["form_triggers"])


class SlowTriggerMetadataTests(unittest.TestCase):
    def test_direct_slow_triggers_are_included(self):
        index = compile_trigger_index({"xdolar": lambda: "R$5"}, {"xdolar"})
        self.assertIn("xdolar", index["slow_triggers"])

    def test_snippet_referencing_slow_trigger_becomes_slow(self):
        snippets = {
            "xreport": "Dólar hoje: %%xdolar%%",
            "xplain": "sem referência",
            "xdolar": lambda: "R$5",
        }
        index = compile_trigger_index(snippets, {"xdolar"})
        self.assertIn("xreport", index["slow_triggers"])
        self.assertNotIn("xplain", index["slow_triggers"])

    def test_reference_to_fast_trigger_stays_fast(self):
        snippets = {"xgreet": "Hoje é %%xhj%%", "xhj": lambda: "01/01/2026"}
        index = compile_trigger_index(snippets, {"xdolar"})
        self.assertNotIn("xgreet", index["slow_triggers"])


class MultiSuffixOrderingTests(unittest.TestCase):
    def test_three_way_suffix_chain_matches_longest_available(self):
        # "x" ⊂ "yx" ⊂ "zzyx": each buffer must resolve to the longest trigger
        # that is actually a suffix of it, never a shorter shadow.
        snippets = {"x": "1", "yx": "2", "zzyx": "3"}
        index = compile_trigger_index(snippets, set())
        self.assertEqual("zzyx", find_direct_trigger("azzyx", index))
        self.assertEqual("yx", find_direct_trigger("ayx", index))
        self.assertEqual("x", find_direct_trigger("ax", index))

    def test_multiple_triggers_share_last_char_all_reachable(self):
        snippets = {"cat": "c", "hat": "h", "splat": "s"}
        index = compile_trigger_index(snippets, set())
        # longest-first, ties keep source order (cat before hat).
        self.assertEqual(("splat", "cat", "hat"), index["direct_by_last_char"]["t"])
        self.assertEqual("cat", find_direct_trigger("wombat cat", index))
        self.assertEqual("hat", find_direct_trigger("with a hat", index))
        self.assertEqual("splat", find_direct_trigger("go splat", index))


class BufferBoundaryTests(unittest.TestCase):
    def test_trigger_longer_than_buffer_does_not_match(self):
        index = compile_trigger_index({"abcdef": "x"}, set())
        self.assertIsNone(find_direct_trigger("cdef", index))

    def test_trigger_exactly_equal_to_buffer_matches(self):
        index = compile_trigger_index({"abc": "x"}, set())
        self.assertEqual("abc", find_direct_trigger("abc", index))

    def test_empty_typed_text_never_matches(self):
        index = compile_trigger_index({"abc": "x"}, set())
        self.assertIsNone(find_direct_trigger("", index))
        self.assertEqual((None, None), find_dynamic_trigger({"abc": "x"}, "", index))


class UnicodeTriggerTests(unittest.TestCase):
    def test_accented_trigger_orders_longest_first_and_matches(self):
        snippets = {"café": "coffee", "xcafé": "big coffee"}
        index = compile_trigger_index(snippets, set())
        self.assertEqual(("xcafé", "café"), index["direct_by_last_char"]["é"])
        self.assertEqual("xcafé", find_direct_trigger("zxcafé", index))
        self.assertEqual("café", find_direct_trigger("zcafé", index))

    def test_single_codepoint_emoji_trigger_matches(self):
        snippets = {"x🎉": "party"}
        index = compile_trigger_index(snippets, set())
        self.assertEqual("x🎉", find_direct_trigger("hey x🎉", index))

    def test_multi_codepoint_emoji_trigger_still_matches(self):
        # A flag is two code points; the bucket keys on the final code point but
        # endswith must still match the whole trigger string.
        flag = "\U0001F1E7\U0001F1F7"  # regional-indicator B + R
        trigger = "x" + flag
        index = compile_trigger_index({trigger: "brasil"}, set())
        self.assertEqual(trigger, find_direct_trigger("vai " + trigger, index))


class DynamicTriggerEdgeTests(unittest.TestCase):
    def setUp(self):
        self.snippets = {"_cpf_numbers": {"fulano": "123", "empty": ""}}
        self.index = compile_trigger_index(self.snippets, set())

    def test_prefix_without_name_does_not_match(self):
        self.assertEqual((None, None), find_dynamic_trigger(self.snippets, "xxcpf", self.index))

    def test_rfind_picks_last_prefix_occurrence(self):
        # The prefix appears twice; only the trailing one carries a real name.
        trigger, value = find_dynamic_trigger(self.snippets, "cpfxcpffulano", self.index)
        self.assertEqual("cpffulano", trigger)
        self.assertEqual("123", value)

    def test_empty_string_mapping_value_is_a_match_not_a_miss(self):
        # value == "" must be treated as a resolved value, never as "no match".
        trigger, value = find_dynamic_trigger(self.snippets, "cpfempty", self.index)
        self.assertEqual("cpfempty", trigger)
        self.assertEqual("", value)


class EmptyKeyRegressionTests(unittest.TestCase):
    """KNOWN DEFECT — kept as a failing regression marker (no source fix applied).

    compile_trigger_index does ``last_char = trigger[-1]`` (trigger_index.py:52),
    which raises ``IndexError`` on an empty-string trigger key. validate_static_snippets
    passes ``{"": "x"}`` through unchanged, so a syntactically valid snippets.json
    with an empty key reaches compile_trigger_index via refresh_runtime_indexes in
    ``TextExpander.__init__`` and crashes app startup, uncaught by
    recover_snippets_file (which only wraps the parse step). An empty key can never
    be a meaningful trigger (``endswith("")`` is always true) and must be skipped
    the way ``_``-prefixed keys already are.
    """

    def test_empty_string_trigger_key_does_not_crash_and_real_trigger_still_indexes(self):
        index = compile_trigger_index({"": "x", "abc": "y"}, set())
        self.assertEqual("abc", find_direct_trigger("zzabc", index))


if __name__ == "__main__":
    unittest.main()
