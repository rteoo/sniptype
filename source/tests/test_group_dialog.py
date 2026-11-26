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
    normalize_group_icon,
)
from library_metadata import build_library_document, merge_metadata, update_group


class FakeControl:
    def __init__(self, value):
        self.value = value
        self.focused = False

    def get(self):
        return self.value

    def focus_set(self):
        self.focused = True


class GroupDialogTests(unittest.TestCase):
    def test_legacy_dialog_edit_and_export_import_preserve_icon(self):
        icon = {"kind": "lucide", "value": "folder-open"}
        metadata = {"kind": "sniptype_metadata", "schema_version": 1,
                    "groups": {"g": {"label": "Old", "icon": icon}}, "items": {}}
        controller = GroupDialogController(metadata["groups"]["g"], {"label": FakeControl("New")})
        self.assertTrue(controller.save())
        edited = update_group(metadata, "g", controller.result)
        exported = build_library_document({}, edited)["__sniptype__"]
        imported = merge_metadata({}, exported, "replace")
        self.assertEqual(icon, imported["groups"]["g"]["icon"])

    def test_icon_validation_accepts_single_sequences_and_rejects_unsafe_values(self):
        for kind, value in (("lucide", "folder-open"), ("emoji", "📁"),
                            ("emoji", "👩🏽‍💻"), ("emoji", "🇧🇷"), ("emoji", "1️⃣"),
                            ("emoji", "↗️"), ("emoji", "\U0001f3f4\U000e0067\U000e0062"
                             "\U000e0065\U000e006e\U000e0067\U000e007f")):
            with self.subTest(value=value):
                icon = {"kind": kind, "value": value}
                self.assertEqual(icon, normalize_group_icon(icon))
                self.assertEqual(icon, build_group_definition({"label": "Group", "icon": icon})["icon"])
        for icon in ({"kind": "lucide", "value": "<script>"}, {"kind": "lucide", "value": "a" * 65},
                     {"kind": "emoji", "value": "📁📂"}, {"kind": "emoji", "value": "hello"},
                     {"kind": "emoji", "value": "📁‍"}, {"kind": "other", "value": "📁"},
                     {"kind": "emoji", "value": "📁", "extra": 1}):
            with self.subTest(icon=icon):
                self.assertIsNone(normalize_group_icon(icon))
                with self.assertRaises(ValueError):
                    build_group_definition({"label": "Group", "icon": icon})

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

    def test_invalid_value_keeps_dialog_open_and_focuses_its_control(self):
        for old_test, values, invalid_field, fragment in (
            ("test_required_label_invalid_value_keeps_dialog_open_and_focuses_label",
             {"label": "   "}, "label", "obrigatório"),
            ("test_invalid_executable_keeps_dialog_open_and_focuses_executable_control",
             {"label": "Grupo", "executables": "\\"}, "executables", None),
        ):
            with self.subTest(old_test):
                controls = {name: FakeControl(value) for name, value in values.items()}
                controller = GroupDialogController(controls=controls)

                self.assertFalse(controller.save())
                self.assertIsNone(controller.result)
                self.assertEqual(invalid_field, controller.invalid_field)
                self.assertTrue(controls[invalid_field].focused)
                if fragment is not None:
                    self.assertIn(fragment, controller.error)

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
