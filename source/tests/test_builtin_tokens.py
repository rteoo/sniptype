"""Built-in tokens: %%_date…%% renders a date, %%_cursor%% places the caret.

Neither may ever be read as a form field: a form would then pop up asking the
person for "_date". Each surface that classifies variables is checked here.
"""

import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import builtin_tokens
import sync_export
from builtin_tokens import CARET_MARK, builtin_kind, plan_insertion, render_date, split_cursor, steps_text
from form_support import compile_form
from preview_support import CURSOR_PLACEHOLDER, resolve_preview
from rich_text_support import build_rich_text_payload, extract_plain_text
from snippet_utils import get_dynamic_prefixes
from trigger_index import compile_trigger_index
from variable_support import classify_variable, has_form_variables, has_key_tokens, resolve_inline

# A Saturday, the last day of a 31-day month.
NOW = datetime(2026, 1, 31, 9, 5, 7)


class GrammarTests(unittest.TestCase):
    def test_kinds(self):
        for name, kind in [
            ("_date", "date"), ("_date+10d", "date"), ("_date-3w", "date"), ("_date:HH:mm", "date"),
            ("_date+1y:dd/MM", "date"), ("_cursor", "cursor"),
            ("_date+1x", None), ("_date+1234d", None), ("_dates", None), ("_date:", None),
            ("_cursorx", None), ("date", None), ("cursor", None),
        ]:
            with self.subTest(name=name):
                self.assertEqual(kind, builtin_kind(name))

    def test_formats(self):
        for name, text in [
            ("_date", "31/01/2026"),
            ("_date:yyyy-MM-dd", "2026-01-31"),
            ("_date:HH:mm:ss", "09:05:07"),
            ("_date:H|d|M|yy", "9|31|1|26"),
            ("_date:dddd,dd-MMMM-yyyy", "sábado,31-janeiro-2026"),
            ("_date:ddd/MMM", "sáb/jan"),
            # Letters that are no pattern are copied as they are.
            ("_date:dd.MM.yyyy(x)", "31.01.2026(x)"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(text, render_date(name, NOW))

    def test_offsets_clamp_to_the_end_of_a_shorter_month(self):
        for name, now, text in [
            ("_date-1d", NOW, "30/01/2026"),
            ("_date+2w", NOW, "14/02/2026"),
            ("_date+1m", NOW, "28/02/2026"),
            ("_date-1m", datetime(2026, 3, 31), "28/02/2026"),
            ("_date+1y", datetime(2024, 2, 29), "28/02/2025"),
            ("_date+13m:MM/yyyy", NOW, "02/2027"),
            ("_date+999y:yyyy", NOW, "3025"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(text, render_date(name, now))


class SplitCursorTests(unittest.TestCase):
    def test_plain_text_loses_the_mark_and_counts_what_follows(self):
        self.assertEqual(("Olá , tudo", 6), split_cursor(f"Olá {CARET_MARK}, tudo"))

    def test_a_line_break_is_one_step_back(self):
        self.assertEqual(("ab\r\nc", 3), split_cursor(f"a{CARET_MARK}b\r\nc"))

    def test_without_a_mark_the_payload_is_untouched(self):
        payload = build_rich_text_payload("Bold", [{"tag": "bold", "start": 0, "end": 4}])
        self.assertEqual((payload, 0), split_cursor(payload))

    def test_the_first_mark_wins_and_every_mark_is_removed(self):
        self.assertEqual(("abc", 2), split_cursor(f"a{CARET_MARK}b{CARET_MARK}c"))

    def test_rich_text_keeps_its_styles(self):
        payload = build_rich_text_payload(f"Bold{CARET_MARK} x", [{"tag": "bold", "start": 0, "end": 4}])
        result, back = split_cursor(payload)
        self.assertEqual(("Bold x", 2), (extract_plain_text(result), back))
        self.assertEqual([{"tag": "bold", "start": 0, "end": 4}], result["spans"])


class ResolverTests(unittest.TestCase):
    def test_builtins_are_never_form_fields(self):
        self.assertEqual("date", classify_variable("_date:yyyy", {}))
        self.assertEqual("cursor", classify_variable("_cursor", {}))
        self.assertFalse(has_form_variables("%%_date%% %%_cursor%%", {}))

    def test_inline_resolution_renders_the_date_and_marks_the_caret(self):
        with mock.patch.object(builtin_tokens, "datetime", mock.Mock(now=mock.Mock(return_value=NOW))):
            text = resolve_inline("Em %%_date%%, %%_cursor%%!", {}, lambda: "")
        self.assertEqual(f"Em 31/01/2026, {CARET_MARK}!", text)

    def test_a_cursor_token_inside_clipboard_text_stays_literal(self):
        text = resolve_inline("%%clipboard-paste%%|%%_cursor%%", {}, lambda: "x%%_cursor%%y")
        self.assertEqual(("x%%_cursor%%y|", 0), split_cursor(text))

    def test_strict_forms_need_no_definition_for_builtins(self):
        compiled = compile_form("Oi %%nome%% %%_date%% %%_cursor%%", [{"name": "nome", "type": "text"}], {})
        self.assertEqual(("nome",), compiled.field_names)

    def test_preview_shows_the_date_and_where_the_caret_lands(self):
        result = resolve_preview("A %%_cursor%% B %%_date:yyyy%%", {})
        self.assertEqual(f"A {CURSOR_PLACEHOLDER} B {datetime.now().year}", result.payload)
        self.assertEqual((), result.unavailable)


class SyncExportTests(unittest.TestCase):
    def test_the_phone_gets_the_text_without_the_caret_token(self):
        self.assertEqual(("Oi !", None), sync_export._resolve_export_text("Oi %%_cursor%%!", {}, {}))

    def test_a_date_is_never_baked_and_makes_the_phone_refuse_the_entry(self):
        text, block = sync_export._resolve_export_text("Em %%_date%%", {}, get_dynamic_prefixes({}))
        self.assertEqual("Em %%_date%%", text)
        self.assertIsNotNone(block)


ENTER, TAB = builtin_tokens.builtin_value("_enter"), builtin_tokens.builtin_value("_tab")


class KeyTokenTests(unittest.TestCase):
    def test_keys_are_builtins_never_form_fields(self):
        self.assertEqual("key", classify_variable("_enter", {}))
        self.assertEqual("key", classify_variable("_tab", {}))
        self.assertFalse(has_form_variables("%%_enter%% %%_tab%%", {}))
        self.assertTrue(has_key_tokens("a%%_tab%%b"))
        self.assertFalse(has_key_tokens("a%%clipboard-paste%%b %%_cursor%%"))

    def test_plan_alternates_pastes_and_keys(self):
        steps, back = plan_insertion(f"Nome{TAB}Fulano{ENTER}")
        self.assertEqual([("text", "Nome"), ("key", "tab"), ("text", "Fulano"), ("key", "enter")], steps)
        self.assertEqual(0, back)

    def test_without_keys_the_plan_is_the_one_paste(self):
        self.assertEqual(([("text", "abc")], 1), plan_insertion(f"ab{CARET_MARK}c"))
        self.assertEqual(([("text", "")], 0), plan_insertion(""))

    def test_consecutive_keys_have_no_empty_paste_between_them(self):
        self.assertEqual([("key", "tab"), ("key", "tab"), ("text", "x")], plan_insertion(f"{TAB}{TAB}x")[0])

    def test_cursor_after_the_last_key_moves_back_within_the_last_paste(self):
        self.assertEqual(([("text", "x"), ("key", "tab"), ("text", "yz")], 1),
                         plan_insertion(f"x{TAB}y{CARET_MARK}z"))

    def test_cursor_before_a_key_is_dropped(self):
        self.assertEqual(([("text", "ab"), ("key", "enter"), ("text", "c")], 0),
                         plan_insertion(f"a{CARET_MARK}b{ENTER}c"))

    def test_rich_text_styles_are_clipped_to_each_paste(self):
        payload = build_rich_text_payload(f"Bold{TAB}more", [{"tag": "bold", "start": 0, "end": 7}])
        steps, _back = plan_insertion(payload)
        self.assertEqual([{"tag": "bold", "start": 0, "end": 4}], steps[0][1]["spans"])
        self.assertEqual([{"tag": "bold", "start": 0, "end": 2}], steps[2][1]["spans"])
        self.assertEqual("more", extract_plain_text(steps[2][1]))

    def test_unsent_steps_read_as_text_with_keys_as_whitespace(self):
        self.assertEqual("a\tb\n", steps_text([("text", "a"), ("key", "tab"), ("text", "b"), ("key", "enter")]))

    def test_a_key_token_inside_clipboard_text_stays_literal(self):
        text = resolve_inline("%%clipboard-paste%%%%_tab%%", {}, lambda: "x%%_enter%%")
        self.assertEqual([("text", "x%%_enter%%"), ("key", "tab")], plan_insertion(text)[0])

    def test_preview_names_the_keys(self):
        self.assertEqual("a‹Tab›b‹Enter›", resolve_preview("a%%_tab%%b%%_enter%%", {}).payload)

    def test_the_phone_refuses_an_entry_that_presses_keys(self):
        text, block = sync_export._resolve_export_text("a%%_tab%%b", {}, {})
        self.assertEqual("a%%_tab%%b", text)
        self.assertIsNotNone(block)

    def test_snippets_that_press_keys_take_the_slow_route(self):
        index = compile_trigger_index(
            {"xform": "a%%_tab%%b", "xplain": "ab", "_cpf_numbers": {"fulano": "1%%_enter%%"}}, set()
        )
        self.assertEqual({"xform", "cpffulano"}, set(index["key_triggers"]))


if __name__ == "__main__":
    unittest.main()
