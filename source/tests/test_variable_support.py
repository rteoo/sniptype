import threading
import unittest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from variable_support import (
    VariableResolutionError,
    classify_variable,
    find_variable_names,
    has_form_variables,
    resolve_form_variables,
    resolve_inline,
)
from whatsapp_runtime_support import ACTION_COMPLETED


def _resolve_in_thread(*args, timeout=2.0, **kwargs):
    """Run resolve_inline on a daemon thread and report whether it hung.

    Returns (result, timed_out). Used for reference cycles: if the source could
    ever infinite-loop, the join times out and ``timed_out`` is True instead of
    wedging the whole test runner.
    """
    box = {}

    def target():
        box["result"] = resolve_inline(*args, **kwargs)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    return box.get("result"), thread.is_alive()


class TestFindVariableNames(unittest.TestCase):

    def test_finds_variable_names(self):
        cases = [
            ("empty_string", "", []),
            ("no_variables", "hello world", []),
            ("single_variable", "%%nome%%", ["nome"]),
            ("multiple_variables", "%%a%% e %%b%%", ["a", "b"]),
            ("duplicates_deduplicated", "%%a%% %%a%%", ["a"]),
            ("order_preserved", "%%z%% %%a%% %%m%%", ["z", "a", "m"]),
            # Spaces inside %% should not match (pattern requires non-whitespace)
            ("no_spaces_inside", "%% name %%", []),
            ("clipboard_paste_name", "%%clipboard-paste%%", ["clipboard-paste"]),
        ]
        for label, text, expected in cases:
            with self.subTest(label, text=text):
                self.assertEqual(find_variable_names(text), expected)


class TestClassifyVariable(unittest.TestCase):

    def test_classifies_each_kind(self):
        cpf = {"_cpf_numbers": {"fulano": "123.456.789-00"}}
        cases = [
            ("clipboard", "clipboard-paste", {}, "clipboard"),
            ("snippet_ref", "xname", {"xname": "Alex"}, "snippet_ref"),
            ("callable_snippet_is_dynamic_ref", "xcot", {"xcot": lambda: "R$10"}, "dynamic_ref"),
            ("mapping_trigger_is_mapping_ref", "cpffulano", cpf, "mapping_ref"),
            ("unknown_mapping_item_is_form_field", "cpfciclano", cpf, "form_field"),
            ("unknown_name_is_form_field", "nome", {}, "form_field"),
            ("nonexistent_key_is_form_field", "data", {"xname": "Alex"}, "form_field"),
        ]
        for label, name, snippets, expected in cases:
            with self.subTest(label):
                self.assertEqual(classify_variable(name, snippets), expected)


class TestHasFormVariables(unittest.TestCase):

    def test_true_only_when_a_form_field_is_present(self):
        cases = [
            ("no_variables", "plain text", {}, False),
            ("only_clipboard", "%%clipboard-paste%%", {}, False),
            ("only_snippet_ref", "Olá %%xname%%", {"xname": "Alex"}, False),
            ("only_mapping_ref", "CPF %%cpffulano%%", {"_cpf_numbers": {"fulano": "123"}}, False),
            ("only_dynamic_ref", "%%xcot%%", {"xcot": lambda: "R$10"}, False),
            ("has_form_field", "Olá %%nome%%", {}, True),
            ("mixed_with_form_field", "%%xname%% e %%data%%", {"xname": "Alex"}, True),
        ]
        for label, text, snippets, expected in cases:
            with self.subTest(label):
                self.assertEqual(bool(has_form_variables(text, snippets)), expected)


class TestResolveInline(unittest.TestCase):

    def test_substitutes_each_inline_kind(self):
        cases = [
            ("no_variables", "hello world", {}, None, "hello world"),
            ("clipboard_substitution", "cmd %%clipboard-paste%%", {}, "meu texto", "cmd meu texto"),
            ("snippet_ref_plain", "Endereço: %%xaddr%%", {"xaddr": "Rua das Flores, 10"}, None,
             "Endereço: Rua das Flores, 10"),
            ("snippet_ref_rich_text", "Ver %%xtitle%%",
             {"xtitle": {"__kind__": "rich_text", "text": "Relatório"}}, None, "Ver Relatório"),
            ("mapping_ref_resolved", "CPF: %%cpffulano%%",
             {"_cpf_numbers": {"fulano": "123.456.789-00"}}, None, "CPF: 123.456.789-00"),
            ("mapping_ref_rich_text_value", "%%ccx%%",
             {"_custom_codes": {"__prefix__": "cc", "x": {"__kind__": "rich_text", "text": "ABC"}}},
             None, "ABC"),
            ("form_field_left_unchanged", "Olá %%nome%%", {}, None, "Olá %%nome%%"),
            ("multiple_variables_mixed", "Clip: %%clipboard-paste%%, Ref: %%xaddr%%, Form: %%nome%%",
             {"xaddr": "Rua A"}, "CB", "Clip: CB, Ref: Rua A, Form: %%nome%%"),
            ("unicode_snippet_ref_resolved", "%%café%%", {"café": "coffee"}, None, "coffee"),
        ]
        for label, text, snippets, clipboard, expected in cases:
            with self.subTest(label):
                result = resolve_inline(text, snippets, lambda clipboard=clipboard: clipboard)
                self.assertEqual(result, expected)

    def test_clipboard_unavailable_fails_instead_of_deleting_token(self):
        with self.assertRaisesRegex(VariableResolutionError, "transferência"):
            resolve_inline("cmd %%clipboard-paste%%", {}, lambda: None)

    def test_clipboard_valid_empty_text_is_substituted(self):
        result = resolve_inline("cmd %%clipboard-paste%%", {}, lambda: "")
        self.assertEqual(result, "cmd ")

    def test_clipboard_read_exception_is_wrapped_truthfully(self):
        def unavailable():
            raise OSError("clipboard busy")

        with self.assertRaises(VariableResolutionError) as caught:
            resolve_inline("cmd %%clipboard-paste%%", {}, unavailable)
        self.assertIsInstance(caught.exception.__cause__, OSError)

    def test_callable_snippet_is_invoked(self):
        snippets = {"xcot": lambda: "R$10"}
        result = resolve_inline("%%xcot%%", snippets, lambda: None)
        self.assertEqual(result, "R$10")

    def test_callable_returning_none_becomes_empty(self):
        # Action-only flows (xwapp opens the browser) substitute nothing.
        snippets = {"xwapp": lambda: None}
        result = resolve_inline("link: %%xwapp%%", snippets, lambda: None)
        self.assertEqual(result, "link: ")

    def test_action_completion_marker_becomes_empty(self):
        snippets = {"xwapp": lambda: ACTION_COMPLETED}
        result = resolve_inline("link: %%xwapp%%", snippets, lambda: None)
        self.assertEqual(result, "link: ")

    def test_raising_callable_substitutes_empty_and_notifies(self):
        def boom():
            raise RuntimeError("sem rede")

        calls = []
        result = resolve_inline(
            "valor: %%xdolar%%", {"xdolar": boom}, lambda: None,
            notify_failure=lambda name, value: calls.append((name, value)),
        )
        self.assertEqual(result, "valor: ")
        self.assertEqual(calls[0][0], "xdolar")
        self.assertIn("sem rede", calls[0][1])

    def test_marker_result_is_substituted_and_notified(self):
        calls = []
        snippets = {"xdolar": lambda: "[Dado indisponível]"}
        result = resolve_inline(
            "%%xdolar%%", snippets, lambda: None,
            notify_failure=lambda name, value: calls.append((name, value)),
        )
        self.assertEqual(result, "[Dado indisponível]")
        self.assertEqual(calls, [("xdolar", "[Dado indisponível]")])

    def test_dynamic_ref_circular_guard(self):
        snippets = {"xcot": lambda: "R$10"}
        result = resolve_inline("%%xcot%%", snippets, lambda: None, _seen={"xcot"})
        self.assertEqual(result, "%%xcot%%")

    def test_circular_ref_guard(self):
        snippets = {"xself": "start %%xself%% end"}
        result = resolve_inline("%%xself%%", snippets, lambda: None, _seen={"xself"})
        self.assertEqual(result, "%%xself%%")


class TestResolveFormVariables(unittest.TestCase):

    def test_substitutes_form_values(self):
        cases = [
            ("single_field", "Olá %%nome%%", {"nome": "Carlos"}, "Olá Carlos"),
            ("multiple_fields", "%%nome%%, disponível em %%data%%?",
             {"nome": "Ana", "data": "segunda"}, "Ana, disponível em segunda?"),
            ("missing_key_leaves_token", "Olá %%nome%%", {}, "Olá %%nome%%"),
            ("empty_value", "%%campo%%", {"campo": ""}, ""),
            ("repeated_token", "%%x%% e %%x%%", {"x": "A"}, "A e A"),
            ("unicode_form_value", "%%c%%", {"c": "café ☕"}, "café ☕"),
        ]
        for label, text, values, expected in cases:
            with self.subTest(label):
                self.assertEqual(resolve_form_variables(text, values), expected)


# --------------------------------------------------------------------------- #
# Adversarial: token parsing (VARIABLE_RE / find_variable_names)
# --------------------------------------------------------------------------- #
class TestTokenParsingAdversarial(unittest.TestCase):

    def test_malformed_tokens_do_not_match(self):
        cases = [
            # %%%% has no non-% char between the pairs, so the "+" fails.
            ("empty_token_does_not_match", "%%%%"),
            ("unterminated_token_no_closing", "%%name"),
            ("unterminated_token_single_trailing_percent", "%%name%"),
            ("lone_double_percent", "%%"),
            # "50%% off": the second %% is followed by a space, so nothing matches.
            ("percent_inside_normal_text", "50%% off"),
            # A % inside the name is excluded by [^%\s]; no closing pair aligns.
            ("internal_percent_breaks_token", "%%a%b%%"),
            ("tab_inside_token_does_not_match", "%%\t%%"),
        ]
        for label, text in cases:
            with self.subTest(label, text=text):
                self.assertEqual(find_variable_names(text), [])

    def test_edge_case_tokens_are_found(self):
        name = "z" * 5000
        cases = [
            # "%%a%%b%%": first pair closes after 'a'; the trailing "b%%" is inert.
            ("double_token_with_middle_text", "%%a%%b%%", ["a"]),
            # The inner %% pair anchors; extra surrounding % are absorbed.
            ("triple_delimited_token", "%%%name%%%", ["name"]),
            ("adjacent_tokens", "%%a%%%%b%%", ["a", "b"]),
            ("token_at_string_start_and_end", "%%a%%", ["a"]),
            ("token_at_string_start_and_end", "x%%a%%", ["a"]),
            ("token_at_string_start_and_end", "%%a%%x", ["a"]),
            ("unicode_token_name", "%%café%%", ["café"]),
            ("unicode_token_name", "%%naïve_ção%%", ["naïve_ção"]),
            ("token_with_dots_digits_hyphens", "%%a.b-c1%%", ["a.b-c1"]),
            ("extremely_long_token_name", f"%%{name}%%", [name]),
        ]
        for label, text, expected in cases:
            with self.subTest(label, text=text[:40]):
                self.assertEqual(find_variable_names(text), expected)


# --------------------------------------------------------------------------- #
# Adversarial: classification (classify_variable)
# --------------------------------------------------------------------------- #
class TestClassifyVariableAdversarial(unittest.TestCase):

    def test_sentinel_callable_classifies_without_invoking(self):
        # sync_export relies on this: a dynamic trigger is mapped to a sentinel
        # callable so classify still returns 'dynamic_ref' — and must NOT run it.
        def sentinel():
            raise AssertionError("classify_variable must never invoke the callable")

        self.assertEqual(classify_variable("xdolar", {"xdolar": sentinel}), "dynamic_ref")

    def test_precedence_and_edge_cases(self):
        cases = [
            # "cpf" alone (prefix with no item) is not a composed trigger.
            ("bare_mapping_prefix_is_form_field", "cpf",
             {"_cpf_numbers": {"fulano": "123"}}, "form_field"),
            # The synthetic "__prefix__" entry is not a resolvable mapping item.
            ("prefix_plus_reserved_prefix_item_is_form_field", "cc__prefix__",
             {"_custom_codes": {"__prefix__": "cc", "x": "ABC"}}, "form_field"),
            # A literal key wins over the composed mapping that would also match.
            ("direct_snippet_key_beats_mapping_pattern", "cpffulano",
             {"cpffulano": "static-value", "_cpf_numbers": {"fulano": "123"}}, "snippet_ref"),
            ("callable_at_composed_name_is_dynamic_ref", "cpffulano",
             {"cpffulano": lambda: "x", "_cpf_numbers": {"fulano": "123"}}, "dynamic_ref"),
            ("unicode_snippet_key_is_snippet_ref", "café", {"café": "coffee"}, "snippet_ref"),
            # Priority order: clipboard-paste is resolved before any snippet lookup.
            ("clipboard_wins_even_with_matching_snippet", "clipboard-paste",
             {"clipboard-paste": "shadow"}, "clipboard"),
        ]
        for label, name, snippets, expected in cases:
            with self.subTest(label):
                self.assertEqual(classify_variable(name, snippets), expected)


# --------------------------------------------------------------------------- #
# Adversarial: inline resolution (resolve_inline / _resolve_dynamic)
# --------------------------------------------------------------------------- #
class TestResolveInlineAdversarial(unittest.TestCase):

    def test_callable_returning_int_is_stringified(self):
        result = resolve_inline("n=%%x%%", {"x": lambda: 42}, lambda: None)
        self.assertEqual(result, "n=42")

    def test_callable_returning_falsy_zero_becomes_empty(self):
        # 0 is falsy, so _resolve_dynamic substitutes "" (same path as None).
        result = resolve_inline("n=%%x%%", {"x": lambda: 0}, lambda: None)
        self.assertEqual(result, "n=")

    def test_callable_returning_rich_text_dict_uses_plain_text(self):
        calls = []
        rich = {"__kind__": "rich_text", "text": "Olá", "spans": []}
        result = resolve_inline(
            "%%x%%", {"x": lambda: rich}, lambda: None,
            notify_failure=lambda name, value: calls.append((name, value)),
        )
        self.assertEqual(result, "Olá")
        # The raw (dict) result is handed to notify_failure, not the plain text.
        self.assertEqual(calls, [("x", rich)])

    def test_repeated_dynamic_token_invoked_once_all_replaced(self):
        counter = {"n": 0}

        def once():
            counter["n"] += 1
            return "V"

        result = resolve_inline("%%x%% and %%x%%", {"x": once}, lambda: None)
        self.assertEqual(result, "V and V")
        self.assertEqual(counter["n"], 1)  # invoked once despite two occurrences

    def test_snippet_ref_is_one_level_deep(self):
        # An embedded token inside a referenced snippet is left unresolved when it
        # is not otherwise present at the top level (documented one-level rule).
        snippets = {"xaddr": "Rua %%xcity%%", "xcity": "SP"}
        result = resolve_inline("%%xaddr%%", snippets, lambda: None)
        self.assertEqual(result, "Rua %%xcity%%")

    def test_embedded_token_resolved_only_via_top_level_reference(self):
        # Same data, but 'xcity' also appears at top level, so global replace
        # reaches the copy embedded by xaddr's value too.
        snippets = {"xaddr": "Rua %%xcity%%", "xcity": "SP"}
        result = resolve_inline("%%xaddr%% - %%xcity%%", snippets, lambda: None)
        self.assertEqual(result, "Rua SP - SP")

    def test_seen_guard_applies_to_mapping_ref(self):
        # The _seen short-circuit sits before the mapping branch too.
        snippets = {"_cpf_numbers": {"fulano": "123"}}
        result = resolve_inline(
            "%%cpffulano%%", snippets, lambda: None, _seen={"cpffulano"}
        )
        self.assertEqual(result, "%%cpffulano%%")

    def test_self_reference_without_seen_does_not_hang(self):
        # A snippet referencing itself must terminate: resolve_inline never
        # recurses, so it expands exactly one level and stops.
        snippets = {"xself": "a %%xself%% b"}
        result, timed_out = _resolve_in_thread("%%xself%%", snippets, lambda: None)
        self.assertFalse(timed_out, "resolve_inline hung on a self-reference")
        self.assertEqual(result, "a %%xself%% b")

    def test_mutual_cycle_without_seen_does_not_hang(self):
        snippets = {"A": "%%B%%", "B": "%%A%%"}
        result, timed_out = _resolve_in_thread(
            "%%A%% %%B%%", snippets, lambda: None
        )
        self.assertFalse(timed_out, "resolve_inline hung on a mutual cycle")
        # Single left-to-right pass swaps each token once; no further passes.
        self.assertEqual(result, "%%A%% %%A%%")

    def test_notify_failure_is_optional_on_raising_callable(self):
        # Without a notify callback, a raising dynamic ref still yields "".
        def boom():
            raise RuntimeError("x")

        result = resolve_inline("v=%%x%%", {"x": boom}, lambda: None)
        self.assertEqual(result, "v=")


if __name__ == "__main__":
    unittest.main()
