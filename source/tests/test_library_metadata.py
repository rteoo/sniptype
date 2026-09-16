import copy
import unittest
from unittest import mock

from library_metadata import (
    LibraryMetadata,
    MetadataReadOnlyError,
    METADATA_KEY,
    SCHEMA_VERSION,
    assign_static_item,
    build_library_document,
    create_group,
    delete_group,
    duplicate_static_item_metadata,
    merge_metadata,
    normalize_metadata,
    remove_form_metadata,
    set_form_metadata,
    split_library_document,
    toggle_favorite,
    unassign_static_item,
    update_group,
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

    def test_create_group_accepts_injected_id_and_uses_schema_defaults(self):
        metadata = create_group(LibraryMetadata({}, present=False), group_id="work", label="Work")

        self.assertEqual("Work", metadata["groups"]["work"]["label"])
        self.assertEqual("", metadata["groups"]["work"]["notes"])
        self.assertEqual("", metadata["groups"]["work"]["prefix"])
        self.assertTrue(metadata["groups"]["work"]["enabled"])
        self.assertEqual("inherit", metadata["groups"]["work"]["terminator"])
        self.assertEqual({"mode": "all", "executables": []}, metadata["groups"]["work"]["applications"])

    def test_create_group_generates_uuid_and_rejects_duplicate_id(self):
        with mock.patch("library_metadata.uuid.uuid4", return_value="generated"):
            metadata = create_group({}, label="First")
        self.assertIn("generated", metadata["groups"])
        with self.assertRaises(ValueError):
            create_group(metadata, group_id="generated")

    def test_update_group_is_copy_on_write_and_preserves_unknown_fields(self):
        original = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {"g": {"label": "Old", "extension": {"x": 1}}},
            "items": {"static": {}, "mappings": {}},
            "top_extension": "keep",
        }

        updated = update_group(original, "g", {"label": "New", "prefix": "w"})

        self.assertEqual("Old", original["groups"]["g"]["label"])
        self.assertEqual("New", updated["groups"]["g"]["label"])
        self.assertEqual({"x": 1}, updated["groups"]["g"]["extension"])
        self.assertEqual("keep", updated["top_extension"])

    def test_delete_group_moves_static_and_nested_mapping_assignments_to_ungrouped(self):
        original = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {"g": {"label": "Delete"}, "keep": {"label": "Keep"}},
            "items": {
                "static": {"x": {"group_id": "g"}, "y": {"group_id": "g", "favorite": True}},
                "mappings": {"_codes": {"a": {"group_id": "g", "form": {"fields": []}}}},
            },
        }

        updated = delete_group(original, "g")

        self.assertNotIn("g", updated["groups"])
        self.assertNotIn("group_id", updated["items"]["static"]["y"])
        self.assertNotIn("x", updated["items"]["static"])
        self.assertNotIn("group_id", updated["items"]["mappings"]["_codes"]["a"])
        self.assertIn("keep", updated["groups"])
        self.assertEqual("g", original["items"]["static"]["x"]["group_id"])

    def test_assign_and_unassign_static_item_preserve_mapping_metadata(self):
        metadata = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {"g": {"label": "Work"}},
            "items": {"static": {}, "mappings": {"_codes": {"a": {"favorite": True}}}},
        }

        assigned = assign_static_item(metadata, "x", "g")
        unassigned = unassign_static_item(assigned, "x")

        self.assertEqual({"group_id": "g"}, assigned["items"]["static"]["x"])
        self.assertNotIn("x", unassigned["items"]["static"])
        self.assertEqual({"favorite": True}, unassigned["items"]["mappings"]["_codes"]["a"])

    def test_form_metadata_and_favorite_are_copy_on_write(self):
        metadata = {"groups": {}, "items": {"static": {}, "mappings": {}}}
        form = {"fields": [{"name": "customer", "type": "text"}], "extension": "keep"}

        with_form = set_form_metadata(metadata, "x", form)
        with_favorite = toggle_favorite(with_form, "x")
        removed_form = remove_form_metadata(with_favorite, "x")

        self.assertEqual({}, metadata["items"]["static"])
        self.assertEqual(form, with_form["items"]["static"]["x"]["form"])
        self.assertTrue(with_favorite["items"]["static"]["x"]["favorite"])
        self.assertNotIn("form", removed_form["items"]["static"]["x"])
        self.assertTrue(removed_form["items"]["static"]["x"]["favorite"])

    def test_duplicate_copies_group_and_form_but_resets_favorite(self):
        metadata = {
            "kind": "sniptype_metadata", "schema_version": 1,
            "groups": {"g": {"label": "Work"}},
            "items": {
                "static": {"source": {"group_id": "g", "favorite": True, "form": {"fields": []}}},
                "mappings": {},
            },
        }

        duplicate = duplicate_static_item_metadata(metadata, "source", "copy")

        self.assertEqual("g", duplicate["items"]["static"]["copy"]["group_id"])
        self.assertEqual({"fields": []}, duplicate["items"]["static"]["copy"]["form"])
        self.assertFalse(duplicate["items"]["static"]["copy"]["favorite"])
        self.assertTrue(metadata["items"]["static"]["source"]["favorite"])
        with self.assertRaises(ValueError):
            duplicate_static_item_metadata(duplicate, "source", "copy")

    def test_duplicate_legacy_item_without_metadata_remains_implicit(self):
        duplicate = duplicate_static_item_metadata({}, "source", "copy")

        self.assertNotIn("copy", duplicate["items"]["static"])

    def test_all_mutations_reject_read_only_metadata(self):
        _, metadata = split_library_document({METADATA_KEY: {"schema_version": 99, "future": True}})
        operations = (
            lambda: create_group(metadata, group_id="g"),
            lambda: update_group(metadata, "g", {"label": "x"}),
            lambda: delete_group(metadata, "g"),
            lambda: assign_static_item(metadata, "x", "g"),
            lambda: unassign_static_item(metadata, "x"),
            lambda: set_form_metadata(metadata, "x", {"fields": []}),
            lambda: remove_form_metadata(metadata, "x"),
            lambda: toggle_favorite(metadata, "x"),
            lambda: duplicate_static_item_metadata(metadata, "x", "y"),
        )

        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(MetadataReadOnlyError):
                    operation()


if __name__ == "__main__":
    unittest.main()
