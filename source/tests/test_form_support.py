import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from form_support import (
    CompiledForm,
    FormField,
    FormValidationError,
    compile_form,
    infer_legacy_fields,
    render_form,
    validate_form_fields,
)


class FormSupportTests(unittest.TestCase):
    def test_legacy_form_infers_unique_text_fields_in_template_order(self):
        form = compile_form("Olá %%nome%%, %%nome%%. Cidade: %%cidade%%")

        self.assertIsInstance(form, CompiledForm)
        self.assertTrue(form.legacy)
        self.assertEqual(
            (FormField("nome"), FormField("cidade")), form.fields
        )
        self.assertEqual("Olá Ana, Ana. Cidade: Goiânia", render_form(
            form, {"nome": "Ana", "cidade": "Goiânia"}
        ))

    def test_defaults_and_multiline_values_render_in_one_pass(self):
        form = compile_form(
            "Nome: %%nome%%\nObservações:\n%%notas%%",
            [
                {"name": "nome", "type": "text", "default": "Cliente"},
                {"name": "notas", "type": "multiline", "default": "Linha 1"},
            ],
        )

        self.assertEqual(
            "Nome: Cliente\nObservações:\nA\nB",
            render_form(form, {"notas": "A\nB"}),
        )
        literal = render_form(form, {"nome": "%%notas%%", "notas": "ok"})
        self.assertEqual("Nome: %%notas%%\nObservações:\nok", literal)

    def test_choice_requires_an_option_and_uses_default(self):
        form = compile_form(
            "Saudação: %%saudacao%%",
            [{"name": "saudacao", "type": "choice", "options": ["Olá", "Oi"], "default": "Oi"}],
        )
        self.assertEqual("Saudação: Oi", render_form(form, {}))
        with self.assertRaises(FormValidationError):
            render_form(form, {"saudacao": "Hey"})

    def test_date_stores_iso_input_and_formats_output(self):
        form = compile_form(
            "Vencimento: %%vencimento%%",
            [{"name": "vencimento", "type": "date", "default": "2026-09-16", "output_format": "%Y/%m/%d"}],
        )
        self.assertEqual("Vencimento: 2026/09/16", render_form(form, {}))
        self.assertEqual("Vencimento: 2027/01/02", render_form(form, {"vencimento": "2027-01-02"}))

    def test_date_today_default_is_evaluated_when_rendered(self):
        form = compile_form(
            "Hoje: %%hoje%%",
            [{"name": "hoje", "type": "date", "default": "today", "output_format": "%Y-%m-%d"}],
        )
        with mock.patch("form_support.date") as date_type:
            date_type.today.return_value = date(2030, 4, 5)
            self.assertEqual("Hoje: 2030-04-05", render_form(form, {}))

    def test_optional_uses_literal_content_or_empty(self):
        form = compile_form(
            "Oi\n%%assinatura%%",
            [{"name": "assinatura", "type": "optional", "content": "Atenciosamente,\nAna"}],
        )
        self.assertEqual("Oi\n", render_form(form, {}))
        self.assertEqual("Oi\nAtenciosamente,\nAna", render_form(form, {"assinatura": True}))

    def test_dataclass_fields_are_normalized_like_persisted_definitions(self):
        form = compile_form(
            "%%assinar%%",
            [FormField("assinar", "optional", content="Ana")],
        )
        self.assertEqual("", render_form(form, {}))
        self.assertEqual("Ana", render_form(form, {"assinar": True}))

    def test_missing_and_extra_metadata_definitions_are_rejected(self):
        with self.assertRaises(FormValidationError):
            compile_form("%%nome%% %%cidade%%", [{"name": "nome"}])
        with self.assertRaises(FormValidationError):
            compile_form("%%nome%%", [{"name": "nome"}, {"name": "extra"}])

    def test_duplicate_definitions_and_invalid_specs_are_rejected(self):
        with self.assertRaises(FormValidationError):
            validate_form_fields([{"name": "nome"}, {"name": "nome"}])
        with self.assertRaises(FormValidationError):
            validate_form_fields([{"name": "nome", "type": "choice", "options": []}])
        with self.assertRaises(FormValidationError):
            validate_form_fields([{"name": "data", "type": "date", "default": "not-a-date"}])

    def test_collisions_follow_existing_variable_precedence(self):
        snippets = {
            "xstatic": "value",
            "xdynamic": lambda: "value",
            "_cpf_numbers": {"fulano": "123", "__prefix__": "cpf"},
        }
        for name in ("clipboard-paste", "xstatic", "xdynamic", "cpffulano"):
            with self.subTest(name=name), self.assertRaises(FormValidationError):
                compile_form(f"%%{name}%%", [{"name": name}], snippets)

    def test_structured_form_can_mix_inline_references(self):
        snippets = {
            "xstatic": "Ana",
            "xdynamic": lambda: "ignored here",
            "_cpf_numbers": {"fulano": "123", "__prefix__": "cpf"},
        }
        form = compile_form(
            "Nome: %%xstatic%% / CPF: %%cpffulano%% / Data: %%data%% / Clip: %%clipboard-paste%%",
            [{"name": "data", "default": "hoje"}],
            snippets,
        )
        self.assertEqual(
            "Nome: %%xstatic%% / CPF: %%cpffulano%% / Data: hoje / Clip: %%clipboard-paste%%",
            render_form(form, {}),
        )

    def test_legacy_inference_excludes_existing_references(self):
        snippets = {"xnome": "Ana", "_cpf_numbers": {"fulano": "123"}}
        self.assertEqual(
            (FormField("cidade"),),
            infer_legacy_fields("%%xnome%% %%cpffulano%% %%cidade%%", snippets),
        )

    def test_unknown_field_values_are_rejected(self):
        form = compile_form("%%nome%%", [{"name": "nome"}])
        with self.assertRaises(FormValidationError):
            render_form(form, {"nome": "Ana", "extra": "x"})


if __name__ == "__main__":
    unittest.main()
