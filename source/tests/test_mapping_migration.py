"""Library upgrade through startup, backup restore, and the manager bridge."""

import json
from pathlib import Path
import unittest
from unittest import mock

from app_module import sniptype as tx
from library_metadata import METADATA_KIND, split_library_document
from manager_bridge import ManagerBridge
from mapping_migration import group_legacy_mappings
from rich_text_support import build_rich_text_payload
from sync_export import build_bundle
from test_manager_runtime import make_real_app
from trigger_index import find_direct_candidate


def manager(app):
    return ManagerBridge(app, version="9.9.9", channel="stable")


class MappingMigrationTests(unittest.TestCase):
    def test_startup_backs_up_and_migrates_values_metadata_and_references(self):
        rich = build_rich_text_payload("Hello %%who%%", [{"tag": "bold", "start": 0, "end": 5}])
        form = {"fields": [{"name": "who", "type": "text", "default": "world"}]}
        original = {
            "letter": "ID: %%cpfexample%%",
            "_cpf_numbers": {"example": "Test ID"},
            "_email_codes": {"__prefix__": "mail", "example": rich},
            "__sniptype__": {
                "kind": METADATA_KIND, "schema_version": 1,
                "groups": {"existing": {"label": "Existing group"}},
                "items": {"mappings": {"_email_codes": {"example": {"favorite": True, "form": form}}}},
            },
        }
        app = make_real_app(self, original)
        bridge = manager(app)
        path = Path(app.snippets_file)
        saved = path.read_bytes()
        backups = list(Path(app.backups_dir).glob("*.json"))
        self.assertTrue(any(json.loads(backup.read_bytes()) == original for backup in backups))
        self.assertFalse(bridge.app_info()["legacyMappings"])
        groups = {item["label"]: item["id"] for item in bridge.groups_list()["groups"]}
        self.assertEqual({"CPF", "EMAIL", "Existing group"}, groups.keys())
        (item,) = bridge.library_list(group=groups["EMAIL"])["items"]
        self.assertEqual(("mailexample", "mailexample", True, True),
                         (item["trigger"], item["effectiveTrigger"], item["favorite"], item["rich"]))
        self.assertEqual(rich, app.snippets["mailexample"])
        self.assertEqual(form, app._static_form_metadata("mailexample"))
        self.assertEqual("ID: Test ID", bridge.preview_get(name="letter")["text"])
        self.assertEqual("Hello world", bridge.preview_get(name="mailexample")["text"])
        self.assertEqual("cpfexample", find_direct_candidate("cpfexample", app.trigger_index).stable_identity)
        before_mobile = {item["trigger"]: item for item in build_bundle(original, {})["entries"]}
        after_mobile = {item["trigger"]: item for item in build_bundle(json.loads(saved), {})["entries"]}
        self.assertEqual(before_mobile, after_mobile)
        app.reload_snippets_from_disk()
        self.assertEqual(saved, path.read_bytes())
        self.assertEqual(backups, list(Path(app.backups_dir).glob("*.json")))

    def test_import_and_restore_project_legacy_data_before_counting(self):
        old = {"_email_codes": {"__prefix__": "mail", "team": "Test address"}}
        app = make_real_app(self, {"hello": "Hello"}, backups=[("snippets-20260201-000000.json", json.dumps(old))])
        path = str(Path(app.backups_dir) / "snippets-20260201-000000.json")
        counts = {"new": 1, "removed": 1, "overwritten": 0}
        self.assertEqual((counts, None), app.preview_restore(path))
        self.assertEqual((True, None), app.restore_backup(path))
        self.assertEqual((dict.fromkeys(counts, 0), None), app.preview_restore(path))
        document, error = app.read_import_document({"_email_codes": {"__prefix__": "mail", "team": "New address"}})
        self.assertIsNone(error)
        self.assertEqual({"new": 0, "removed": 0, "overwritten": 1}, app.import_change_counts(document)["merge"])
        self.assertEqual((True, None), app.apply_import(document, "merge"))
        self.assertEqual("New address", app.snippets["mailteam"])
        self.assertEqual(1, len(manager(app).groups_list()["groups"]))

    def test_backup_or_write_failure_leaves_legacy_library_usable(self):
        original = {"_cpf_numbers": {"example": "Test ID"}}
        for target in ("create_backup", "write_json_atomic"):
            with self.subTest(target=target), mock.patch.object(tx, target, side_effect=OSError("test failure")):
                app = make_real_app(self, original)
                self.assertEqual(original, json.loads(Path(app.snippets_file).read_bytes()))
                self.assertTrue(manager(app).app_info()["legacyMappings"])
                self.assertEqual(("Test ID", 10), app.check_dynamic_pattern("cpfexample"))
                self.assertIsNotNone(app.last_save_error)

    def test_conflicting_and_read_only_types_keep_their_legacy_representation(self):
        original = {
            "cpfexample": "Direct value",
            "_cpf_numbers": {"example": "Hidden value", "alternate": "Preserved with its type"},
            "_agency_codes": {"__prefix__": "", "shortcut": "Bare trigger"},
        }
        snippets, meta = split_library_document(original)
        grouped, metadata = group_legacy_mappings(snippets, meta)
        self.assertEqual(original["_cpf_numbers"], grouped["_cpf_numbers"])
        self.assertEqual("Bare trigger", grouped["shortcut"])
        self.assertIn("_agency_codes", snippets)
        self.assertEqual("AGENCY", next(iter(metadata["groups"].values()))["label"])

        document = {**original, "__sniptype__": {"kind": METADATA_KIND, "schema_version": 99}}
        pair = split_library_document(document)
        self.assertTrue(pair[1].read_only)
        self.assertIs(pair[0], group_legacy_mappings(*pair)[0])

    def test_shorter_legacy_suffix_keeps_its_precedence(self):
        original = {
            "_short_codes": {"__prefix__": "l", "city": "Existing winner"},
            "_long_codes": {"__prefix__": "ma", "lcity": "Previously shadowed"},
        }
        grouped, _meta = group_legacy_mappings(*split_library_document(original))
        self.assertEqual("Existing winner", grouped["lcity"])
        self.assertEqual(original["_long_codes"], grouped["_long_codes"])
        self.assertNotIn("malcity", grouped)
