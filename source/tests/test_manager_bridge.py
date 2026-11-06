"""The JSON bridge the Tauri manager talks to, against a real app on a temp home."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_module import sniptype as tx
import ui_theme
from manager_bridge import ManagerBridge, ManagerProcess, find_manager_executable, revision
from rich_text_support import build_rich_text_payload
from test_manager_runtime import make_real_app
from workflow_support import SnippetRef


def on_disk(app):
    with open(app.snippets_file, encoding="utf-8") as handle:
        return json.load(handle)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.app = make_real_app(self, {
            "hello": "Hello there",
            "sig": "Best,\nTeo",
            "fancy": build_rich_text_payload("Bold text", [{"tag": "bold", "start": 0, "end": 4}]),
            "_codes": {"__prefix__": "c", "city": "Goiânia"},
        })
        self.bridge = ManagerBridge(self.app, version="9.9.9", channel="beta")

    def call(self, method, **params):
        return self.bridge.handle({"id": 7, "method": method, "params": params})

    def result(self, method, **params):
        response = self.call(method, **params)
        self.assertNotIn("error", response, response)
        self.assertEqual(7, response["id"])
        return response["result"]

    def error(self, method, **params):
        response = self.call(method, **params)
        self.assertIn("error", response, response)
        return response["error"]

    def test_list_holds_static_snippets_only_with_one_line_previews(self):
        items = {item["trigger"]: item for item in self.result("library.list")["items"]}
        self.assertTrue({"hello", "sig", "fancy"} <= set(items))
        self.assertNotIn("_codes", items)
        self.assertNotIn("ccity", items)
        self.assertEqual("Best, Teo", items["sig"]["preview"])
        self.assertTrue(items["fancy"]["rich"])
        self.assertFalse(items["hello"]["rich"])

    def test_switcher_ranks_every_kind_like_the_classic_one(self):
        rows = self.result("switcher.search", query="")
        self.assertEqual({"static", "mapping", "dynamic"}, {row["kind"] for row in rows})
        self.assertLessEqual(len(rows), ManagerBridge.SWITCHER_LIMIT)
        hello = self.result("switcher.search", query="hello")[0]
        self.assertEqual({"kind": "static", "key": "hello", "container": None, "label": "Texto",
                          "trigger": "hello", "preview": "Hello there"}, hello)
        city = next(row for row in self.result("switcher.search", query="Goiânia") if row["kind"] == "mapping")
        self.assertEqual(("city", "_codes", "Mapeamento"), (city["key"], city["container"], city["label"]))
        content = [row["key"] for row in self.result("switcher.search", query="Best,")]
        self.assertEqual(["sig"], content)

    def test_info_reports_version_language_and_settings(self):
        info = self.result("app.info")
        self.assertEqual(("9.9.9", "beta", "pt-BR"), (info["version"], info["channel"], info["language"]))
        self.assertIn(info["appearance"], ("system", "light", "dark"))
        self.assertEqual("compact", info["density"])
        self.assertFalse(info["terminatorMode"])
        self.assertIsInstance(info["issues"], list)

    def test_save_new_snippet_reaches_disk_and_expands(self):
        self.assertEqual({"status": "saved", "trigger": "addr", "revision": revision("Rua A, 1")},
                         self.result("snippet.save", trigger=" addr ", text="Rua A, 1"))
        self.assertEqual("Rua A, 1", on_disk(self.app)["addr"])
        self.assertEqual("Rua A, 1", self.app.snippets["addr"])
        self.assertTrue(os.listdir(self.app.backups_dir), "a save backs up the prior file")

    def test_edit_keeps_trigger_and_overwrites_text(self):
        self.result("snippet.save", trigger="hello", text="Hi", original="hello")
        self.assertEqual("Hi", on_disk(self.app)["hello"])

    def test_writing_over_another_snippet_asks_first(self):
        answer = self.result("snippet.save", trigger="hello", text="Other", original="sig")
        self.assertEqual(("confirm", "replace"), (answer["status"], answer["check"]))
        self.assertEqual("Hello there", on_disk(self.app)["hello"])
        self.result("snippet.save", trigger="hello", text="Other", original="sig", confirmed=["replace"])
        self.assertEqual("Other", on_disk(self.app)["hello"])

    def test_trigger_warnings_need_confirmation(self):
        answer = self.result("snippet.save", trigger="ello", text="Suffix of hello")
        self.assertEqual(("confirm", "warnings"), (answer["status"], answer["check"]))
        self.assertNotIn("ello", on_disk(self.app))
        self.result("snippet.save", trigger="ello", text="Suffix of hello", confirmed=["warnings"])
        self.assertEqual("Suffix of hello", on_disk(self.app)["ello"])

    def test_invalid_drafts_are_refused_with_a_reason(self):
        self.assertEqual("invalid", self.error("snippet.save", trigger="x", text="  ")["code"])
        self.assertEqual("invalid", self.error("snippet.save", trigger="_x", text="v")["code"])

    def test_plain_text_never_overwrites_a_rich_snippet(self):
        before = on_disk(self.app)["fancy"]
        self.assertEqual("rich", self.error("snippet.save", trigger="fancy", text="flat", original="fancy")["code"])
        self.assertEqual(before, on_disk(self.app)["fancy"])

    def test_spans_save_formatted_text_and_none_left_saves_it_plain(self):
        spans = [{"tag": "italic", "start": 0, "end": 4}, {"tag": "code", "start": 5, "end": 9}]
        self.result("snippet.save", trigger="fancy", text="Bold text", original="fancy", spans=spans)
        stored = on_disk(self.app)["fancy"]
        self.assertEqual(("rich_text", spans), (stored["__kind__"], stored["spans"]))
        self.assertIn("<em>Bold</em>", stored["html"])
        self.assertIn(r"\f1", stored["rtf"])
        self.result("snippet.save", trigger="plain", text="Now bold", spans=[{"tag": "bold", "start": 4, "end": 8}])
        self.assertTrue(on_disk(self.app)["plain"]["html"].endswith("<strong>bold</strong></div>"))
        self.result("snippet.save", trigger="fancy", text="Bold text", original="fancy", spans=[])
        self.assertEqual("Bold text", on_disk(self.app)["fancy"])
        self.assertEqual("bad_params", self.error("snippet.save", trigger="x1", text="v", spans="bold")["code"])

    def test_failed_write_reports_and_rolls_memory_back(self):
        with mock.patch.object(self.app, "save_snippets", return_value=False):
            self.assertEqual("save_failed", self.error("snippet.save", trigger="new1", text="v")["code"])
            self.assertEqual("save_failed",
                             self.error("snippet.save", trigger="hello", text="v", original="hello")["code"])
        self.assertNotIn("new1", self.app.snippets)
        self.assertEqual("Hello there", self.app.snippets["hello"])

    def test_delete_then_undo_restores_the_snippet_on_disk(self):
        token = self.result("snippet.delete", trigger="sig")["undoToken"]
        self.assertNotIn("sig", on_disk(self.app))
        self.assertNotIn("sig", self.app.snippets)
        self.assertEqual({"trigger": "sig"}, self.result("snippet.undoDelete", token=token))
        self.assertEqual("Best,\nTeo", on_disk(self.app)["sig"])
        self.assertEqual("undo_expired", self.error("snippet.undoDelete", token=token)["code"])

    def test_delete_missing_is_an_error(self):
        self.assertEqual("missing", self.error("snippet.delete", trigger="nope")["code"])

    def test_get_returns_text_and_rich_flag(self):
        self.assertEqual({"trigger": "fancy", "text": "Bold text", "rich": True,
                          "spans": [{"tag": "bold", "start": 0, "end": 4}], "effectiveTrigger": "fancy",
                          "favorite": False, "groupId": None, "revision": revision(on_disk(self.app)["fancy"])},
                         self.result("snippet.get", trigger="fancy"))
        self.assertEqual("missing", self.error("snippet.get", trigger="nope")["code"])

    def test_settings_persist_and_apply(self):
        info = self.result("settings.set", key="terminatorMode", value=True)
        self.assertTrue(info["terminatorMode"])
        self.assertTrue(self.app.terminator_mode)
        with open(self.app.settings_file, encoding="utf-8") as handle:
            self.assertTrue(json.load(handle)["terminator_mode"])
        # Density is process-wide in ui_theme; later GUI tests expect the default.
        self.addCleanup(ui_theme.set_density, ui_theme.DEFAULT_DENSITY)
        self.assertEqual("comfortable", self.result("settings.set", key="density", value="comfortable")["density"])
        self.assertEqual("bad_params", self.error("settings.set", key="mirror_dir", value="C:/x")["code"])
        self.assertEqual("bad_params", self.error("settings.set", key="density", value="huge")["code"])

    def test_the_window_has_no_way_back_to_the_classic_manager(self):
        self.assertEqual("unknown_method", self.error("app.openClassicManager")["code"])

    def test_unknown_methods_and_bad_params_are_errors_not_crashes(self):
        self.assertEqual("unknown_method", self.error("library.drop")["code"])
        self.assertEqual("bad_params", self.error("snippet.get")["code"])
        self.assertEqual("bad_params", self.bridge.handle({"id": 1, "method": "app.info", "params": []})
                         ["error"]["code"])


class MappingBridgeTests(unittest.TestCase):
    def setUp(self):
        self.app = make_real_app(self, {
            "hello": "Hello there",
            "_cpf_numbers": {
                "fulano": "123.456.789-00",
                "styled": build_rich_text_payload("Bold id", [{"tag": "bold", "start": 0, "end": 4}]),
            },
            "_email_codes": {"__prefix__": "mail", "work": "work@example.com"},
        })
        self.bridge = ManagerBridge(self.app, version="9.9.9", channel="beta")

    call, result, error = BridgeTests.call, BridgeTests.result, BridgeTests.error

    def test_formatted_items_save_with_spans_and_keep_them_without(self):
        spans = [{"tag": "underline", "start": 0, "end": 4}]
        self.result("mapping.save", type="_cpf_numbers", name="styled", text="Bold id", original="styled", spans=spans)
        self.assertEqual(spans, on_disk(self.app)["_cpf_numbers"]["styled"]["spans"])
        self.assertEqual(spans, self.result("mapping.get", type="_cpf_numbers", name="styled")["spans"])
        self.assertEqual("rich", self.error("mapping.save", type="_cpf_numbers", name="styled", text="flat",
                                            original="styled")["code"])

    def test_types_list_builtins_first_with_counts_and_prefixes(self):
        types = self.result("mapping.types")
        self.assertEqual(["_cnpj_numbers", "_cpf_numbers", "_email_codes"], [t["key"] for t in types])
        by_key = {t["key"]: t for t in types}
        self.assertEqual((0, True), (by_key["_cnpj_numbers"]["count"], by_key["_cnpj_numbers"]["builtin"]))
        self.assertEqual(2, by_key["_cpf_numbers"]["count"])
        self.assertEqual(("EMAIL", "mail", 1, False),
                         tuple(by_key["_email_codes"][k] for k in ("label", "prefix", "count", "builtin")))

    def test_list_holds_one_types_items_with_effective_triggers(self):
        items = {item["name"]: item for item in self.result("mapping.list", type="_cpf_numbers")}
        self.assertEqual({"fulano", "styled"}, set(items))
        self.assertEqual(("cpffulano", "123.456.789-00", False),
                         (items["fulano"]["effectiveTrigger"], items["fulano"]["preview"], items["fulano"]["rich"]))
        self.assertTrue(items["styled"]["rich"])
        self.assertEqual([], self.result("mapping.list", type="_cnpj_numbers"))
        self.assertEqual("missing_type", self.error("mapping.list", type="_gone_codes")["code"])

    def test_get_returns_text_rich_flag_and_effective_trigger(self):
        self.assertEqual({"type": "_email_codes", "name": "work", "text": "work@example.com", "rich": False,
                          "spans": [], "effectiveTrigger": "mailwork", "favorite": False,
                          "revision": revision("work@example.com")},
                         self.result("mapping.get", type="_email_codes", name="work"))
        self.assertEqual("missing", self.error("mapping.get", type="_email_codes", name="__prefix__")["code"])

    def test_save_new_item_reaches_disk_and_expands(self):
        self.assertEqual({"status": "saved", "type": "_cpf_numbers", "name": "beltrano",
                          "revision": revision("987.654.321-00")},
                         self.result("mapping.save", type="_cpf_numbers", name=" beltrano ", text="987.654.321-00"))
        self.assertEqual("987.654.321-00", on_disk(self.app)["_cpf_numbers"]["beltrano"])
        self.assertEqual(("987.654.321-00", len("cpfbeltrano")),
                         tx.resolve_dynamic_pattern(self.app.snippets, "cpfbeltrano"))

    def test_saving_into_a_builtin_type_without_items_creates_it(self):
        self.result("mapping.save", type="_cnpj_numbers", name="acme", text="12.345.678/0001-90")
        self.assertEqual({"acme": "12.345.678/0001-90"}, on_disk(self.app)["_cnpj_numbers"])

    def test_writing_over_another_item_asks_first(self):
        answer = self.result("mapping.save", type="_cpf_numbers", name="fulano", text="000", original=None)
        self.assertEqual(("confirm", "replace"), (answer["status"], answer["check"]))
        self.assertEqual("123.456.789-00", on_disk(self.app)["_cpf_numbers"]["fulano"])
        self.result("mapping.save", type="_cpf_numbers", name="fulano", text="000", confirmed=["replace"])
        self.assertEqual("000", on_disk(self.app)["_cpf_numbers"]["fulano"])

    def test_invalid_and_rich_drafts_are_refused(self):
        for name, text in (("", "v"), ("__prefix__", "v"), ("x", "  ")):
            self.assertEqual("invalid", self.error("mapping.save", type="_cpf_numbers", name=name, text=text)["code"])
        before = on_disk(self.app)["_cpf_numbers"]["styled"]
        self.assertEqual("rich", self.error("mapping.save", type="_cpf_numbers", name="styled", text="flat",
                                            original="styled")["code"])
        self.assertEqual(before, on_disk(self.app)["_cpf_numbers"]["styled"])

    def test_failed_write_rolls_memory_back(self):
        with mock.patch.object(self.app, "save_snippets", return_value=False):
            self.assertEqual("save_failed",
                             self.error("mapping.save", type="_cpf_numbers", name="new1", text="v")["code"])
            self.assertEqual("save_failed",
                             self.error("mapping.save", type="_cnpj_numbers", name="acme", text="v")["code"])
            self.assertEqual("save_failed", self.error("mapping.delete", type="_email_codes", name="work")["code"])
        self.assertNotIn("new1", self.app.snippets["_cpf_numbers"])
        self.assertNotIn("_cnpj_numbers", self.app.snippets)
        self.assertEqual("work@example.com", self.app.snippets["_email_codes"]["work"])

    def test_delete_then_undo_restores_the_item_on_disk(self):
        token = self.result("mapping.delete", type="_email_codes", name="work")["undoToken"]
        self.assertNotIn("work", on_disk(self.app)["_email_codes"])
        self.assertEqual("undo_expired", self.error("snippet.undoDelete", token=token)["code"],
                         "a static undo cannot spend a mapping token")
        self.assertEqual({"type": "_email_codes", "name": "work"},
                         self.result("mapping.undoDelete", token=token))
        self.assertEqual("work@example.com", on_disk(self.app)["_email_codes"]["work"])
        self.assertEqual("undo_expired", self.error("mapping.undoDelete", token=token)["code"])
        self.assertEqual("missing", self.error("mapping.delete", type="_email_codes", name="nope")["code"])

    def test_create_type_validates_then_persists(self):
        self.assertEqual({"status": "invalid", "field": "prefix",
                          "message": "O prefixo 'mail' já está em uso por outro tipo de mapeamento."},
                         self.result("mapping.createType", name="contato", prefix="mail"))
        self.assertEqual("name", self.result("mapping.createType", name="email", prefix="em")["field"])
        self.assertEqual("name", self.result("mapping.createType", name="dois tipos", prefix="dt")["field"])
        self.assertEqual({"status": "created", "key": "_phone_codes"},
                         self.result("mapping.createType", name=" Phone ", prefix="TEL"))
        self.assertEqual({"__prefix__": "tel"}, on_disk(self.app)["_phone_codes"])
        self.assertIn("_phone_codes", [t["key"] for t in self.result("mapping.types")])

    def test_delete_type_removes_custom_types_only(self):
        self.assertEqual("builtin", self.error("mapping.deleteType", type="_cpf_numbers")["code"])
        with mock.patch.object(self.app, "save_snippets", return_value=False):
            self.assertEqual("save_failed", self.error("mapping.deleteType", type="_email_codes")["code"])
        self.assertIn("_email_codes", self.app.snippets)
        self.assertEqual({"type": "_email_codes"}, self.result("mapping.deleteType", type="_email_codes"))
        self.assertNotIn("_email_codes", on_disk(self.app))
        self.assertEqual("missing_type", self.error("mapping.deleteType", type="_email_codes")["code"])


class OrganizeBridgeTests(unittest.TestCase):
    """Favorites, groups, Duplicar, Renomear and the list filters."""

    def setUp(self):
        self.app = make_real_app(self, {
            "hello": "Hello there",
            "sig": "Best,\nTeo",
            "fancy": build_rich_text_payload("Bold text", [{"tag": "bold", "start": 0, "end": 4}]),
            "_cpf_numbers": {"fulano": "123.456.789-00"},
        })
        self.bridge = ManagerBridge(self.app, version="9.9.9", channel="beta")

    call, result, error = BridgeTests.call, BridgeTests.result, BridgeTests.error

    def metadata(self):
        return on_disk(self.app)["__sniptype__"]

    def listed(self, **params):
        return [item["trigger"] for item in self.result("library.list", **params)["items"]]

    def new_group(self, label="Trabalho", **values):
        answer = self.result("group.save", values={"label": label, **values})
        self.assertEqual("saved", answer["status"], answer)
        return answer["id"]

    def test_favorite_is_saved_and_filters_the_list(self):
        self.result("snippet.setFavorite", trigger="sig", favorite=True)
        self.assertTrue(self.metadata()["items"]["static"]["sig"]["favorite"])
        self.assertEqual(["sig"], self.listed(filter="favorites"))
        self.result("snippet.setFavorite", trigger="sig", favorite=False)
        self.assertEqual([], self.listed(filter="favorites"))

    def test_mapping_favorite_is_saved_and_listed(self):
        self.result("mapping.setFavorite", type="_cpf_numbers", name="fulano", favorite=True)
        self.assertTrue(self.metadata()["items"]["mappings"]["_cpf_numbers"]["fulano"]["favorite"])
        (item,) = self.result("mapping.list", type="_cpf_numbers")
        self.assertTrue(item["favorite"])
        self.assertTrue(self.result("mapping.get", type="_cpf_numbers", name="fulano")["favorite"])
        self.assertEqual("missing", self.error("mapping.setFavorite", type="_cpf_numbers", name="nobody",
                                               favorite=True)["code"])

    def test_group_create_assign_filter_and_prefix(self):
        group = self.new_group(prefix="w")
        self.assertEqual([{"id": group, "label": "Trabalho", "prefix": "w", "enabled": True, "count": 0}],
                         self.result("groups.list")["groups"])
        self.result("snippet.setGroup", trigger="hello", group=group)
        self.assertEqual(group, self.metadata()["items"]["static"]["hello"]["group_id"])
        items = {item["trigger"]: item for item in self.result("library.list")["items"]}
        self.assertEqual(("whello", group, "Trabalho"),
                         (items["hello"]["effectiveTrigger"], items["hello"]["groupId"], items["hello"]["group"]))
        self.assertEqual(["hello"], self.listed(group=group))
        self.assertNotIn("hello", self.listed(group="__ungrouped__"))
        self.assertEqual(("whello", group, False), tuple(
            self.result("snippet.get", trigger="hello")[k] for k in ("effectiveTrigger", "groupId", "favorite")))
        self.result("snippet.setGroup", trigger="hello", group="")
        self.assertNotIn("group_id", self.metadata()["items"]["static"].get("hello", {}))

    def test_group_dialog_values_and_validation(self):
        form = self.result("group.form")
        self.assertEqual("", form["values"]["label"])
        self.assertEqual({"inherit", "immediate", "terminator"}, {c["value"] for c in form["terminators"]})
        self.assertEqual({"all", "allow", "deny"}, {c["value"] for c in form["applicationModes"]})
        self.assertEqual(("invalid", "label"), tuple(self.result("group.save", values={"label": " "})[k]
                                                     for k in ("status", "field")))
        self.assertEqual("prefix", self.result("group.save", values={"label": "X", "prefix": "a b"})["field"])
        answer = self.result("group.save", values={"label": "Apps", "application_mode": "allow",
                                                   "executables": "Code.exe\n\ncode.exe"})
        stored = self.metadata()["groups"][answer["id"]]
        self.assertEqual({"mode": "allow", "executables": ["code.exe"]}, stored["applications"])
        self.assertEqual("Apps", self.result("group.form", id=answer["id"])["values"]["label"])

    def test_group_prefix_that_collides_is_refused_on_the_prefix_field(self):
        group = self.new_group()
        self.result("snippet.setGroup", trigger="hello", group=group)
        self.result("snippet.save", trigger="xhello", text="Other", confirmed=["warnings"])
        answer = self.result("group.save", id=group, values={"label": "Trabalho", "prefix": "x"})
        self.assertEqual(("invalid", "prefix"), (answer["status"], answer["field"]))
        self.assertEqual("", self.metadata()["groups"][group]["prefix"])

    def test_group_delete_ungroups_members_and_undo_brings_both_back(self):
        group = self.new_group()
        self.result("snippet.setGroup", trigger="hello", group=group)
        token = self.result("group.delete", id=group)["undoToken"]
        self.assertNotIn(group, self.metadata().get("groups", {}))
        self.assertNotIn("group_id", self.metadata()["items"]["static"].get("hello", {}))
        self.assertEqual("Hello there", on_disk(self.app)["hello"])
        self.result("group.undoDelete", token=token)
        self.assertIn(group, self.metadata()["groups"])
        self.assertEqual(group, self.metadata()["items"]["static"]["hello"]["group_id"])
        self.assertEqual("undo_expired", self.error("group.undoDelete", token=token)["code"])
        self.assertEqual("missing_group", self.error("group.delete", id="nope")["code"])

    def test_duplicate_copies_value_and_group_but_not_favorite(self):
        group = self.new_group()
        self.result("snippet.setGroup", trigger="fancy", group=group)
        self.result("snippet.setFavorite", trigger="fancy", favorite=True)
        self.assertEqual({"status": "duplicated", "trigger": "fancy2"},
                         self.result("snippet.duplicate", trigger="fancy", destination=" fancy2 "))
        disk = on_disk(self.app)
        self.assertEqual(disk["fancy"], disk["fancy2"])
        copied = self.metadata()["items"]["static"]["fancy2"]
        self.assertEqual((group, False), (copied["group_id"], copied["favorite"]))
        for destination in ("", "_x", "hello"):
            self.assertEqual("invalid", self.result("snippet.duplicate", trigger="sig",
                                                    destination=destination)["status"])
        self.assertEqual("missing", self.error("snippet.duplicate", trigger="gone", destination="g2")["code"])

    def test_rename_moves_value_and_metadata_and_asks_about_warnings(self):
        self.result("snippet.setFavorite", trigger="sig", favorite=True)
        self.assertEqual({"status": "renamed", "trigger": "sign"},
                         self.result("snippet.rename", trigger="sig", destination="sign"))
        disk = on_disk(self.app)
        self.assertNotIn("sig", disk)
        self.assertEqual("Best,\nTeo", disk["sign"])
        self.assertTrue(self.metadata()["items"]["static"]["sign"]["favorite"])
        self.assertEqual("invalid", self.result("snippet.rename", trigger="sign", destination="hello")["status"])
        answer = self.result("snippet.rename", trigger="sign", destination="ello")
        self.assertEqual(("confirm", "warnings"), (answer["status"], answer["check"]))
        self.assertIn("sign", on_disk(self.app))
        self.result("snippet.rename", trigger="sign", destination="ello", confirmed=["warnings"])
        self.assertIn("ello", on_disk(self.app))

    def test_failed_write_leaves_metadata_unchanged(self):
        with mock.patch.object(self.app, "save_snippets", return_value=False):
            self.assertEqual("save_failed", self.error("snippet.setFavorite", trigger="sig", favorite=True)["code"])
            self.assertEqual("save_failed", self.error("snippet.duplicate", trigger="sig", destination="s2")["code"])
        self.assertNotIn("s2", self.app.snippets)
        self.assertEqual([], self.listed(filter="favorites"))

    def test_recent_and_problem_filters(self):
        self.app.workflow_state.record_success(SnippetRef("static", "sig"))
        self.assertEqual(["sig"], self.listed(filter="recent"))
        self.assertEqual([], self.listed(filter="problems"))
        self.assertEqual("bad_params", self.error("library.list", filter="nope")["code"])
        self.assertEqual(3, self.result("library.list", filter="recent")["total"])


class DynamicBridgeTests(unittest.TestCase):
    """Snippets dinâmicos: the bundled registry, toggled and renamed through the user overrides."""

    def setUp(self):
        self.app = make_real_app(self, {"hello": "Hello there", "xhj": "Static text under a dynamic trigger"})
        self.bridge = ManagerBridge(self.app, version="9.9.9", channel="beta")

    call, result, error = BridgeTests.call, BridgeTests.result, BridgeTests.error

    def overrides(self):
        if not os.path.exists(self.app.dynamic_registry_file):
            return {}
        with open(self.app.dynamic_registry_file, encoding="utf-8") as handle:
            return json.load(handle)

    def entry(self, key):
        return next(item for section in self.result("dynamics.list") for item in section["items"]
                    if item["key"] == key)

    def test_list_holds_every_section_in_order_with_descriptions(self):
        sections = self.result("dynamics.list")
        self.assertEqual(["datetime", "economy", "stock", "whatsapp"], [s["id"] for s in sections])
        self.assertEqual("Data e Hora", sections[0]["label"])
        xhj = self.entry("xhj")
        self.assertEqual(("xhj", True), (xhj["trigger"], xhj["enabled"]))
        self.assertTrue(xhj["description"])
        self.assertEqual(len(self.app.dynamic_registry), sum(len(s["items"]) for s in sections))

    def test_disable_then_enable_over_a_static_asks_first(self):
        self.assertEqual("saved", self.result("dynamic.setEnabled", key="xhj", enabled=False)["status"])
        self.assertEqual({"enabled": False}, self.overrides()["xhj"])
        self.assertFalse(self.entry("xhj")["enabled"])
        answer = self.result("dynamic.setEnabled", key="xhj", enabled=True)
        self.assertEqual(("confirm", "shadow"), (answer["status"], answer["check"]))
        self.assertFalse(self.overrides()["xhj"]["enabled"])
        self.result("dynamic.setEnabled", key="xhj", enabled=True, confirmed=["shadow"])
        self.assertTrue(self.entry("xhj")["enabled"])
        self.assertEqual("Static text under a dynamic trigger", on_disk(self.app)["xhj"])

    def test_rename_validates_asks_about_warnings_and_persists(self):
        for bad in ("_x", "hello", "two words", ""):
            self.assertEqual("invalid", self.result("dynamic.rename", key="xhoje", trigger=bad)["status"], bad)
        answer = self.result("dynamic.rename", key="xhoje", trigger="llo")
        self.assertEqual(("confirm", "warnings"), (answer["status"], answer["check"]))
        self.assertNotIn("xhoje", self.overrides())
        self.assertEqual("renamed", self.result("dynamic.rename", key="xhoje", trigger="hojex")["status"])
        self.assertEqual("hojex", self.overrides()["xhoje"]["trigger"])
        self.assertEqual("hojex", self.entry("xhoje")["trigger"])
        self.result("dynamic.rename", key="xhoje", trigger="xhoje")
        self.assertNotIn("xhoje", self.overrides())

    def test_unknown_key_and_failed_write(self):
        self.assertEqual("missing", self.error("dynamic.setEnabled", key="nope", enabled=False)["code"])
        with mock.patch.object(self.app, "_toggle_registry_entry", return_value=False):
            self.assertEqual("save_failed", self.error("dynamic.setEnabled", key="xhoje", enabled=False)["code"])


class BackupBridgeTests(unittest.TestCase):
    """Backups, import and export: the window sends file contents, never paths."""

    def setUp(self):
        self.app = make_real_app(self, {"hello": "Hello there", "_cpf_numbers": {"fulano": "123.456.789-00"}})
        self.bridge = ManagerBridge(self.app, version="9.9.9", channel="beta")

    call, result, error = BridgeTests.call, BridgeTests.result, BridgeTests.error

    def test_create_then_list_with_counts(self):
        before = len(self.result("backups.list"))
        name = self.result("backup.create")["name"]
        listed = {backup["name"]: backup for backup in self.result("backups.list")}
        self.assertEqual(before + 1, len(listed))
        created = listed[name]
        self.assertEqual((1, 1, False), (created["texts"], created["lists"], created["empty"]))
        self.assertTrue(created["when"])

    def test_preview_and_restore_bring_the_backup_back(self):
        name = self.result("backup.create")["name"]
        self.result("snippet.save", trigger="later", text="Added after the backup")
        preview = self.result("backup.preview", name=name)
        self.assertEqual(1, preview["counts"]["removed"])
        count = len(self.result("backups.list"))
        self.result("backup.restore", name=name)
        self.assertNotIn("later", on_disk(self.app))
        self.assertNotIn("later", self.app.snippets)
        self.assertEqual(count + 1, len(self.result("backups.list")), "the replaced library is backed up first")

    def test_only_listed_backups_can_be_named(self):
        for name in ("../snippets.json", "snippets.json", "nope.json"):
            self.assertEqual("missing", self.error("backup.restore", name=name)["code"], name)
        self.assertIn("hello", on_disk(self.app))

    def test_export_text_is_the_library_file(self):
        exported = self.result("library.exportText")
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), exported["text"])
        self.assertTrue(exported["fileName"].endswith(".json"))

    def test_import_preview_merge_and_replace(self):
        text = json.dumps({"hello": "Replaced", "fresh": "New one"})
        counts = self.result("library.importPreview", text=text)
        self.assertEqual({"new": 1, "overwritten": 1, "removed": 0}, counts["merge"])
        self.assertEqual(1, counts["replace"]["removed"])
        self.result("library.import", text=text, mode="merge")
        disk = on_disk(self.app)
        self.assertEqual(("Replaced", "New one"), (disk["hello"], disk["fresh"]))
        self.assertIn("_cpf_numbers", disk)
        self.result("library.import", text=json.dumps({"only": "This"}), mode="replace")
        self.assertEqual({"only"}, {key for key in on_disk(self.app) if key != "__sniptype__"})

    def test_import_refuses_what_is_not_a_library(self):
        for text in ("not json", "[1, 2]"):
            self.assertEqual("invalid", self.error("library.importPreview", text=text)["code"], text)
            self.assertEqual("invalid", self.error("library.import", text=text, mode="merge")["code"], text)
        self.assertEqual("bad_params", self.error("library.import", text="{}", mode="wipe")["code"])
        self.assertIn("hello", on_disk(self.app))


class FormBridgeTests(unittest.TestCase):
    """Formulário and Prévia, for statics and mapping items."""

    def setUp(self):
        self.app = make_real_app(self, {
            "hello": "Hello there",
            "letter": "Dear %%name%%, see you %%when%%.",
            "sig": "Best, %%hello%%",
            "_email_codes": {"__prefix__": "mail", "work": "Hi %%who%%"},
        })
        self.bridge = ManagerBridge(self.app, version="9.9.9", channel="beta")

    call, result, error = BridgeTests.call, BridgeTests.result, BridgeTests.error

    def metadata(self):
        return on_disk(self.app)["__sniptype__"]

    def test_get_without_a_form_offers_the_template_fields(self):
        form = self.result("form.get", name="letter")
        self.assertFalse(form["saved"])
        self.assertEqual(["name", "when"], form["variables"])
        self.assertEqual(["name", "when"], [field["name"] for field in form["fields"]])
        self.assertEqual({"text", "multiline", "choice", "date", "optional"}, {t["value"] for t in form["types"]})
        self.assertEqual([], self.result("form.get", name="sig")["variables"], "a snippet reference is no field")

    def test_save_validates_then_persists_and_reopens(self):
        fields = [{"name": "name", "type": "text", "default": "friend", "label": "Name"},
                  {"name": "when", "type": "choice", "default": "", "options": ["soon", "later"]}]
        self.assertEqual({"status": "saved", "count": 2}, self.result("form.save", name="letter", fields=fields))
        stored = self.metadata()["items"]["static"]["letter"]["form"]["fields"]
        self.assertEqual(("friend", "soon", ["soon", "later"]),
                         (stored[0]["default"], stored[1]["default"], stored[1]["options"]))
        self.assertTrue(self.result("form.get", name="letter")["saved"])
        answer = self.result("form.save", name="letter", fields=fields[:1])
        self.assertEqual("invalid", answer["status"])
        self.assertIn("when", answer["message"])
        bad = self.result("form.save", name="letter", fields=[{"name": "na me", "type": "text"}, fields[1]])
        self.assertEqual(("invalid", 0), (bad["status"], bad["index"]))

    def test_mapping_form_and_duplicate_keeps_it(self):
        fields = [{"name": "who", "type": "text", "default": "team"}]
        self.result("form.save", name="work", type="_email_codes", fields=fields)
        self.assertEqual("team", self.metadata()["items"]["mappings"]["_email_codes"]["work"]["form"]["fields"][0]["default"])
        self.result("mapping.save", type="_email_codes", name="home", text="Hi %%who%%", formFrom="work")
        copied = self.metadata()["items"]["mappings"]["_email_codes"]["home"]["form"]
        self.assertEqual("team", copied["fields"][0]["default"])
        self.assertEqual("form", self.error("mapping.save", type="_email_codes", name="other",
                                            text="No fields here", formFrom="work")["code"])
        self.assertNotIn("other", on_disk(self.app)["_email_codes"])

    def test_preview_fills_defaults_references_and_drafts(self):
        self.result("form.save", name="letter", fields=[
            {"name": "name", "type": "text", "default": "friend"},
            {"name": "when", "type": "text", "default": "Monday"}])
        self.assertEqual("Dear friend, see you Monday.", self.result("preview.get", name="letter")["text"])
        self.assertEqual("Best, Hello there", self.result("preview.get", name="sig")["text"])
        draft = self.result("preview.get", text="Copied: %%clipboard-paste%%")
        self.assertIn("clipboard-paste", draft["status"])
        drifted = self.result("preview.get", name="letter", text="Only %%name%%")
        self.assertEqual("Only ", drifted["text"])
        self.assertTrue(drifted["status"])
        self.assertEqual("missing", self.error("form.get", name="nope")["code"])


class FindExecutableTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def touch(self, *parts):
        path = os.path.join(self.root, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path

    def test_override_must_exist(self):
        path = self.touch("custom.exe")
        self.assertEqual(path, find_manager_executable(env={"SNIPTYPE_MANAGER_EXE": path}))
        self.assertIsNone(find_manager_executable(env={"SNIPTYPE_MANAGER_EXE": path + ".missing"}))

    def test_packaged_app_uses_the_binary_beside_it(self):
        path = self.touch("app", "sniptype-manager.exe" if sys.platform == "win32" else "sniptype-manager")
        found = find_manager_executable(env={}, frozen=True, executable=os.path.join(self.root, "app", "Sniptype.exe"))
        self.assertEqual(path, found)

    def test_source_checkout_prefers_release_over_debug(self):
        name = "sniptype-manager.exe" if sys.platform == "win32" else "sniptype-manager"
        source = os.path.join(self.root, "source")
        debug = self.touch("ui", "src-tauri", "target", "debug", name)
        self.assertEqual(debug, find_manager_executable(env={}, frozen=False, source_dir=source))
        release = self.touch("ui", "src-tauri", "target", "release", name)
        self.assertEqual(release, find_manager_executable(env={}, frozen=False, source_dir=source))


CHILD = r"""
import json, sys
sys.stdout.write(json.dumps({"id": 1, "method": "library.list"}) + "\n")
sys.stdout.write("not json\n")
sys.stdout.flush()
answer = sys.stdin.readline()
with open(sys.argv[1], "w", encoding="utf-8") as out:
    out.write(answer)
"""


class ProcessRoundTripTests(unittest.TestCase):
    def test_child_request_is_answered_over_its_stdin(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        answer_file = os.path.join(tmp.name, "answer.json")
        app = mock.Mock()
        app.gui.call.side_effect = lambda func: func(None)
        bridge = mock.Mock()
        bridge.handle.return_value = {"id": 1, "result": ["ok"]}

        def popen(_args, **kwargs):
            return subprocess.Popen([sys.executable, "-c", CHILD, answer_file], **kwargs)

        process = ManagerProcess(app, "ignored.exe", bridge, popen=popen)
        process._reader.join(timeout=20)
        self.assertFalse(process._reader.is_alive())
        process.close()
        bridge.handle.assert_called_once_with({"id": 1, "method": "library.list"})
        with open(answer_file, encoding="utf-8") as handle:
            self.assertEqual({"id": 1, "result": ["ok"]}, json.loads(handle.read()))
        app.logger.warning.assert_called()  # the non-JSON line was reported, not answered


class StaleDraftTests(unittest.TestCase):
    """A draft opened before the library changed never overwrites the newer value unasked."""

    def setUp(self):
        self.app = make_real_app(self, {"hello": "Hello there", "_codes": {"__prefix__": "c", "city": "Goiânia"}})
        self.bridge = ManagerBridge(self.app, version="9.9.9", channel="stable")

    def result(self, method, **params):
        response = self.bridge.handle({"id": 1, "method": method, "params": params})
        self.assertNotIn("error", response, response)
        return response["result"]

    def change_behind_the_window(self, key, value, container=None):
        """Another writer (a tray reload of an edited file, a restore) puts ``value`` in the library."""
        if container is None:
            self.assertTrue(self.app.save_static_snippet(key, value))
        else:
            self.assertTrue(self.app.save_mapping_item(container, key, value))

    def test_get_and_save_carry_the_revision_of_the_stored_value(self):
        opened = self.result("snippet.get", trigger="hello")["revision"]
        self.assertIsInstance(opened, str)
        saved = self.result("snippet.save", trigger="hello", text="Hi", original="hello", base=opened)
        self.assertEqual("saved", saved["status"])
        self.assertNotEqual(opened, saved["revision"])
        self.assertEqual(saved["revision"], self.result("snippet.get", trigger="hello")["revision"])

    def test_check_reports_unchanged_changed_and_gone(self):
        base = self.result("snippet.get", trigger="hello")["revision"]
        self.assertEqual({"status": "unchanged", "revision": base},
                         self.result("draft.check", kind="static", key="hello", base=base))
        self.change_behind_the_window("hello", "Changed elsewhere")
        changed = self.result("draft.check", kind="static", key="hello", base=base)
        self.assertEqual("changed", changed["status"])
        self.assertNotEqual(base, changed["revision"])
        self.app._delete_static_snippet("hello", include_shadowed=True)
        self.assertEqual({"status": "gone", "revision": None},
                         self.result("draft.check", kind="static", key="hello", base=base))

    def test_saving_over_a_newer_version_asks_first(self):
        base = self.result("snippet.get", trigger="hello")["revision"]
        self.change_behind_the_window("hello", "Changed elsewhere")
        answer = self.result("snippet.save", trigger="hello", text="Old draft", original="hello", base=base)
        self.assertEqual(("confirm", "stale"), (answer["status"], answer["check"]))
        self.assertIn("alterado depois que você o abriu", answer["message"])
        self.assertEqual("Changed elsewhere", on_disk(self.app)["hello"])
        self.result("snippet.save", trigger="hello", text="Old draft", original="hello", base=base,
                    confirmed=["stale"])
        self.assertEqual("Old draft", on_disk(self.app)["hello"])

    def test_saving_a_deleted_item_asks_before_creating_it_again(self):
        base = self.result("snippet.get", trigger="hello")["revision"]
        self.app._delete_static_snippet("hello", include_shadowed=True)
        answer = self.result("snippet.save", trigger="hello", text="Back", original="hello", base=base)
        self.assertEqual("stale", answer["check"])
        self.assertIn("excluído", answer["message"])
        self.assertNotIn("hello", on_disk(self.app))

    def test_without_a_base_the_save_behaves_as_before(self):
        self.change_behind_the_window("hello", "Changed elsewhere")
        self.assertEqual("saved", self.result("snippet.save", trigger="hello", text="Mine", original="hello")["status"])

    def test_mapping_items_get_the_same_guard(self):
        base = self.result("mapping.get", type="_codes", name="city")["revision"]
        self.assertEqual("unchanged", self.result("draft.check", kind="mapping", key="city", base=base,
                                                  container="_codes")["status"])
        self.change_behind_the_window("city", "Anápolis", container="_codes")
        answer = self.result("mapping.save", type="_codes", name="city", text="Old", original="city", base=base)
        self.assertEqual("stale", answer["check"])
        saved = self.result("mapping.save", type="_codes", name="city", text="Old", original="city", base=base,
                            confirmed=["stale"])
        self.assertEqual("Old", on_disk(self.app)["_codes"]["city"])
        self.assertEqual(saved["revision"], self.result("mapping.get", type="_codes", name="city")["revision"])


class ExpansionStateAndHealthTests(unittest.TestCase):
    """The window shows the expansion state, pauses it, and runs each issue's action."""

    def setUp(self):
        self.app = make_real_app(self, {"hello": "Hello there"})
        self.app.icon = None
        self.bridge = ManagerBridge(self.app, version="9.9.9", channel="stable")

    def result(self, method, **params):
        response = self.bridge.handle({"id": 1, "method": method, "params": params})
        self.assertNotIn("error", response, response)
        return response["result"]

    def error(self, method, **params):
        response = self.bridge.handle({"id": 1, "method": method, "params": params})
        self.assertIn("error", response, response)
        return response["error"]["code"]

    def test_info_names_the_expansion_state_and_the_last_expansion(self):
        info = self.result("app.info")
        self.assertEqual({"state": "ok", "label": "Expansão ativa"}, info["expansion"])
        self.assertEqual("Nada expandido ainda", info["lastExpansion"])
        self.assertFalse(info["canEditLast"])

    def test_pause_and_resume_from_the_window_return_the_receipt_instead_of_a_toast(self):
        with mock.patch.object(self.app, "notify") as notify:
            paused = self.result("app.toggleEnabled")
            self.assertFalse(self.app.enabled)
            self.assertTrue(paused["receipt"].startswith("Expansão pausada às"))
            self.assertEqual("paused", self.result("app.info")["expansion"]["state"])
            resumed = self.result("app.toggleEnabled")
        self.assertTrue(self.app.enabled)
        self.assertTrue(resumed["receipt"].startswith("Expansão retomada às"))
        notify.assert_not_called()

    def test_a_failed_capture_cannot_be_resumed_from_the_window(self):
        self.app.enabled = False
        self.app.capture_error = OSError("hook")
        with mock.patch.object(self.app, "notify_error") as notify_error:
            self.assertIsNone(self.result("app.toggleEnabled")["receipt"])
        self.assertFalse(self.app.enabled)
        notify_error.assert_called_once()
        self.assertEqual("down", self.result("app.info")["expansion"]["state"])

    def test_issues_carry_their_action_and_resume_runs_it(self):
        self.app.enabled = False
        issue = next(issue for issue in self.result("app.info")["issues"] if issue["id"] == "paused")
        self.assertEqual(("resume", "Retomar", False),
                         (issue["action"], issue["actionLabel"], issue["dismissible"]))
        answer = self.result("health.run", action="resume")
        self.assertIsNone(answer["page"])
        self.assertTrue(answer["receipt"].startswith("Expansão retomada às"))
        self.assertTrue(self.app.enabled)

    def test_page_actions_name_the_page_and_others_reuse_the_app(self):
        self.assertEqual({"page": "backups", "receipt": None}, self.result("health.run", action="open_backups"))
        self.assertEqual("dinamicos", self.result("health.run", action="open_dynamic")["page"])
        for action, method in (("open_folder", "open_data_folder"), ("open_log", "open_log"),
                               ("retry_sync", "retry_sync")):
            with self.subTest(action), mock.patch.object(self.app, method) as called:
                self.assertEqual({"page": None, "receipt": None}, self.result("health.run", action=action))
                called.assert_called_once_with()
        self.assertEqual("bad_params", self.error("health.run", action="reboot"))

    def test_only_info_issues_can_be_dismissed(self):
        self.app.library_recovery = {"kind": "backup", "at": "2026-11-05T10:00:00"}
        self.app.enabled = False
        ids = {issue["id"]: issue["dismissible"] for issue in self.result("app.info")["issues"]}
        restored = next(key for key in ids if key.startswith("restored:"))
        self.assertTrue(ids[restored])
        self.assertEqual("bad_params", self.error("health.dismiss", id="paused"))
        self.assertIsNone(self.result("health.dismiss", id=restored))
        remaining = [issue["id"] for issue in self.result("app.info")["issues"]]
        self.assertEqual(["paused"], remaining)
        self.assertEqual("not_found", self.error("health.dismiss", id=restored))

    def test_edit_last_needs_an_expansion_and_then_queues_it(self):
        self.assertEqual("not_found", self.error("app.editLast"))
        self.app.workflow_state.record_success(SnippetRef("static", "hello"))
        self.app._last_successful_expansion_at = tx.datetime(2026, 11, 5, 14, 32)
        info = self.result("app.info")
        self.assertTrue(info["canEditLast"])
        self.assertIn("hello", info["lastExpansion"])
        with mock.patch.object(self.app, "edit_last_snippet") as edit_last:
            self.assertIsNone(self.result("app.editLast"))
        edit_last.assert_called_once_with()


class HotkeySettingsTests(unittest.TestCase):
    """Configurações records and saves the workflow hotkeys through the app's own save."""

    def setUp(self):
        self.app = make_real_app(self, {"hello": "Hello there"})
        self.app.icon = None
        self.bridge = ManagerBridge(self.app, version="9.9.9", channel="stable")

    def result(self, method, **params):
        response = self.bridge.handle({"id": 1, "method": method, "params": params})
        self.assertNotIn("error", response, response)
        return response["result"]

    def test_info_lists_the_three_hotkeys_off_by_default(self):
        hotkeys = self.result("app.info")["hotkeys"]
        self.assertEqual(["open_manager", "edit_last", "toggle_enabled"], [h["action"] for h in hotkeys])
        self.assertEqual("Abrir gerenciador", hotkeys[0]["label"])
        self.assertTrue(all(h["binding"] is None and h["display"] == "" for h in hotkeys))

    def test_capture_translates_a_key_press(self):
        self.assertEqual({"binding": "<ctrl>+<shift>+m", "display": "Ctrl+Shift+M"},
                         self.result("hotkeys.capture", key="M", code="KeyM", ctrl=True, shift=True))
        self.assertIsNone(self.result("hotkeys.capture", key="Shift", code="ShiftLeft", shift=True)["binding"])

    def test_save_persists_and_replaces_the_live_router(self):
        before = self.app.hotkey_router
        answer = self.result("hotkeys.save", bindings={"open_manager": "<ctrl>+<shift>+m",
                                                       "edit_last": None, "toggle_enabled": None})
        self.assertEqual("saved", answer["status"])
        self.assertEqual("Ctrl+Shift+M", answer["hotkeys"][0]["display"])
        with open(self.app.settings_file, encoding="utf-8") as handle:
            self.assertEqual("<ctrl>+<shift>+m", json.load(handle)["hotkeys"]["open_manager"])
        # The live router was replaced and knows the new chord, with no restart.
        self.assertIsNot(before, self.app.hotkey_router)
        self.assertEqual({"open_manager"}, set(self.app.hotkey_router._chords))

    def test_invalid_and_duplicate_bindings_are_refused_in_words(self):
        answer = self.result("hotkeys.save", bindings={"open_manager": "m", "edit_last": None,
                                                       "toggle_enabled": None})
        self.assertEqual(("invalid", "open_manager"), (answer["status"], answer["field"]))
        self.assertEqual("Uma letra ou um número precisa de Ctrl, Alt ou Win.", answer["message"])
        answer = self.result("hotkeys.save", bindings={"open_manager": "<ctrl>+<shift>+m",
                                                       "edit_last": "<ctrl>+<shift>+m", "toggle_enabled": None})
        self.assertEqual("edit_last", answer["field"])
        self.assertEqual("Já é o atalho de Abrir gerenciador.", answer["message"])
        self.assertNotIn("hotkeys", self.app.settings)

    def test_tray_configurar_atalhos_opens_the_window_at_settings(self):
        process = mock.Mock(alive=True)
        self.app._manager_process = process
        with mock.patch.object(self.app.gui, "submit") as submit:
            self.app.configure_hotkeys()
        process.send.assert_called_once_with({"event": "target"})
        submit.assert_not_called()
        self.assertEqual({"kind": "page", "key": "settings", "container": None}, self.result("app.takeTarget"))
        self.assertIsNone(self.result("app.takeTarget"))

    def test_without_the_window_the_tray_opens_the_classic_dialog(self):
        with mock.patch.object(tx, "find_manager_executable", return_value=None), \
                mock.patch.object(self.app.gui, "submit") as submit:
            self.app.configure_hotkeys()
        submit.assert_called_once_with(self.app._show_hotkey_settings)
        self.assertIsNone(self.app._pending_manager_page)


class WindowPlaceTests(unittest.TestCase):
    """The window reopens where it was: the app keeps its place in settings.json."""

    def setUp(self):
        self.app = make_real_app(self, {"hello": "Hello there"})
        self.bridge = ManagerBridge(self.app, version="9.9.9", channel="stable")

    def call(self, method, **params):
        return self.bridge.handle({"id": 1, "method": method, "params": params})

    def test_first_time_there_is_no_saved_place(self):
        self.assertEqual({}, self.call("app.info")["result"]["window"])

    def test_save_persists_and_info_returns_it(self):
        value = {"x": 40, "y": 30, "width": 1200, "height": 780, "maximized": False, "page": "mapeamentos"}
        self.assertIsNone(self.call("window.save", value=value)["result"])
        with open(self.app.settings_file, encoding="utf-8") as handle:
            self.assertEqual(value, json.load(handle)["manager_window"])
        self.assertEqual(value, self.call("app.info")["result"]["window"])

    def test_an_unusable_state_is_refused_and_not_saved(self):
        self.assertEqual("bad_params", self.call("window.save", value={"x": "left"})["error"]["code"])
        self.assertNotIn("manager_window", self.app.settings)

    def test_saving_the_same_place_again_does_not_write(self):
        value = {"x": 40, "y": 30, "width": 1200, "height": 780, "maximized": False, "page": "textos"}
        self.call("window.save", value=value)
        with mock.patch.object(self.app, "_persist_settings") as persist:
            self.call("window.save", value=dict(value))
        persist.assert_not_called()


class ManagerEventPushTests(unittest.TestCase):
    """The app tells a running window when its state or its library changed."""

    def setUp(self):
        self.app = make_real_app(self, {"hello": "Hello there"})
        self.app.icon = None
        self.process = mock.Mock(alive=True)
        self.app._manager_process = self.process

    def events(self):
        return [call.args[0]["event"] for call in self.process.send.call_args_list]

    def test_nothing_is_sent_without_a_running_window(self):
        self.process.alive = False
        self.app._push_manager_event("state")
        self.app._manager_process = None
        self.app._push_manager_event("state")
        self.process.send.assert_not_called()

    def test_a_pause_from_anywhere_reaches_the_window(self):
        self.app.toggle_enabled(None, None)
        self.assertIn("state", self.events())

    def test_health_facts_and_replaced_libraries_reach_the_window(self):
        self.app._request_health_refresh()
        self.assertEqual(["state"], self.events())
        self.process.send.reset_mock()
        self.app._library_replaced()
        self.assertEqual(["state", "library"], self.events())

    def test_reloading_the_library_tells_the_window(self):
        with mock.patch.object(self.app, "notify_status"):
            self.assertTrue(self.app._reload_snippets())
        self.assertIn("library", self.events())


class OpenManagerRoutingTests(unittest.TestCase):
    def _app(self, settings):
        app = object.__new__(tx.Sniptype)
        app.settings = settings
        app.gui = mock.Mock()
        app.logger = mock.Mock()
        app.logs_dir = tempfile.gettempdir()
        app.notify_error = mock.Mock()
        app._manager_process = None
        app._manager_process_lock = threading.Lock()
        app._pending_manager_target = None
        return app

    def test_tauri_window_is_the_default(self):
        app = self._app({})
        process = mock.Mock(alive=True)
        with mock.patch.object(tx, "find_manager_executable", return_value="m.exe"), \
                mock.patch.object(tx, "ManagerProcess", return_value=process) as spawn:
            app.open_manager()
        spawn.assert_called_once()
        app.gui.submit.assert_not_called()

    def test_a_leftover_classic_choice_still_opens_the_tauri_window(self):
        app = self._app({"manager_ui": "tk"})
        process = mock.Mock(alive=True)
        with mock.patch.object(tx, "find_manager_executable", return_value="m.exe"),                 mock.patch.object(tx, "ManagerProcess", return_value=process) as spawn:
            app.open_manager()
        spawn.assert_called_once()
        app.gui.submit.assert_not_called()

    def test_default_without_the_binary_opens_the_classic_manager_quietly(self):
        app = self._app({})
        with mock.patch.object(tx, "find_manager_executable", return_value=None):
            app.open_manager()
        app.notify_error.assert_not_called()
        app.gui.submit.assert_called_once_with(app._show_manager_window)

    def test_edit_last_target_reaches_a_running_window_once(self):
        app = self._app({})
        app._pending_manager_target = SnippetRef("static", "sig")
        process = mock.Mock(alive=True)
        app._manager_process = process
        app.open_manager()
        process.send.assert_called_once_with({"event": "target"})
        bridge = ManagerBridge(app, version="9.9.9", channel="beta")
        self.assertEqual({"kind": "static", "key": "sig", "container": None}, bridge.take_target())
        self.assertIsNone(bridge.take_target())

    def test_starts_the_tauri_window_once_then_focuses_it(self):
        app = self._app({})
        process = mock.Mock(alive=True)
        with mock.patch.object(tx, "find_manager_executable", return_value="m.exe"),                 mock.patch.object(tx, "ManagerProcess", return_value=process) as spawn:
            app.open_manager()
            app.open_manager()
        spawn.assert_called_once()
        process.focus.assert_called_once_with()
        app.gui.submit.assert_not_called()

    def test_failed_start_says_so_and_opens_the_classic_manager(self):
        app = self._app({})
        with mock.patch.object(tx, "find_manager_executable", return_value="m.exe"),                 mock.patch.object(tx, "ManagerProcess", side_effect=OSError("denied")):
            app.open_manager()
        app.notify_error.assert_called_once()
        app.gui.submit.assert_called_once_with(app._show_manager_window)


if __name__ == "__main__":
    unittest.main()
