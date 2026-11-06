"""Condition blocks: %%_if:COND%% … %%_elif%% … %%_else%% … %%_endif%%.

Only the branch that holds when the snippet expands is kept, and a dropped
branch must never ask for its form fields nor run its dynamic snippets.
"""

import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sync_export
import variable_support
from builtin_tokens import (
    AFTER_ELSE,
    STRAY_MARKER,
    UNCLOSED,
    UNKNOWN_CONDITION,
    ConditionError,
    builtin_kind,
    condition_problem,
    resolve_conditions,
)
from editor_session import mapping_draft_problem, static_draft_problem
from form_support import compile_form, fields_used_in
from preview_support import resolve_preview
from rich_text_support import build_rich_text_payload, extract_plain_text
from snippet_utils import get_dynamic_prefixes
from variable_support import classify_variable, expand_inline, has_form_variables, resolve_inline

# 2026-11-06 is a Friday.
MORNING = datetime(2026, 11, 6, 9, 0)
AFTERNOON = datetime(2026, 11, 6, 12, 0)
NIGHT = datetime(2026, 11, 6, 18, 0)
SATURDAY_DAWN = datetime(2026, 11, 7, 4, 59)

GREETING = (
    "%%_if:morning%%Bom dia, %%nome%%\n"
    "%%_elif:afternoon%%Boa tarde, %%nome%%\n"
    "%%_else%%Boa noite, %%nome%%\n"
    "%%_endif%%"
)


def at(now):
    """Patch the clock the inline resolver reads."""
    return mock.patch.object(variable_support, "datetime", mock.Mock(now=mock.Mock(return_value=now)))


class GrammarTests(unittest.TestCase):
    def test_markers_are_builtins_even_with_an_unknown_condition(self):
        for name in ("_if:morning", "_elif:fri", "_else", "_endif", "_if:breakfast", "_if"):
            self.assertEqual("condition", builtin_kind(name), name)
            self.assertEqual("condition", classify_variable(name, {}), name)
        for name in ("_elsewhere", "_ifx", "_endifs"):
            self.assertIsNone(builtin_kind(name), name)

    def test_markers_are_never_form_fields(self):
        self.assertFalse(has_form_variables("%%_if:morning%%a%%_else%%b%%_endif%%", {}))
        compiled = compile_form("%%_if:fri%%%%nome%%%%_endif%%", [{"name": "nome"}], {})
        self.assertEqual(("nome",), compiled.field_names)


class ResolveTests(unittest.TestCase):
    def test_the_greeting_follows_the_time_of_day(self):
        self.assertEqual("Bom dia, %%nome%%", resolve_conditions(GREETING, MORNING))
        self.assertEqual("Boa tarde, %%nome%%", resolve_conditions(GREETING, AFTERNOON))
        self.assertEqual("Boa noite, %%nome%%", resolve_conditions(GREETING, NIGHT))
        self.assertEqual("Boa noite, %%nome%%", resolve_conditions(GREETING, SATURDAY_DAWN))

    def test_period_boundaries(self):
        cases = [(4, "night"), (5, "morning"), (11, "morning"), (12, "afternoon"), (17, "afternoon"), (18, "night"), (23, "night")]
        for hour, period in cases:
            now = datetime(2026, 11, 6, hour, 59 if hour in (4, 11, 17) else 0)
            text = "%%_if:" + period + "%%yes%%_else%%no%%_endif%%"
            self.assertEqual("yes", resolve_conditions(text, now), (hour, period))

    def test_days(self):
        text = "%%_if:weekend%%fds%%_elif:fri%%sexta%%_elif:weekday%%útil%%_endif%%"
        self.assertEqual("sexta", resolve_conditions(text, MORNING))
        self.assertEqual("fds", resolve_conditions(text, SATURDAY_DAWN))
        self.assertEqual("útil", resolve_conditions(text, datetime(2026, 11, 2, 9)))

    def test_no_branch_holding_leaves_nothing_and_the_text_around_stays(self):
        self.assertEqual("Oi! Até.", resolve_conditions("Oi!%%_if:sat%% Bom fds!%%_endif%% Até.", MORNING))

    def test_line_breaks_touching_markers_are_layout(self):
        text = "Oi\n%%_if:fri%%\nBom fds\n%%_else%%\nBoa semana\n%%_endif%%\nAtt."
        self.assertEqual("Oi\nBom fds\nAtt.", resolve_conditions(text, MORNING))
        self.assertEqual("Oi\nBoa semana\nAtt.", resolve_conditions(text, datetime(2026, 11, 5, 9)))
        crlf = "%%_if:fri%%\r\nA\r\n%%_endif%%"
        self.assertEqual("A", resolve_conditions(crlf, MORNING))

    def test_only_one_line_break_is_layout(self):
        self.assertEqual("A\n", resolve_conditions("%%_if:fri%%A\n\n%%_endif%%", MORNING))

    def test_blocks_nest(self):
        text = "%%_if:weekday%%%%_if:morning%%útil cedo%%_else%%útil tarde%%_endif%%%%_else%%fds%%_endif%%"
        self.assertEqual("útil cedo", resolve_conditions(text, MORNING))
        self.assertEqual("útil tarde", resolve_conditions(text, NIGHT))
        self.assertEqual("fds", resolve_conditions(text, datetime(2026, 11, 7, 9)))

    def test_a_branch_inside_a_dropped_one_is_dropped(self):
        text = "%%_if:sat%%%%_if:morning%%x%%_endif%%%%_else%%y%%_endif%%"
        self.assertEqual("y", resolve_conditions(text, MORNING))

    def test_other_tokens_are_left_for_the_resolver(self):
        self.assertEqual("%%_date%% %%nome%%", resolve_conditions("%%_if:fri%%%%_date%% %%nome%%%%_endif%%", MORNING))

    def test_text_without_markers_is_returned_as_is(self):
        self.assertEqual("100%% off %%nome%%", resolve_conditions("100%% off %%nome%%", MORNING))


class ProblemTests(unittest.TestCase):
    def test_every_malformed_block_names_its_problem(self):
        cases = [
            ("%%_if:breakfast%%a%%_endif%%", UNKNOWN_CONDITION),
            ("%%_if%%a%%_endif%%", UNKNOWN_CONDITION),
            ("a%%_endif%%", STRAY_MARKER),
            ("%%_else%%a", STRAY_MARKER),
            ("%%_if:fri%%a%%_else%%b%%_else%%c%%_endif%%", AFTER_ELSE),
            ("%%_if:fri%%a%%_else%%b%%_elif:sat%%c%%_endif%%", AFTER_ELSE),
            ("%%_if:fri%%a", UNCLOSED),
        ]
        for text, problem in cases:
            self.assertEqual(problem, condition_problem(text), text)
            with self.assertRaises(ConditionError):
                resolve_conditions(text, MORNING)

    def test_an_unknown_condition_in_a_dropped_branch_is_still_reported(self):
        self.assertEqual(UNKNOWN_CONDITION, condition_problem("%%_if:fri%%a%%_elif:brunch%%b%%_endif%%"))

    def test_well_formed_text_has_no_problem(self):
        self.assertIsNone(condition_problem(GREETING))
        self.assertIsNone(condition_problem("sem condição"))

    def test_both_editors_refuse_to_save_a_malformed_block(self):
        self.assertEqual(UNCLOSED, static_draft_problem("xoi", "%%_if:fri%%a"))
        self.assertEqual(UNCLOSED, mapping_draft_problem("alice", "%%_if:fri%%a"))
        self.assertIsNone(static_draft_problem("xoi", GREETING))


class ExpansionTests(unittest.TestCase):
    def test_inline_resolution_keeps_the_branch_that_holds(self):
        with at(AFTERNOON):
            self.assertEqual("Boa tarde, Ana", resolve_inline(GREETING.replace("%%nome%%", "Ana"), {}, lambda: ""))

    def test_a_dropped_branch_never_reads_the_clipboard_nor_runs_a_dynamic_snippet(self):
        provider = mock.Mock(return_value="R$ 5,00")
        clipboard = mock.Mock(return_value="copiado")
        text = "%%_if:sat%%%%xdolar%% %%clipboard-paste%%%%_else%%Sem cotação%%_endif%%"
        with at(MORNING):
            template, values = expand_inline(text, {"xdolar": provider}, clipboard)
        self.assertEqual(("Sem cotação", {}), (template, values))
        provider.assert_not_called()
        clipboard.assert_not_called()

    def test_a_dropped_branch_leaves_its_form_fields_out(self):
        snippets = {}
        with at(MORNING):
            template, _values = expand_inline("%%_if:morning%%Oi %%nome%%%%_else%%Oi %%apelido%%%%_endif%%", snippets, str)
        fields = [{"name": "nome"}, {"name": "apelido", "type": "choice", "options": ["a"]}]
        compiled = compile_form(template, fields_used_in(fields, template), snippets)
        self.assertEqual(("nome",), compiled.field_names)

    def test_a_referenced_snippet_resolves_its_own_conditions(self):
        snippets = {"xsaud": "%%_if:morning%%Bom dia%%_else%%Olá%%_endif%%"}
        with at(MORNING):
            self.assertEqual("Bom dia, Ana", resolve_inline("%%xsaud%%, Ana", snippets, str))
        with at(NIGHT):
            self.assertEqual("Olá, Ana", resolve_inline("%%xsaud%%, Ana", snippets, str))

    def test_a_malformed_block_fails_the_expansion(self):
        with self.assertRaises(ConditionError):
            resolve_inline("%%_if:fri%%a", {}, str)


class PreviewTests(unittest.TestCase):
    def test_preview_shows_the_branch_that_holds_now_with_its_form(self):
        fields = [{"name": "nome", "default": "Ana"}]
        result = resolve_preview(GREETING, {}, fields, {"nome": "Bia"})
        greeting = resolve_conditions(GREETING, datetime.now()).replace("%%nome%%", "Bia")
        self.assertEqual(greeting, result.payload)

    def test_preview_drops_fields_and_values_of_a_dropped_branch(self):
        text = "%%_if:morning%%%%a%%%%_elif:afternoon%%%%a%%%%_else%%%%a%%%%_endif%%%%_if:sat%%%%b%%%%_endif%%"
        fields = [{"name": "a", "default": "A"}, {"name": "b", "default": "B"}]
        result = resolve_preview(text, {}, fields, {"a": "x", "b": "y"})
        expected = "x" + ("y" if datetime.now().weekday() == 5 else "")
        self.assertEqual(expected, result.payload)

    def test_rich_text_keeps_the_styles_of_the_kept_branch(self):
        text = "%%_if:sat%%Sábado%%_else%%Outro dia%%_endif%%"
        start = text.index("Outro")
        payload = build_rich_text_payload(text, [{"tag": "bold", "start": start, "end": start + len("Outro dia")}])
        with mock.patch("preview_support.datetime", mock.Mock(now=mock.Mock(return_value=MORNING))):
            result = resolve_preview(payload, {})
        self.assertEqual("Outro dia", extract_plain_text(result.payload))
        self.assertEqual([{"tag": "bold", "start": 0, "end": 9}], result.payload["spans"])


class SyncExportTests(unittest.TestCase):
    def test_the_phone_refuses_an_entry_with_a_condition(self):
        text, block = sync_export._resolve_export_text(GREETING, {}, get_dynamic_prefixes({}))
        self.assertIsNotNone(block)
        self.assertIn("_if:morning", block["residual"])


if __name__ == "__main__":
    unittest.main()
