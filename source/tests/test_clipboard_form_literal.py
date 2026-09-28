"""Substituted data stays literal during form expansion.

Clipboard text, dynamic provider output and values typed into the form dialog
are data. A ``%%token%%`` inside any of them must never become a new form field
or be substituted by a later pass. Static snippet and mapping references are
library content, so the form fields their bodies carry are still prompted for.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_module import sniptype as tx  # .pyw is not importable off Windows
from form_support import compile_form, render_form
from rich_text_support import build_rich_text_payload, is_rich_text_payload
from test_hotpath import make_app
from variable_support import resolve_form_variables, resolve_inline


def _dialog_answering(values):
    """A ``_show_form_dialog`` stand-in that answers every field it is asked for."""
    def show(field_names, compiled_form=None):
        return {name: values.get(name, "REPLACED") for name in field_names}
    return show


class FormExpansionKeepsClipboardLiteralTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _expand(self, app, trigger, clipboard_text, answers):
        dialog = mock.Mock(side_effect=_dialog_answering(answers))
        with mock.patch.object(app, "_show_form_dialog", dialog), \
                mock.patch.object(tx.Clipboard, "get_text", return_value=clipboard_text), \
                mock.patch.object(tx.time, "sleep"):
            app._run_expansion(trigger)
        app.text_inserter.insert_text.assert_called_once()
        return dialog, app.text_inserter.insert_text.call_args.args[0]

    def test_plain_form_clipboard_token_creates_no_field(self):
        app = make_app(self.tmp, {"xhi": "Hi %%name%% %%clipboard-paste%%"})
        dialog, inserted = self._expand(app, "xhi", "%%extra%%", {"name": "Ana"})
        self.assertEqual(["name"], dialog.call_args.args[0])
        self.assertEqual("Hi Ana %%extra%%", inserted)

    def test_structured_form_clipboard_token_creates_no_field(self):
        app = make_app(self.tmp, {"xhi": "Hi %%name%% %%clipboard-paste%%"})
        app.library_metadata = {
            "items": {"static": {"xhi": {"form": {"fields": [{"name": "name"}]}}}}
        }
        app.refresh_runtime_indexes()
        dialog, inserted = self._expand(app, "xhi", "%%extra%%", {"name": "Ana"})
        self.assertEqual(["name"], dialog.call_args.args[0])
        self.assertEqual("Hi Ana %%extra%%", inserted)

    def test_structured_form_clipboard_token_naming_a_real_field_stays_literal(self):
        app = make_app(self.tmp, {"xhi": "Hi %%name%% %%clipboard-paste%%"})
        app.library_metadata = {
            "items": {"static": {"xhi": {"form": {"fields": [{"name": "name"}]}}}}
        }
        app.refresh_runtime_indexes()
        _dialog, inserted = self._expand(app, "xhi", "%%name%%", {"name": "Ana"})
        self.assertEqual("Hi Ana %%name%%", inserted)

    def test_rich_text_form_clipboard_token_stays_literal(self):
        text = "Hi %%name%% %%clipboard-paste%%"
        rich = build_rich_text_payload(text, [{"tag": "bold", "start": 0, "end": 2}])
        app = make_app(self.tmp, {"xrich": rich})
        dialog, inserted = self._expand(app, "xrich", "%%extra%%", {"name": "Ana"})
        self.assertEqual(["name"], dialog.call_args.args[0])
        self.assertTrue(is_rich_text_payload(inserted))
        self.assertEqual("Hi Ana %%extra%%", inserted["text"])
        self.assertEqual([{"tag": "bold", "start": 0, "end": 2}], inserted["spans"])

    def test_referenced_snippet_fields_are_still_prompted(self):
        # xa routes to the form path through its own field; the one-level ref
        # then contributes its body's field to the same dialog.
        app = make_app(self.tmp, {
            "xb": "Prezado %%cliente%%",
            "xa": "%%xb%%, %%saudacao%% %%clipboard-paste%%",
        })
        dialog, inserted = self._expand(
            app, "xa", "%%extra%%", {"cliente": "Ana", "saudacao": "bom dia"}
        )
        self.assertEqual(["cliente", "saudacao"], dialog.call_args.args[0])
        self.assertEqual("Prezado Ana, bom dia %%extra%%", inserted)

    def test_dynamic_output_token_creates_no_field(self):
        app = make_app(self.tmp, {"xform": "%%xdyn%% %%name%%"})
        app.snippets["xdyn"] = lambda: "%%extra%%"
        dialog = mock.Mock(side_effect=_dialog_answering({"name": "Ana"}))
        with mock.patch.object(app, "_show_form_dialog", dialog), \
                mock.patch.object(tx.time, "sleep"):
            app.run_slow_snippet("xform")
        self.assertEqual(["name"], dialog.call_args.args[0])
        self.assertEqual("%%extra%% Ana", app.text_inserter.insert_text.call_args.args[0])

    def test_typed_form_value_naming_another_field_stays_literal(self):
        app = make_app(self.tmp, {"xab": "%%a%% %%b%%"})
        _dialog, inserted = self._expand(app, "xab", None, {"a": "%%b%%", "b": "X"})
        self.assertEqual("%%b%% X", inserted)

    def test_ordinary_form_is_unchanged(self):
        app = make_app(self.tmp, {"xhi": "Olá %%nome%%, clip=%%clipboard-paste%%"})
        dialog, inserted = self._expand(app, "xhi", "texto", {"nome": "Ana"})
        self.assertEqual(["nome"], dialog.call_args.args[0])
        self.assertEqual("Olá Ana, clip=texto", inserted)


class ResolverSinglePassTests(unittest.TestCase):
    """The support-module seams behind the form path."""

    def test_clipboard_token_matching_a_top_level_ref_stays_literal(self):
        snippets = {"xcity": "SP"}
        result = resolve_inline(
            "%%clipboard-paste%% %%xcity%%", snippets, lambda: "%%xcity%%"
        )
        self.assertEqual("%%xcity%% SP", result)

    def test_dynamic_output_matching_the_clipboard_token_stays_literal(self):
        snippets = {"xdyn": lambda: "%%clipboard-paste%%"}
        result = resolve_inline(
            "%%xdyn%% %%clipboard-paste%%", snippets, lambda: "CB"
        )
        self.assertEqual("%%clipboard-paste%% CB", result)

    def test_form_values_do_not_chain(self):
        result = resolve_form_variables("%%nome%%", {"nome": "%%data%%", "data": "X"})
        self.assertEqual("%%data%%", result)

    def test_render_form_substitutes_inline_values_in_the_same_pass(self):
        form = compile_form("Hi %%name%% %%clipboard-paste%%", [{"name": "name"}])
        result = render_form(
            form, {"name": "%%clipboard-paste%%"},
            inline_values={"clipboard-paste": "%%name%%"},
        )
        self.assertEqual("Hi %%clipboard-paste%% %%name%%", result)


if __name__ == "__main__":
    unittest.main()
