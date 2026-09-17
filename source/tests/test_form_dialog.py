import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from form_dialog import FormDialogController, month_grid
from form_support import compile_form


class FakeControl:
    def __init__(self, value="", *, multiline=False):
        self.value = value
        self.multiline = multiline
        self.focused = False

    def get(self, *args):
        return self.value

    def focus_set(self):
        self.focused = True


class FormDialogControllerTests(unittest.TestCase):
    def test_collects_multiline_and_scalar_controls(self):
        form = compile_form(
            "%%nome%%\n%%notas%%",
            [
                {"name": "nome", "default": "Cliente"},
                {"name": "notas", "type": "multiline", "default": "Observação"},
            ],
        )
        controls = {
            "nome": FakeControl("Ana"),
            "notas": FakeControl("linha 1\nlinha 2", multiline=True),
        }
        controller = FormDialogController(form, controls)

        self.assertTrue(controller.submit())
        self.assertEqual({"nome": "Ana", "notas": "linha 1\nlinha 2"}, controller.result)
        self.assertIsNone(controller.error)

    def test_invalid_value_keeps_dialog_open_and_focus_identifies_control(self):
        form = compile_form(
            "%%saudacao%%",
            [{"name": "saudacao", "type": "choice", "options": ["Olá", "Oi"]}],
        )
        control = FakeControl("Hey")
        controller = FormDialogController(form, {"saudacao": control})

        self.assertFalse(controller.submit())
        self.assertIsNone(controller.result)
        self.assertEqual("saudacao", controller.invalid_field)
        self.assertTrue(control.focused)
        self.assertIn("saudacao", controller.error)

    def test_cancel_clears_result_and_is_distinct_from_empty_submission(self):
        form = compile_form("%%nome%%", [{"name": "nome"}])
        controller = FormDialogController(form, {"nome": FakeControl("Ana")})
        self.assertTrue(controller.submit())
        controller.cancel()
        self.assertIsNone(controller.result)

    def test_month_grid_uses_standard_library_calendar(self):
        rows = month_grid(2026, 2)
        self.assertEqual(5, len(rows))
        self.assertEqual(1, rows[0][6])

    def test_date_default_today_is_resolved_when_controls_are_built(self):
        form = compile_form(
            "%%data%%",
            [{"name": "data", "type": "date", "default": "today"}],
        )
        with mock.patch("form_dialog.date") as date_type:
            date_type.today.return_value = date(2031, 7, 8)
            from form_dialog import _date_default

            self.assertEqual("2031-07-08", _date_default(form.fields[0]))


if __name__ == "__main__":
    unittest.main()
