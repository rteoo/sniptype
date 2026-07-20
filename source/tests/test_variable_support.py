import unittest
from unittest.mock import patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from variable_support import (
    classify_variable,
    find_variable_names,
    has_form_variables,
    resolve_form_variables,
    resolve_inline,
)


class TestFindVariableNames(unittest.TestCase):

    def test_empty_string(self):
        self.assertEqual(find_variable_names(""), [])

    def test_no_variables(self):
        self.assertEqual(find_variable_names("hello world"), [])

    def test_single_variable(self):
        self.assertEqual(find_variable_names("%%nome%%"), ["nome"])

    def test_multiple_variables(self):
        self.assertEqual(find_variable_names("%%a%% e %%b%%"), ["a", "b"])

    def test_duplicates_deduplicated(self):
        self.assertEqual(find_variable_names("%%a%% %%a%%"), ["a"])

    def test_order_preserved(self):
        self.assertEqual(find_variable_names("%%z%% %%a%% %%m%%"), ["z", "a", "m"])

    def test_no_spaces_inside(self):
        # Spaces inside %% should not match (pattern requires non-whitespace)
        self.assertEqual(find_variable_names("%% name %%"), [])

    def test_clipboard_paste_name(self):
        self.assertEqual(find_variable_names("%%clipboard-paste%%"), ["clipboard-paste"])


class TestClassifyVariable(unittest.TestCase):

    def test_clipboard(self):
        self.assertEqual(classify_variable("clipboard-paste", {}), "clipboard")

    def test_snippet_ref(self):
        snippets = {"xname": "Example User"}
        self.assertEqual(classify_variable("xname", snippets), "snippet_ref")

    def test_callable_snippet_is_dynamic_ref(self):
        snippets = {"xcot": lambda: "R$10"}
        self.assertEqual(classify_variable("xcot", snippets), "dynamic_ref")

    def test_mapping_trigger_is_mapping_ref(self):
        snippets = {"_cpf_numbers": {"fulano": "123.456.789-00"}}
        self.assertEqual(classify_variable("cpffulano", snippets), "mapping_ref")

    def test_unknown_mapping_item_is_form_field(self):
        snippets = {"_cpf_numbers": {"fulano": "123.456.789-00"}}
        self.assertEqual(classify_variable("cpfciclano", snippets), "form_field")

    def test_unknown_name_is_form_field(self):
        self.assertEqual(classify_variable("nome", {}), "form_field")

    def test_nonexistent_key_is_form_field(self):
        snippets = {"xname": "Example User"}
        self.assertEqual(classify_variable("data", snippets), "form_field")


class TestHasFormVariables(unittest.TestCase):

    def test_no_variables(self):
        self.assertFalse(has_form_variables("plain text", {}))

    def test_only_clipboard(self):
        self.assertFalse(has_form_variables("%%clipboard-paste%%", {}))

    def test_only_snippet_ref(self):
        snippets = {"xname": "Example User"}
        self.assertFalse(has_form_variables("Olá %%xname%%", snippets))

    def test_only_mapping_ref(self):
        snippets = {"_cpf_numbers": {"fulano": "123"}}
        self.assertFalse(has_form_variables("CPF %%cpffulano%%", snippets))

    def test_only_dynamic_ref(self):
        self.assertFalse(has_form_variables("%%xcot%%", {"xcot": lambda: "R$10"}))

    def test_has_form_field(self):
        self.assertTrue(has_form_variables("Olá %%nome%%", {}))

    def test_mixed_with_form_field(self):
        snippets = {"xname": "Example User"}
        self.assertTrue(has_form_variables("%%xname%% e %%data%%", snippets))


class TestResolveInline(unittest.TestCase):

    def test_no_variables(self):
        result = resolve_inline("hello world", {}, lambda: None)
        self.assertEqual(result, "hello world")

    def test_clipboard_substitution(self):
        result = resolve_inline("cmd %%clipboard-paste%%", {}, lambda: "meu texto")
        self.assertEqual(result, "cmd meu texto")

    def test_clipboard_empty_becomes_empty_string(self):
        result = resolve_inline("cmd %%clipboard-paste%%", {}, lambda: None)
        self.assertEqual(result, "cmd ")

    def test_snippet_ref_plain(self):
        snippets = {"xaddr": "Rua das Flores, 10"}
        result = resolve_inline("Endereço: %%xaddr%%", snippets, lambda: None)
        self.assertEqual(result, "Endereço: Rua das Flores, 10")

    def test_snippet_ref_rich_text(self):
        snippets = {"xtitle": {"__kind__": "rich_text", "text": "Relatório"}}
        result = resolve_inline("Ver %%xtitle%%", snippets, lambda: None)
        self.assertEqual(result, "Ver Relatório")

    def test_callable_snippet_is_invoked(self):
        snippets = {"xcot": lambda: "R$10"}
        result = resolve_inline("%%xcot%%", snippets, lambda: None)
        self.assertEqual(result, "R$10")

    def test_callable_returning_none_becomes_empty(self):
        # Action-only flows (xwapp opens the browser) substitute nothing.
        snippets = {"xwapp": lambda: None}
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

    def test_mapping_ref_resolved(self):
        snippets = {"_cpf_numbers": {"fulano": "123.456.789-00"}}
        result = resolve_inline("CPF: %%cpffulano%%", snippets, lambda: None)
        self.assertEqual(result, "CPF: 123.456.789-00")

    def test_mapping_ref_rich_text_value(self):
        snippets = {"_custom_codes": {"__prefix__": "cc",
                                      "x": {"__kind__": "rich_text", "text": "ABC"}}}
        result = resolve_inline("%%ccx%%", snippets, lambda: None)
        self.assertEqual(result, "ABC")

    def test_dynamic_ref_circular_guard(self):
        snippets = {"xcot": lambda: "R$10"}
        result = resolve_inline("%%xcot%%", snippets, lambda: None, _seen={"xcot"})
        self.assertEqual(result, "%%xcot%%")

    def test_form_field_left_unchanged(self):
        result = resolve_inline("Olá %%nome%%", {}, lambda: None)
        self.assertEqual(result, "Olá %%nome%%")

    def test_circular_ref_guard(self):
        snippets = {"xself": "start %%xself%% end"}
        result = resolve_inline("%%xself%%", snippets, lambda: None, _seen={"xself"})
        self.assertEqual(result, "%%xself%%")

    def test_multiple_variables_mixed(self):
        snippets = {"xaddr": "Rua A"}
        result = resolve_inline(
            "Clip: %%clipboard-paste%%, Ref: %%xaddr%%, Form: %%nome%%",
            snippets,
            lambda: "CB",
        )
        self.assertEqual(result, "Clip: CB, Ref: Rua A, Form: %%nome%%")


class TestResolveFormVariables(unittest.TestCase):

    def test_single_field(self):
        result = resolve_form_variables("Olá %%nome%%", {"nome": "Carlos"})
        self.assertEqual(result, "Olá Carlos")

    def test_multiple_fields(self):
        result = resolve_form_variables(
            "%%nome%%, disponível em %%data%%?",
            {"nome": "Ana", "data": "segunda"},
        )
        self.assertEqual(result, "Ana, disponível em segunda?")

    def test_missing_key_leaves_token(self):
        result = resolve_form_variables("Olá %%nome%%", {})
        self.assertEqual(result, "Olá %%nome%%")

    def test_empty_value(self):
        result = resolve_form_variables("%%campo%%", {"campo": ""})
        self.assertEqual(result, "")

    def test_repeated_token(self):
        result = resolve_form_variables("%%x%% e %%x%%", {"x": "A"})
        self.assertEqual(result, "A e A")


if __name__ == "__main__":
    unittest.main()
