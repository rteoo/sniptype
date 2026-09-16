import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from group_dialog import (
    APPLICATION_LABELS,
    TERMINATOR_LABELS,
    GroupDialogController,
    build_group_definition,
    normalize_executable_lines,
)


class FakeControl:
    def __init__(self, value):
        self.value = value
        self.focused = False

    def get(self):
        return self.value

    def focus_set(self):
        self.focused = True


class GroupDialogTests(unittest.TestCase):
    def test_executables_are_casefolded_deduplicated_and_stored_as_basenames(self):
        self.assertEqual(
            ("outlook.exe", "notepad.exe"),
            normalize_executable_lines(
                "OUTLOOK.EXE\nC:\\Windows\\NOTEPAD.EXE\noutlook.exe\n"
            ),
        )

    def test_blank_executable_lines_are_ignored_and_invalid_line_is_rejected(self):
        self.assertEqual((), normalize_executable_lines("\n  \n"))
        with self.assertRaisesRegex(ValueError, "linha 1"):
            normalize_executable_lines("\\")

    def test_builds_schema_v1_group_definition(self):
        result = build_group_definition({
            "label": "  Financeiro ",
            "notes": "Uso interno",
            "prefix": "fin-",
            "enabled": False,
            "terminator": "terminator",
            "application_mode": "allow",
            "executables": "EXCEL.EXE\nexcel.exe",
        })
        self.assertEqual({
            "label": "Financeiro",
            "notes": "Uso interno",
            "prefix": "fin-",
            "enabled": False,
            "terminator": "terminator",
            "applications": {"mode": "allow", "executables": ["excel.exe"]},
        }, result)

    def test_accepts_display_labels_for_selectors(self):
        result = build_group_definition({
            "label": "Grupo",
            "terminator": TERMINATOR_LABELS["immediate"],
            "application_mode": APPLICATION_LABELS["deny"],
        })
        self.assertEqual("immediate", result["terminator"])
        self.assertEqual("deny", result["applications"]["mode"])

    def test_prefix_cannot_contain_whitespace(self):
        with self.assertRaisesRegex(ValueError, "prefixo"):
            build_group_definition({"label": "Grupo", "prefix": "work "})

    def test_required_label_invalid_value_keeps_dialog_open_and_focuses_label(self):
        controls = {"label": FakeControl("   ")}
        controller = GroupDialogController(controls=controls)

        self.assertFalse(controller.save())
        self.assertIsNone(controller.result)
        self.assertEqual("label", controller.invalid_field)
        self.assertTrue(controls["label"].focused)
        self.assertIn("obrigatório", controller.error)

    def test_invalid_executable_keeps_dialog_open_and_focuses_executable_control(self):
        controls = {
            "label": FakeControl("Grupo"),
            "executables": FakeControl("\\"),
        }
        controller = GroupDialogController(controls=controls)

        self.assertFalse(controller.save())
        self.assertEqual("executables", controller.invalid_field)
        self.assertTrue(controls["executables"].focused)

    def test_save_then_cancel_discards_result(self):
        controls = {"label": FakeControl("Grupo")}
        controller = GroupDialogController(controls=controls)

        self.assertTrue(controller.save())
        self.assertEqual("Grupo", controller.result["label"])
        controller.cancel()
        self.assertIsNone(controller.result)
        self.assertIsNone(controller.error)


if __name__ == "__main__":
    unittest.main()
