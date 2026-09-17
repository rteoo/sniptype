import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from form_editor_dialog import FormEditorController
from form_support import FormValidationError


class FormEditorControllerTests(unittest.TestCase):
    def test_edits_are_ordered_and_do_not_mutate_input_until_save(self):
        initial = {"fields": [{"name": "name", "type": "text", "default": "Ana"}]}
        original = copy.deepcopy(initial)
        controller = FormEditorController(initial)

        added = controller.add_field("multiline")
        controller.update_field(added, name="details", default="notes")
        controller.move_field(added, -1)
        controller.update_field(0, label="Nome completo")

        self.assertEqual(original, initial)
        self.assertEqual(["details", "name"], [field["name"] for field in controller.fields])
        self.assertIsNone(controller.result)

    def test_remove_and_cancel_leave_no_result(self):
        controller = FormEditorController({"fields": [
            {"name": "first"}, {"name": "second"},
        ]})
        controller.remove_field(0)
        self.assertEqual(["second"], [field["name"] for field in controller.fields])
        self.assertIsNone(controller.cancel())
        self.assertIsNone(controller.result)

    def test_save_returns_persisted_definition_with_type_specific_keys(self):
        controller = FormEditorController({"fields": [
            {"name": "name", "label": "Name", "default": "Ana", "type": "text"},
            {"name": "body", "type": "multiline", "default": "line"},
            {"name": "kind", "type": "choice", "options": ["A", "B"], "default": "B"},
            {"name": "when", "type": "date", "default": "today", "output_format": "%Y-%m-%d"},
            {"name": "enabled", "type": "optional", "content": "Include", "default": True},
        ]})

        result = controller.save()

        self.assertEqual(result, controller.result)
        self.assertEqual(
            {"name": "kind", "type": "choice", "default": "B", "options": ["A", "B"]},
            result["fields"][2],
        )
        self.assertEqual(
            {"name": "enabled", "type": "optional", "default": True, "content": "Include"},
            result["fields"][4],
        )
        self.assertEqual("today", result["fields"][3]["default"])

    def test_save_uses_form_support_validation_and_identifies_invalid_field(self):
        controller = FormEditorController(
            {"fields": [{"name": "existing", "type": "text"}]},
            snippets={"existing": "a snippet"},
        )

        with self.assertRaises(FormValidationError):
            controller.save()

        self.assertIsNone(controller.result)
        self.assertEqual(0, controller.invalid_index)
        self.assertIn("collides", controller.error)

    def test_template_validation_rejects_missing_or_unused_fields(self):
        controller = FormEditorController(
            {"fields": [{"name": "unused", "type": "text"}]},
            template="Hello %%name%%",
        )

        with self.assertRaises(FormValidationError):
            controller.save()

        self.assertIn("missing: name", controller.error)
        self.assertIn("unused: unused", controller.error)

    def test_reorder_bounds_are_safe_and_invalid_indexes_are_actionable(self):
        controller = FormEditorController({"fields": [{"name": "one"}]})
        self.assertEqual(0, controller.move_field(0, -1))
        self.assertEqual(0, controller.move_field(0, 1))
        with self.assertRaises(IndexError):
            controller.update_field(2, name="bad")


if __name__ == "__main__":
    unittest.main()
