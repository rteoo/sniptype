import copy
import threading
import unittest

from library_metadata import mapping_item_metadata, split_library_document, static_item_metadata
from manager_actions import (
    MetadataReadOnlyError,
    TriggerCollisionError,
    assign_item,
    create_group,
    delete_group,
    duplicate_static,
    group_members,
    remove_form,
    rename_static,
    restore_group,
    restore_mapping_item,
    restore_static,
    set_form,
    set_mapping_form,
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

    def test_rename_preserves_group_form_and_favorite_metadata(self):
        snippets = {"old": "Hello %%name%%"}
        metadata = {
            "groups": {"work": {"label": "Work", "prefix": "w"}},
            "items": {"static": {"old": {
                "group_id": "work",
                "favorite": True,
                "form": {"fields": [{"name": "name"}]},
            }}, "mappings": {}},
        }

        result = rename_static(snippets, metadata, "old", "new")

        self.assertNotIn("old", result.snippets)
        self.assertEqual("Hello %%name%%", result.snippets["new"])
        self.assertEqual(
            metadata["items"]["static"]["old"],
            result.metadata["items"]["static"]["new"],
        )

    def test_set_form_rejects_invalid_field_definition_without_mutating_inputs(self):
        for old_test, template, form in (
            ("test_set_form_rejects_invalid_field_definition_without_mutating_inputs",
             "%%field%%", {"fields": [{"name": "bad", "type": "unknown"}]}),
            ("test_set_form_definition_must_match_template_fields",
             "Hello %%name%%", {"fields": [{"name": "unused"}]}),
        ):
            with self.subTest(old_test):
                snippets = {"x": template}
                metadata = {}

                with self.assertRaises(ValueError):
                    set_form(snippets, metadata, "x", form)

                self.assertEqual({"x": template}, snippets)
                self.assertEqual({}, metadata)

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

    def test_mapping_form_is_validated_and_stored_under_mapping_item(self):
        snippets = {"_codes": {"__prefix__": "c", "hello": "Hi %%name%%"}}

        result = set_mapping_form(
            snippets,
            {},
            "_codes",
            "hello",
            {"fields": [{"name": "name", "type": "multiline"}]},
        )

        self.assertEqual(
            "multiline",
            result.metadata["items"]["mappings"]["_codes"]["hello"]["form"]["fields"][0]["type"],
        )

    def test_reachability_hazards_are_returned_separately_from_success(self):
        snippets = {"a": "short", "ba": "long"}
        metadata = {
            "groups": {"group": {"label": "Group", "prefix": ""}},
            "items": {"static": {"ba": {"group_id": "group"}}, "mappings": {}},
        }

        result = update_group(snippets, metadata, "group", {"notes": "updated"})

        self.assertIn(("a", "ba"), result.reachability_warnings)

    def test_runtime_providers_are_kept_by_reference_while_data_is_copied(self):
        # Regression: providers are bound methods of objects holding locks, so
        # deep-copying them raised "cannot pickle '_thread.RLock'".
        class Provider:
            def __init__(self):
                self.lock = threading.RLock()

            def today(self):
                return "hoje"

        provider = Provider().today
        mapping = {"__prefix__": "c", "alpha": "A"}
        snippets = {"x": "value", "xhoje": provider, "_codes": mapping}
        metadata = {"groups": {}, "items": {"static": {}, "mappings": {}}}

        for name, operation in (
            ("toggle_favorite", lambda: toggle_favorite(snippets, metadata, "x", True)),
            ("create_group", lambda: create_group(snippets, metadata, group_id="g", label="G")),
            ("duplicate_static", lambda: duplicate_static(snippets, metadata, "x", "y")),
            ("rename_static", lambda: rename_static(snippets, metadata, "x", "y")),
            ("set_form", lambda: set_form(snippets, metadata, "x", {"fields": []})),
            ("toggle_mapping_favorite",
             lambda: toggle_mapping_favorite(snippets, metadata, "_codes", "alpha", True)),
        ):
            with self.subTest(name):
                result = operation()
                self.assertIs(provider, result.snippets["xhoje"])
                self.assertIsNot(mapping, result.snippets["_codes"])
                self.assertEqual(mapping, result.snippets["_codes"])

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



class UndoTransactionTests(unittest.TestCase):
    """Desfazer puts a deleted item back through the ordinary save path."""

    def test_restore_static_brings_back_the_value_and_its_metadata(self):
        metadata = metadata_with_group()
        metadata["items"]["static"]["xola"] = {"group_id": "work", "favorite": True, "form": {"fields": []}}
        saved = static_item_metadata(metadata, "xola")
        metadata["items"]["static"].pop("xola")
        snippets = {"other": "x", "_codes": {"item": "1"}}
        before = copy.deepcopy((snippets, metadata))

        result = restore_static(snippets, metadata, "xola", "Olá", saved)

        self.assertEqual("Olá", result.snippets["xola"])
        self.assertEqual(
            {"group_id": "work", "favorite": True, "form": {"fields": []}},
            result.metadata["items"]["static"]["xola"],
        )
        self.assertEqual(before, (snippets, metadata))

    def test_restore_static_is_refused_once_the_name_is_taken_again(self):
        with self.assertRaises(ValueError):
            restore_static({"xola": "new"}, {}, "xola", "old")
        with self.assertRaises(ValueError):
            restore_static({"xola": lambda: "dynamic"}, {}, "xola", "old")
        with self.assertRaises(ValueError):
            restore_static({}, {}, "_codes", "reserved")

    def test_restore_static_is_refused_when_its_effective_trigger_now_collides(self):
        metadata = metadata_with_group()
        saved = {"group_id": "work"}
        # Since the delete, "wxola" became a plain snippet: the restored
        # "xola" in the "w" group would expand on the same trigger.
        with self.assertRaises(TriggerCollisionError):
            restore_static({"wxola": "taken"}, metadata, "xola", "old", saved)

    def test_an_item_whose_group_is_gone_comes_back_ungrouped(self):
        result = restore_static({}, {}, "xola", "old", {"group_id": "deleted", "favorite": True})
        self.assertEqual({"favorite": True}, result.metadata["items"]["static"]["xola"])

    def test_restore_mapping_item_needs_its_type_and_a_free_identifier(self):
        metadata = metadata_with_group()
        saved = mapping_item_metadata(metadata, "_codes", "item")
        snippets = {"_codes": {"__prefix__": "c"}}

        result = restore_mapping_item(snippets, metadata, "_codes", "item", "1", saved)

        self.assertEqual("1", result.snippets["_codes"]["item"])
        self.assertEqual({"favorite": True}, result.metadata["items"]["mappings"]["_codes"]["item"])
        self.assertNotIn("item", snippets["_codes"])
        with self.assertRaises(KeyError):
            restore_mapping_item({}, metadata, "_codes", "item", "1", saved)
        with self.assertRaises(ValueError):
            restore_mapping_item({"_codes": {"item": "2"}}, metadata, "_codes", "item", "1")

    def test_restore_group_recreates_it_and_regroups_the_members_left_alone(self):
        metadata = metadata_with_group()
        metadata["items"]["static"].update({
            "a": {"group_id": "work"}, "b": {"group_id": "work"}, "c": {"group_id": "work"},
        })
        metadata["items"]["mappings"]["_codes"]["item"]["group_id"] = "work"
        snippets = {"a": "1", "b": "2", "c": "3", "_codes": {"item": "x"}}
        definition = copy.deepcopy(metadata["groups"]["work"])
        static_members, mapping_members = group_members(metadata, "work")
        self.assertEqual(("a", "b", "c"), static_members)
        self.assertEqual((("_codes", "item"),), mapping_members)

        deleted = delete_group(snippets, metadata, "work")
        # Before Desfazer, "b" is deleted and "c" is put in another group.
        content = dict(deleted.snippets)
        content.pop("b")
        regrouped = create_group(content, deleted.metadata, group_id="home", label="Home")
        regrouped = assign_item(regrouped.snippets, regrouped.metadata, "c", "home")

        result = restore_group(
            regrouped.snippets, regrouped.metadata, "work", definition,
            static_items=static_members, mapping_items=mapping_members,
        )

        self.assertEqual(definition["label"], result.metadata["groups"]["work"]["label"])
        statics = result.metadata["items"]["static"]
        self.assertEqual("work", statics["a"]["group_id"])
        self.assertNotIn("b", statics)
        self.assertEqual("home", statics["c"]["group_id"])
        self.assertEqual("work", result.metadata["items"]["mappings"]["_codes"]["item"]["group_id"])

    def test_restore_group_is_refused_when_its_prefix_now_collides(self):
        metadata = metadata_with_group()
        metadata["items"]["static"]["hi"] = {"group_id": "work"}
        definition = copy.deepcopy(metadata["groups"]["work"])
        members = group_members(metadata, "work")
        deleted = delete_group({"hi": "x"}, metadata, "work")
        content = dict(deleted.snippets, whi="taken since")
        with self.assertRaises(TriggerCollisionError):
            restore_group(content, deleted.metadata, "work", definition,
                          static_items=members[0], mapping_items=members[1])


if __name__ == "__main__":
    unittest.main()
