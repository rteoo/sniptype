import copy
import unittest

from library_metadata import split_library_document
from manager_actions import (
    MetadataReadOnlyError,
    TriggerCollisionError,
    assign_item,
    create_group,
    delete_group,
    duplicate_static,
    remove_form,
    set_form,
    toggle_favorite,
    toggle_mapping_favorite,
    unassign_item,
    update_group,
)


def metadata_with_group():
    return {
        "kind": "sniptype_metadata",
        "schema_version": 1,
        "groups": {"work": {"label": "Work", "prefix": "w", "enabled": True}},
        "items": {"static": {}, "mappings": {"_codes": {"item": {"favorite": True}}}},
        "extension": {"keep": "yes"},
    }


class ManagerActionTests(unittest.TestCase):
    def test_duplicate_static_copies_plain_or_rich_content_and_metadata_without_mutation(self):
        rich = {"__kind__": "rich_text", "text": "Olá 🌎", "spans": [{"start": 0, "end": 4}]}
        snippets = {"source": rich}
        metadata = {
            "groups": {"work": {"label": "Work"}},
            "items": {"static": {"source": {"group_id": "work", "favorite": True, "form": {"fields": []}}}, "mappings": {}},
            "extension": {"keep": True},
        }
        snippets_before, metadata_before = copy.deepcopy(snippets), copy.deepcopy(metadata)

        result = duplicate_static(snippets, metadata, "source", "copy")

        self.assertEqual(rich, result.snippets["copy"])
        self.assertEqual("work", result.metadata["items"]["static"]["copy"]["group_id"])
        self.assertEqual({"fields": []}, result.metadata["items"]["static"]["copy"]["form"])
        self.assertFalse(result.metadata["items"]["static"]["copy"]["favorite"])
        self.assertEqual(snippets_before, snippets)
        self.assertEqual(metadata_before, metadata)

    def test_duplicate_requires_new_stored_key_and_existing_source(self):
        with self.assertRaises(ValueError):
            duplicate_static({"x": "x"}, {"items": {"static": {}, "mappings": {}}}, "x", "x")
        with self.assertRaises(KeyError):
            duplicate_static({}, {"items": {"static": {}, "mappings": {}}}, "missing", "new")

    def test_duplicate_legacy_item_gets_only_fresh_nonfavorite_metadata(self):
        result = duplicate_static({"x": "legacy"}, {}, "x", "copy")

        self.assertEqual("legacy", result.snippets["copy"])
        self.assertEqual({"favorite": False}, result.metadata["items"]["static"]["copy"])

    def test_set_form_rejects_invalid_field_definition_without_mutating_inputs(self):
        snippets = {"x": "%%field%%"}
        metadata = {}

        with self.assertRaises(ValueError):
            set_form(snippets, metadata, "x", {"fields": [{"name": "bad", "type": "unknown"}]})

        self.assertEqual({"x": "%%field%%"}, snippets)
        self.assertEqual({}, metadata)

    def test_set_form_definition_must_match_template_fields(self):
        snippets = {"x": "Hello %%name%%"}

        with self.assertRaises(ValueError):
            set_form(snippets, {}, "x", {"fields": [{"name": "unused"}]})

    def test_create_group_is_copy_on_write_and_accepts_injected_id(self):
        snippets = {"x": "value"}
        metadata = {"items": {"static": {}, "mappings": {}}, "unknown": ["preserve"]}

        result = create_group(snippets, metadata, group_id="group-1", label="Grupo")

        self.assertEqual({}, metadata.get("groups", {}))
        self.assertEqual("Grupo", result.metadata["groups"]["group-1"]["label"])
        self.assertEqual(["preserve"], result.metadata["unknown"])
        self.assertEqual(snippets, result.snippets)

    def test_update_group_blocks_exact_static_collision_and_rolls_back_by_construction(self):
        snippets = {"x": "one", "wx": "two"}
        metadata = {
            "groups": {"work": {"label": "Work", "prefix": ""}},
            "items": {"static": {"x": {"group_id": "work"}}, "mappings": {}},
        }

        with self.assertRaises(TriggerCollisionError) as raised:
            update_group(snippets, metadata, "work", {"prefix": "w"})

        self.assertEqual("wx", raised.exception.trigger)
        self.assertEqual(snippets, {"x": "one", "wx": "two"})
        self.assertEqual("", metadata["groups"]["work"]["prefix"])

    def test_dynamic_direct_and_mapping_collisions_are_blocked(self):
        snippets = {"x": "one", "dynamicx": lambda: "now", "_codes": {"__prefix__": "p", "itemx": "v"}}
        metadata = {
            "groups": {"work": {"label": "Work", "prefix": ""}},
            "items": {"static": {"x": {"group_id": "work"}}, "mappings": {}},
        }
        with self.assertRaises(TriggerCollisionError):
            update_group(snippets, metadata, "work", {"prefix": "dynamic"})
        with self.assertRaises(TriggerCollisionError):
            update_group(snippets, metadata, "work", {"prefix": "pitem"})

    def test_delete_assign_unassign_preserve_nested_mapping_and_move_to_ungrouped(self):
        snippets = {"x": "value"}
        metadata = metadata_with_group()
        assigned = assign_item(snippets, metadata, "x", "work")
        unassigned = unassign_item(assigned.snippets, assigned.metadata, "x")
        deleted = delete_group(assigned.snippets, assigned.metadata, "work")

        self.assertNotIn("group_id", unassigned.metadata["items"].get("static", {}).get("x", {}))
        self.assertEqual({"favorite": True}, unassigned.metadata["items"]["mappings"]["_codes"]["item"])
        self.assertNotIn("work", deleted.metadata["groups"])
        self.assertNotIn("group_id", deleted.metadata["items"].get("static", {}).get("x", {}))
        self.assertEqual({"favorite": True}, deleted.metadata["items"]["mappings"]["_codes"]["item"])

    def test_form_and_favorite_actions_return_content_unchanged(self):
        snippets = {"x": "%%n%%"}
        metadata = {"groups": {}, "items": {"static": {}, "mappings": {}}}

        with_form = set_form(snippets, metadata, "x", {"fields": [{"name": "n", "type": "text"}]})
        favorite = toggle_favorite(with_form.snippets, with_form.metadata, "x")
        removed = remove_form(favorite.snippets, favorite.metadata, "x")

        self.assertEqual(snippets, removed.snippets)
        self.assertTrue(favorite.metadata["items"]["static"]["x"]["favorite"])
        self.assertNotIn("form", removed.metadata["items"]["static"]["x"])

    def test_mapping_favorite_is_nested_and_copy_on_write(self):
        snippets = {"_codes": {"__prefix__": "c", "alpha": "A"}}
        metadata = {"items": {"static": {}, "mappings": {}}}

        result = toggle_mapping_favorite(
            snippets,
            metadata,
            "_codes",
            "alpha",
            True,
        )

        self.assertTrue(
            result.metadata["items"]["mappings"]["_codes"]["alpha"]["favorite"]
        )
        self.assertEqual({"items": {"static": {}, "mappings": {}}}, metadata)
        with self.assertRaises(KeyError):
            toggle_mapping_favorite(snippets, metadata, "_codes", "missing")

    def test_reachability_hazards_are_returned_separately_from_success(self):
        snippets = {"a": "short", "ba": "long"}
        metadata = {
            "groups": {"group": {"label": "Group", "prefix": ""}},
            "items": {"static": {"ba": {"group_id": "group"}}, "mappings": {}},
        }

        result = update_group(snippets, metadata, "group", {"notes": "updated"})

        self.assertIn(("a", "ba"), result.reachability_warnings)

    def test_read_only_metadata_is_rejected_before_content_changes(self):
        snippets, metadata = split_library_document({"x": "value", "__sniptype__": {"schema_version": 99}})
        for operation in (
            lambda: duplicate_static(snippets, metadata, "x", "y"),
            lambda: create_group(snippets, metadata, group_id="g"),
            lambda: assign_item(snippets, metadata, "x", "g"),
            lambda: set_form(snippets, metadata, "x", {"fields": []}),
            lambda: toggle_favorite(snippets, metadata, "x"),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(MetadataReadOnlyError):
                    operation()
        self.assertEqual({"x": "value"}, snippets)


if __name__ == "__main__":
    unittest.main()
