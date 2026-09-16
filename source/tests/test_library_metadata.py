import copy
import unittest
from unittest import mock

from library_metadata import (
    METADATA_KEY,
    SCHEMA_VERSION,
    build_library_document,
    merge_metadata,
    normalize_metadata,
    split_library_document,
)


class LibraryMetadataTests(unittest.TestCase):
    def test_metadata_free_document_splits_and_round_trips_unchanged(self):
        document = {
            "xhello": "Olá, mundo",
            "_codes": {"__prefix__": "c", "item": "value"},
        }

        snippets, metadata = split_library_document(document)

        self.assertEqual(document, snippets)
        self.assertEqual({}, dict(metadata))
        self.assertEqual(document, build_library_document(snippets, metadata))
        self.assertNotIn(METADATA_KEY, snippets)

    def test_explicit_empty_metadata_block_is_preserved_as_read_only(self):
        document = {"xhello": "Hello", METADATA_KEY: {}}

        snippets, metadata = split_library_document(document)

        self.assertTrue(metadata.read_only)
        self.assertTrue(metadata.malformed)
        self.assertEqual({}, metadata.raw_block)
        self.assertEqual(document, build_library_document(snippets, metadata))

    def test_split_removes_reserved_entry_and_preserves_unicode_rich_text_and_mapping(self):
        rich_text = {"__kind__": "rich_text", "text": "Olá 🌎", "spans": []}
        metadata = {
            "kind": "sniptype_metadata",
            "schema_version": SCHEMA_VERSION,
            "groups": {"g1": {"label": "Trabalho", "notes": "ação"}},
            "items": {"static": {"xhello": {"group_id": "g1"}}, "mappings": {}},
            "future_field": {"keep": True},
        }
        document = {"xhello": rich_text, "_codes": {"name": "valor"}, METADATA_KEY: metadata}

        snippets, split_metadata = split_library_document(document)

        self.assertEqual({"xhello": rich_text, "_codes": {"name": "valor"}}, snippets)
        self.assertEqual(metadata, dict(split_metadata))
        self.assertEqual(document, build_library_document(snippets, split_metadata))
        self.assertEqual(rich_text, build_library_document(snippets, split_metadata)["xhello"])

    def test_normalize_adds_schema_defaults_and_drops_orphans(self):
        metadata = {
            "kind": "sniptype_metadata",
            "schema_version": 1,
            "groups": {"g1": {"label": "Work"}, "orphan": {"label": "Gone"}},
            "items": {
                "static": {
                    "xhello": {"group_id": "g1"},
                    "xmissing": {"group_id": "g1"},
                    "xorphan": {"group_id": "orphan"},
                },
                "mappings": {"_codes": {"item": {"group_id": "g1"}}},
            },
        }

        normalized = normalize_metadata(metadata, {"static": {"xhello"}, "mappings": set()})

        self.assertEqual("sniptype_metadata", normalized["kind"])
        self.assertEqual(1, normalized["schema_version"])
        self.assertEqual({"g1": {"label": "Work"}, "orphan": {"label": "Gone"}}, normalized["groups"])
        self.assertEqual({"xhello": {"group_id": "g1"}}, normalized["items"]["static"])
        self.assertEqual({"_codes": {}}, normalized["items"]["mappings"])

    def test_normalize_accepts_flat_available_items_and_does_not_mutate_input(self):
        metadata = {"items": {"static": {"x": {"favorite": True}}}}
        original = copy.deepcopy(metadata)

        normalized = normalize_metadata(metadata, {"x"})

        self.assertEqual(original, metadata)
        self.assertEqual(True, normalized["items"]["static"]["x"]["favorite"])
        self.assertEqual({}, normalized["groups"])

    def test_malformed_metadata_is_preserved_and_library_content_remains_loadable(self):
        raw = ["malformed", "metadata"]
        document = {"x": "value", METADATA_KEY: raw}

        snippets, metadata = split_library_document(document)

        self.assertEqual({"x": "value"}, snippets)
        self.assertTrue(metadata.read_only)
        self.assertTrue(metadata.malformed)
        self.assertEqual(raw, metadata.raw_block)
        self.assertEqual(document, build_library_document(snippets, metadata))
        self.assertEqual({"x": "changed", METADATA_KEY: raw}, build_library_document({"x": "changed"}, metadata))

    def test_future_schema_is_preserved_read_only(self):
        future = {"kind": "sniptype_metadata", "schema_version": 99, "new": {"x": 1}}
        snippets, metadata = split_library_document({"x": "value", METADATA_KEY: future})

        self.assertTrue(metadata.read_only)
        self.assertFalse(metadata.malformed)
        self.assertEqual(future, metadata.raw_block)
        self.assertEqual({"x": "value", METADATA_KEY: future}, build_library_document(snippets, metadata))

    def test_build_excludes_reserved_content_even_if_snippets_contains_it(self):
        metadata = {"kind": "sniptype_metadata", "schema_version": 1, "groups": {}, "items": {}}

        document = build_library_document({"x": "value", METADATA_KEY: "not-content"}, metadata)

        self.assertEqual(metadata, document[METADATA_KEY])

    def test_normalize_preserves_unknown_schema_one_fields(self):
        metadata = {
            "kind": "sniptype_metadata",
            "schema_version": 1,
            "groups": {},
            "items": {},
            "extension": {"unicode": "ação"},
        }

        normalized = normalize_metadata(metadata, {})

        self.assertEqual({"unicode": "ação"}, normalized["extension"])

    def test_normalize_filters_nested_mapping_item_orphans(self):
        metadata = {
            "kind": "sniptype_metadata",
            "schema_version": 1,
            "groups": {"g": {"label": "Codes"}},
            "items": {
                "static": {},
                "mappings": {
                    "_codes": {
                        "live": {"group_id": "g"},
                        "gone": {"group_id": "g"},
                    },
                    "_missing": {"gone": {"group_id": "g"}},
                },
            },
        }

        normalized = normalize_metadata(
            metadata,
            {"static": set(), "mappings": {"_codes": {"live"}}},
        )

        self.assertEqual({"_codes": {"live": {"group_id": "g"}}}, normalized["items"]["mappings"])

    def test_replace_merge_uses_imported_metadata_and_legacy_is_empty(self):
        existing = {"kind": "sniptype_metadata", "schema_version": 1, "groups": {"g": {}}, "items": {}}
        imported = {"kind": "sniptype_metadata", "schema_version": 1, "groups": {"i": {}}, "items": {}}

        replaced = merge_metadata(existing, imported, "replace")
        legacy = merge_metadata(existing, {}, "replace")

        self.assertEqual(imported, dict(replaced))
        self.assertEqual({}, dict(legacy))

    def test_merge_reuses_identical_group_and_imported_item_wins(self):
        group = {"label": "Work", "prefix": "w"}
        existing = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {"g": group},
            "items": {"static": {"x": {"favorite": False}}, "mappings": {}},
        }
        imported = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {"g": group},
            "items": {"static": {"x": {"favorite": True}}, "mappings": {}},
        }

        merged = merge_metadata(existing, imported, {"mode": "merge", "imported_static": {"x"}})

        self.assertEqual({"g": group}, merged["groups"])
        self.assertEqual({"favorite": True}, merged["items"]["static"]["x"])

    def test_merge_remaps_conflicting_group_id_and_item_assignment(self):
        existing = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {"same": {"label": "Local"}},
            "items": {"static": {"local": {"group_id": "same"}}, "mappings": {}},
        }
        imported = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {"same": {"label": "Imported"}},
            "items": {"static": {"incoming": {"group_id": "same"}}, "mappings": {}},
        }

        with mock.patch("library_metadata.uuid.uuid4", return_value=mock.Mock(__str__=lambda self: "new-id")):
            merged = merge_metadata(existing, imported, {"mode": "merge", "imported_static": {"incoming"}})

        self.assertEqual({"same": {"label": "Local"}, "new-id": {"label": "Imported"}}, merged["groups"])
        self.assertEqual("new-id", merged["items"]["static"]["incoming"]["group_id"])

    def test_merge_can_select_imported_winners_from_content_mapping(self):
        existing = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {},
            "items": {"static": {"x": {"favorite": False}, "keep": {"favorite": True}}, "mappings": {}},
        }
        imported = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {},
            "items": {"static": {"x": {"favorite": True}, "new": {"favorite": True}}, "mappings": {}},
        }

        merged = merge_metadata(existing, imported, {"mode": "merge", "imported_items": {"static": {"x", "new"}}})

        self.assertTrue(merged["items"]["static"]["x"]["favorite"])
        self.assertTrue(merged["items"]["static"]["new"]["favorite"])
        self.assertTrue(merged["items"]["static"]["keep"]["favorite"])

    def test_merge_preserves_read_only_existing_metadata(self):
        existing = {"kind": "sniptype_metadata", "schema_version": 99, "future": True}
        imported = {"kind": "sniptype_metadata", "schema_version": 1, "groups": {}, "items": {}}

        _, existing_state = split_library_document({METADATA_KEY: existing})
        merged = merge_metadata(existing_state, imported, "merge")

        self.assertTrue(merged.read_only)
        self.assertEqual(existing, merged.raw_block)

    def test_merge_rejects_read_only_imported_metadata(self):
        existing = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {}, "items": {},
        }
        imported = {"kind": "sniptype_metadata", "schema_version": 99, "future": True}

        with self.assertRaisesRegex(ValueError, "read-only|future"):
            merge_metadata(existing, imported, "merge")

    def test_merge_handles_nested_mapping_winners_and_group_remapping(self):
        existing = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {"g": {"label": "Local"}},
            "items": {"static": {}, "mappings": {}},
        }
        imported = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {"g": {"label": "Imported"}},
            "items": {
                "static": {},
                "mappings": {
                    "_codes": {
                        "live": {"group_id": "g", "favorite": True},
                        "skip": {"group_id": "g", "favorite": True},
                    },
                },
            },
        }

        with mock.patch("library_metadata.uuid.uuid4", return_value=mock.Mock(__str__=lambda self: "new-id")):
            merged = merge_metadata(
                existing,
                imported,
                {"mode": "merge", "imported_items": {"mappings": {"_codes": {"live"}}}},
            )

        self.assertEqual("new-id", merged["items"]["mappings"]["_codes"]["live"]["group_id"])
        self.assertNotIn("skip", merged["items"]["mappings"].get("_codes", {}))


if __name__ == "__main__":
    unittest.main()
