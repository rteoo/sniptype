"""Tests for the desktop -> mobile sync bundle (docs/sync-design.md, issue #31)."""

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sync_export as se


FIXED_TIME = time.strptime("2026-07-21T13:45:02", "%Y-%m-%dT%H:%M:%S")


class RecordingLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)

    def info(self, message):
        pass

    def error(self, message):
        pass


def build(static, registry=None, logger=None, app_version="3.2.1"):
    return se.build_bundle(
        static, registry or {}, app_version=app_version, now=FIXED_TIME, logger=logger
    )


def triggers(bundle):
    return [entry["trigger"] for entry in bundle["entries"]]


def entry_for(bundle, trigger):
    for entry in bundle["entries"]:
        if entry["trigger"] == trigger:
            return entry
    return None


class TopLevelShapeTests(unittest.TestCase):
    def test_required_fields_present(self):
        bundle = build({"xa": "A"})
        self.assertEqual(bundle["schema_version"], 1)
        self.assertEqual(bundle["exported_at"], "2026-07-21T13:45:02Z")
        self.assertEqual(bundle["generator"]["name"], "txt_xpander")
        self.assertEqual(bundle["generator"]["platform"], sys.platform)
        self.assertIsInstance(bundle["entries"], list)
        self.assertIsInstance(bundle["dynamic"], list)

    def test_injected_app_version_round_trips(self):
        # §5.1 leaves the constant undecided, so assert the round-trip, not a literal.
        self.assertEqual(build({}, app_version="9.9.9")["generator"]["version"], "9.9.9")

    def test_app_version_may_be_null(self):
        self.assertIsNone(build({}, app_version=None)["generator"]["version"])


class MappingExpansionTests(unittest.TestCase):
    def test_builtin_containers_expand(self):
        bundle = build({
            "_cpf_numbers": {"fulano": "123.456.789-00"},
            "_cnpj_numbers": {"empresa": "12.345.678/0001-90"},
        })
        self.assertEqual(sorted(triggers(bundle)), ["cnpjempresa", "cpffulano"])
        entry = entry_for(bundle, "cpffulano")
        self.assertEqual(entry["source"], "mapping")
        self.assertEqual(
            entry["group"],
            {"container": "_cpf_numbers", "prefix": "cpf", "item": "fulano"},
        )

    def test_custom_container_uses_explicit_prefix(self):
        bundle = build({"_custom_codes": {"__prefix__": "cod", "nf": "NF-4471"}})
        self.assertEqual(triggers(bundle), ["codnf"])

    def test_prefix_key_never_becomes_a_trigger(self):
        bundle = build({"_custom_codes": {"__prefix__": "cod", "nf": "x"}})
        self.assertNotIn("cod__prefix__", triggers(bundle))
        self.assertNotIn("__prefix__", triggers(bundle))

    def test_empty_prefix_yields_bare_item_names(self):
        bundle = build({"_custom_codes": {"__prefix__": "", "nf": "NF-1"}})
        self.assertEqual(triggers(bundle), ["nf"])

    def test_derived_prefix_strips_every_numbers_and_codes_occurrence(self):
        bundle = build({"_client_codes_codes": {"a": "1"}})
        # get_dynamic_prefixes uses str.replace, which removes every occurrence.
        self.assertEqual(triggers(bundle), ["clienta"])

    def test_two_containers_claiming_one_prefix_export_only_the_winner(self):
        # get_dynamic_prefixes is keyed by prefix: the last container wins and the
        # earlier one is genuinely unreachable at runtime, so it must not export.
        bundle = build({
            "_dup_codes": {"__prefix__": "p", "a": "first"},
            "_other_codes": {"__prefix__": "p", "b": "second"},
        })
        self.assertEqual(triggers(bundle), ["pb"])

    def test_non_container_underscore_key_is_dropped(self):
        bundle = build({"_notes": "just a note", "xa": "A"})
        self.assertEqual(triggers(bundle), ["xa"])

    def test_expansion_matches_the_runtime_trigger_set(self):
        from dynamic_registry import composed_mapping_triggers

        static = {
            "xa": "A",
            "_cpf_numbers": {"fulano": "1", "beltrano": "2"},
            "_custom_codes": {"__prefix__": "cod", "nf": "3"},
            "_notes": "ignored",
        }
        bundle = build(static)
        mapping = {e["trigger"] for e in bundle["entries"] if e["source"] == "mapping"}
        self.assertEqual(mapping, composed_mapping_triggers(static))


class OrderingTests(unittest.TestCase):
    def test_static_first_then_mappings_in_prefix_order(self):
        bundle = build({
            "xb": "B",
            "_cpf_numbers": {"z": "1", "a": "2"},
            "xa": "A",
        })
        self.assertEqual(triggers(bundle), ["xb", "xa", "cpfz", "cpfa"])

    def test_identical_input_yields_byte_identical_output(self):
        static = {"xa": "A", "_cpf_numbers": {"f": "1"}}
        registry = {"xhj": {"provider": "datetime", "format": "%d/%m/%Y"}}
        first = json.dumps(build(static, registry), ensure_ascii=False, indent=2)
        second = json.dumps(build(static, registry), ensure_ascii=False, indent=2)
        self.assertEqual(first, second)


class RichTextTests(unittest.TestCase):
    def payload(self, text, html="<div>x</div>"):
        return {"__kind__": "rich_text", "text": text, "spans": [], "html": html, "rtf": "{}"}

    def test_html_copied_when_clean(self):
        bundle = build({"xa": self.payload("Example User\nDiretor")})
        entry = entry_for(bundle, "xa")
        self.assertEqual(entry["kind"], "rich_text")
        self.assertEqual(entry["text"], "Example User\nDiretor")
        self.assertEqual(entry["html"], "<div>x</div>")
        self.assertNotIn("spans", entry)
        self.assertNotIn("rtf", entry)

    def test_html_omitted_when_raw_value_had_variables(self):
        bundle = build({"xname": "Example User", "xa": self.payload("Olá, %%xname%%")})
        entry = entry_for(bundle, "xa")
        self.assertEqual(entry["kind"], "rich_text")
        self.assertEqual(entry["text"], "Olá, Example User")
        self.assertNotIn("html", entry)

    def test_empty_html_is_not_emitted(self):
        bundle = build({"xa": self.payload("plain", html="")})
        self.assertNotIn("html", entry_for(bundle, "xa"))

    def test_mapping_values_may_be_rich_text(self):
        bundle = build({"_custom_codes": {"__prefix__": "c", "a": self.payload("R")}})
        entry = entry_for(bundle, "ca")
        self.assertEqual(entry["kind"], "rich_text")
        self.assertEqual(entry["source"], "mapping")


class UnexportableValueTests(unittest.TestCase):
    def test_non_string_values_skipped_with_warning(self):
        logger = RecordingLogger()
        bundle = build({"xa": None, "xb": 42, "xc": ["a"], "xd": {"a": 1}, "xe": "ok"}, logger=logger)
        self.assertEqual(triggers(bundle), ["xe"])
        self.assertEqual(len(logger.warnings), 4)

    def test_callables_skipped_silently(self):
        logger = RecordingLogger()
        bundle = build({"xa": lambda: "runtime", "xb": "ok"}, logger=logger)
        self.assertEqual(triggers(bundle), ["xb"])
        self.assertEqual(logger.warnings, [])


class VariableResolutionTests(unittest.TestCase):
    def test_snippet_ref_is_resolved(self):
        bundle = build({"xname": "Project Contributors", "xs": "Olá, aqui é %%xname%%."})
        entry = entry_for(bundle, "xs")
        self.assertEqual(entry["text"], "Olá, aqui é Project Contributors.")
        self.assertNotIn("input", entry)

    def test_mapping_ref_is_resolved(self):
        bundle = build({
            "_cpf_numbers": {"fulano": "123.456.789-00"},
            "xs": "CPF: %%cpffulano%%",
        })
        self.assertEqual(entry_for(bundle, "xs")["text"], "CPF: 123.456.789-00")

    def test_clipboard_is_preserved_and_flagged(self):
        bundle = build({"xs": "Copiado: %%clipboard-paste%%"})
        entry = entry_for(bundle, "xs")
        self.assertEqual(entry["text"], "Copiado: %%clipboard-paste%%")
        self.assertTrue(entry["input"]["clipboard"])
        self.assertEqual(entry["input"]["fields"], [])

    def test_form_field_is_preserved_and_listed(self):
        bundle = build({"xs": "Prezado %%cliente%%, tudo bem %%cliente%%?"})
        entry = entry_for(bundle, "xs")
        self.assertEqual(entry["input"]["fields"], ["cliente"])
        self.assertFalse(entry["input"]["clipboard"])

    def test_dynamic_ref_is_preserved_and_listed(self):
        registry = {"xdolar": {"provider": "bcb", "method": "dolar"}}
        bundle = build({"xs": "Hoje: %%xdolar%%"}, registry)
        entry = entry_for(bundle, "xs")
        self.assertEqual(entry["text"], "Hoje: %%xdolar%%")
        self.assertEqual(entry["input"]["dynamic_refs"], ["xdolar"])

    def test_static_never_shadows_a_dynamic_ref_in_the_classification_map(self):
        # The map is built dynamic-last. Built the other way round, %%xdolar%%
        # would classify as snippet_ref and get baked.
        registry = {"xdolar": {"provider": "bcb", "method": "dolar"}}
        bundle = build({"xdolar": "STALE", "xs": "Hoje: %%xdolar%%"}, registry)
        entry = entry_for(bundle, "xs")
        self.assertEqual(entry["text"], "Hoje: %%xdolar%%")
        self.assertEqual(entry["input"]["dynamic_refs"], ["xdolar"])

    def test_export_never_invokes_a_callable(self):
        # The sentinel raises if called; a bundle building at all proves it isn't.
        registry = {"xhj": {"provider": "datetime", "format": "%d/%m/%Y"}}
        bundle = build({"xs": "Data: %%xhj%%"}, registry)
        self.assertEqual(entry_for(bundle, "xs")["text"], "Data: %%xhj%%")

    def test_injected_form_token_reaches_fields_via_rescan(self):
        # Routing is decided from the raw value, but the desktop's form dialog is
        # built from the resolved one, so a one-level ref's form token is prompted
        # for and must be listed.
        bundle = build({"xb": "Prezado %%cliente%%", "xa": "%%xb%%, bom dia"})
        entry = entry_for(bundle, "xa")
        self.assertEqual(entry["text"], "Prezado %%cliente%%, bom dia")
        self.assertEqual(entry["input"]["fields"], ["cliente"])
        self.assertEqual(entry["input"]["residual"], [])

    def test_injected_ref_lands_in_residual(self):
        bundle = build({"xc": "C", "xb": "Olá %%xc%%", "xa": "%%xb%%"})
        entry = entry_for(bundle, "xa")
        self.assertEqual(entry["text"], "Olá %%xc%%")
        self.assertEqual(entry["input"]["residual"], ["xc"])
        self.assertEqual(entry["input"]["fields"], [])

    def test_residual_is_defined_by_survival_not_provenance(self):
        # "%%xname%% e %%xb%%" with xb = "cc %%xname%%": the second copy is never
        # chased, so xname is residual even though it was in the raw list.
        bundle = build({
            "xname": "Example User",
            "xb": "cc %%xname%%",
            "xa": "%%xname%% e %%xb%%",
        })
        entry = entry_for(bundle, "xa")
        self.assertEqual(entry["text"], "Example User e cc %%xname%%")
        self.assertEqual(entry["input"]["residual"], ["xname"])

    def test_consumed_names_are_not_also_residual(self):
        registry = {"xdolar": {"provider": "bcb", "method": "dolar"}}
        bundle = build({"xs": "%%cliente%% %%xdolar%% %%clipboard-paste%%"}, registry)
        block = entry_for(bundle, "xs")["input"]
        self.assertEqual(block["fields"], ["cliente"])
        self.assertEqual(block["dynamic_refs"], ["xdolar"])
        self.assertTrue(block["clipboard"])
        self.assertEqual(block["residual"], [])

    def test_ref_to_unexportable_value_is_left_as_a_token(self):
        # extract_plain_text would otherwise inject a literal "['a']".
        bundle = build({"xbad": ["a"], "xa": "Olá %%xbad%%"})
        entry = entry_for(bundle, "xa")
        self.assertEqual(entry["text"], "Olá %%xbad%%")
        self.assertEqual(entry["input"]["residual"], ["xbad"])

    def test_clean_value_has_no_input_block(self):
        self.assertNotIn("input", entry_for(build({"xa": "plain"}), "xa"))


class PrecedenceTests(unittest.TestCase):
    def test_accepted_dynamic_beats_static(self):
        logger = RecordingLogger()
        registry = {"xhj": {"provider": "datetime", "format": "%d/%m/%Y"}}
        bundle = build({"xhj": "static value", "xa": "A"}, registry, logger=logger)
        self.assertEqual(triggers(bundle), ["xa"])
        self.assertTrue(any("xhj" in w for w in logger.warnings))

    def test_unknown_provider_loses_to_the_static_snippet(self):
        # Precedence runs over the export accept set, not merely the enabled set:
        # an entry with a bad provider binds nothing, so the static snippet fires.
        registry = {"xhj": {"provider": "typo", "method": "x"}}
        bundle = build({"xhj": "static value"}, registry)
        self.assertEqual(triggers(bundle), ["xhj"])
        self.assertEqual(entry_for(bundle, "xhj")["text"], "static value")

    def test_disabled_dynamic_loses_to_the_static_snippet(self):
        registry = {"xhj": {"provider": "datetime", "enabled": False}}
        bundle = build({"xhj": "static value"}, registry)
        self.assertEqual(triggers(bundle), ["xhj"])

    def test_static_beats_mapping_composed(self):
        logger = RecordingLogger()
        bundle = build(
            {"cpffulano": "static", "_cpf_numbers": {"fulano": "mapped"}}, logger=logger
        )
        self.assertEqual(triggers(bundle), ["cpffulano"])
        self.assertEqual(entry_for(bundle, "cpffulano")["source"], "static")
        self.assertTrue(any("cpffulano" in w for w in logger.warnings))

    def test_dynamic_beats_mapping_composed(self):
        registry = {"cpffulano": {"provider": "datetime", "format": "%d"}}
        bundle = build({"_cpf_numbers": {"fulano": "mapped"}}, registry)
        self.assertEqual(triggers(bundle), [])

    def test_no_duplicate_triggers_ever(self):
        bundle = build({
            "cpffulano": "static",
            "_cpf_numbers": {"fulano": "mapped"},
            "_other_codes": {"__prefix__": "cpf", "fulano": "also"},
        })
        self.assertEqual(len(triggers(bundle)), len(set(triggers(bundle))))


class AcceptSetTests(unittest.TestCase):
    def test_disabled_entries_excluded(self):
        registry = {
            "xhj": {"provider": "datetime", "format": "%d/%m/%Y"},
            "xdolar": {"provider": "bcb", "method": "dolar", "enabled": False},
        }
        bundle = build({}, registry)
        self.assertEqual([row["id"] for row in bundle["dynamic"]], ["xhj"])

    def test_enabled_field_is_emitted_on_survivors(self):
        bundle = build({}, {"xhj": {"provider": "datetime", "format": "%d"}})
        self.assertTrue(bundle["dynamic"][0]["enabled"])

    def test_non_dict_entry_skipped(self):
        bundle = build({}, {"xhj": "not a dict"})
        self.assertEqual(bundle["dynamic"], [])

    def test_unknown_provider_skipped_with_warning(self):
        logger = RecordingLogger()
        bundle = build({}, {"xhj": {"provider": "nope"}}, logger=logger)
        self.assertEqual(bundle["dynamic"], [])
        self.assertTrue(any("nope" in w for w in logger.warnings))

    def test_invalid_bcb_and_stock_methods_skipped(self):
        registry = {
            "a": {"provider": "bcb", "method": "bogus"},
            "b": {"provider": "stock", "method": "bogus"},
            "c": {"provider": "whatsapp", "mode": "bogus"},
        }
        self.assertEqual(build({}, registry)["dynamic"], [])

    def test_valid_provider_methods_accepted(self):
        registry = {
            "a": {"provider": "bcb", "method": "dolar"},
            "b": {"provider": "stock", "method": "cotacao"},
            "c": {"provider": "whatsapp", "mode": "open"},
        }
        self.assertEqual([row["id"] for row in build({}, registry)["dynamic"]], ["a", "b", "c"])

    def test_duplicate_effective_trigger_first_wins(self):
        logger = RecordingLogger()
        registry = {
            "a": {"provider": "datetime", "format": "%d"},
            "b": {"provider": "datetime", "format": "%m", "trigger": "a"},
        }
        bundle = build({}, registry, logger=logger)
        self.assertEqual([row["id"] for row in bundle["dynamic"]], ["a"])
        self.assertTrue(any("duplicado" in w for w in logger.warnings))

    def test_an_unbound_entry_does_not_reserve_its_trigger(self):
        # build_dynamic_snippets checks duplicates against *bound* entries only.
        registry = {
            "a": {"provider": "typo"},
            "b": {"provider": "datetime", "format": "%d", "trigger": "a"},
        }
        self.assertEqual([row["id"] for row in build({}, registry)["dynamic"]], ["b"])

    def test_rename_reaches_trigger_while_id_stays_stable(self):
        registry = {"xhj": {"provider": "datetime", "format": "%d", "trigger": "data"}}
        row = build({}, registry)["dynamic"][0]
        self.assertEqual(row["id"], "xhj")
        self.assertEqual(row["trigger"], "data")


class DynamicMetadataTests(unittest.TestCase):
    def test_category_falls_back_to_provider_then_other(self):
        registry = {
            "a": {"provider": "datetime", "category": "datetime", "format": "%d"},
            "b": {"provider": "bcb", "method": "dolar"},
        }
        rows = build({}, registry)["dynamic"]
        self.assertEqual(rows[0]["category"], "datetime")
        self.assertEqual(rows[1]["category"], "bcb")

    def test_description_defaults_to_empty_string(self):
        self.assertEqual(build({}, {"a": {"provider": "datetime"}})["dynamic"][0]["description"], "")

    def test_datetime_is_local_with_render(self):
        registry = {"xhj": {"provider": "datetime", "format": "%d/%m/%Y"}}
        row = build({}, registry)["dynamic"][0]
        self.assertTrue(row["local"])
        self.assertEqual(
            row["render"],
            {"kind": "date_format", "unicode_pattern": "dd/MM/yyyy", "locale": "pt-BR"},
        )

    def test_non_datetime_providers_are_not_local(self):
        registry = {"xdolar": {"provider": "bcb", "method": "dolar"}}
        row = build({}, registry)["dynamic"][0]
        self.assertFalse(row["local"])
        self.assertNotIn("render", row)

    def test_format_absent_uses_the_provider_default(self):
        row = build({}, {"a": {"provider": "datetime"}})["dynamic"][0]
        self.assertEqual(row["render"]["unicode_pattern"], "dd/MM/yyyy")

    def test_extenso_wins_over_format(self):
        registry = {"a": {"provider": "datetime", "method": "extenso", "format": "%d"}}
        row = build({}, registry)["dynamic"][0]
        self.assertEqual(row["render"]["unicode_pattern"], "EEEE, dd' de 'MMMM' de 'yyyy")

    def test_unknown_directive_drops_render_and_local(self):
        logger = RecordingLogger()
        registry = {"a": {"provider": "datetime", "format": "%Q"}}
        row = build({}, registry, logger=logger)["dynamic"][0]
        self.assertFalse(row["local"])
        self.assertNotIn("render", row)
        self.assertTrue(any("%Q" in w for w in logger.warnings))

    def test_non_string_format_drops_render(self):
        row = build({}, {"a": {"provider": "datetime", "format": 5}})["dynamic"][0]
        self.assertFalse(row["local"])


class StrftimeConversionTests(unittest.TestCase):
    def test_every_directive_in_the_table(self):
        cases = {
            "%Y": "yyyy", "%y": "yy", "%m": "MM", "%d": "dd", "%H": "HH",
            "%I": "hh", "%M": "mm", "%S": "ss", "%j": "DDD", "%A": "EEEE",
            "%a": "EEE", "%B": "MMMM", "%b": "MMM", "%p": "a",
        }
        for fmt, expected in cases.items():
            with self.subTest(fmt=fmt):
                self.assertEqual(se.strftime_to_unicode_pattern(fmt), expected)

    def test_percent_literal(self):
        self.assertEqual(se.strftime_to_unicode_pattern("%d%%"), "dd%")

    def test_literal_run_with_letters_is_quoted_wholesale(self):
        # Leave 'às' unquoted and the 's' renders as seconds.
        self.assertEqual(
            se.strftime_to_unicode_pattern("%d/%m/%Y às %H:%M"),
            "dd/MM/yyyy' às 'HH:mm",
        )

    def test_letterless_literals_stay_bare(self):
        self.assertEqual(se.strftime_to_unicode_pattern("%d/%m/%Y"), "dd/MM/yyyy")
        self.assertEqual(se.strftime_to_unicode_pattern("%H:%M:%S"), "HH:mm:ss")

    def test_apostrophe_is_doubled(self):
        self.assertEqual(se.strftime_to_unicode_pattern("%H'%M"), "HH''mm")
        self.assertEqual(se.strftime_to_unicode_pattern("%d o'clock"), "dd' o''clock'")

    def test_name_based_user_override(self):
        self.assertEqual(
            se.strftime_to_unicode_pattern("%A, %d de %B"),
            # ", " holds no ASCII letter, so it stays bare — same as the extenso
            # pattern's own "EEEE, dd".
            "EEEE, dd' de 'MMMM",
        )

    def test_unknown_directive_returns_none(self):
        self.assertIsNone(se.strftime_to_unicode_pattern("%Q"))

    def test_trailing_lone_percent_returns_none(self):
        self.assertIsNone(se.strftime_to_unicode_pattern("%d%"))

    def test_non_string_returns_none(self):
        self.assertIsNone(se.strftime_to_unicode_pattern(None))


class WorkedExampleTests(unittest.TestCase):
    def test_matches_the_design_doc(self):
        static = {
            "xname": "Project Contributors",
            "xsaudacao": "Olá, aqui é %%xname%%.",
            "_cpf_numbers": {"fulano": "123.456.789-00"},
            "_custom_codes": {"__prefix__": "cod", "nf": "NF-4471"},
        }
        registry = {
            "xhj": {
                "provider": "datetime", "category": "datetime", "format": "%d/%m/%Y",
                "description": "Data de hoje (DD/MM/AAAA)",
            },
            "xdolar": {"provider": "bcb", "method": "dolar", "enabled": False},
        }
        bundle = build(static, registry, app_version="3.2.0")

        self.assertEqual(bundle["entries"], [
            {"trigger": "xname", "text": "Project Contributors", "kind": "text", "source": "static"},
            {"trigger": "xsaudacao", "text": "Olá, aqui é Project Contributors.", "kind": "text",
             "source": "static"},
            {"trigger": "cpffulano", "text": "123.456.789-00", "kind": "text", "source": "mapping",
             "group": {"container": "_cpf_numbers", "prefix": "cpf", "item": "fulano"}},
            {"trigger": "codnf", "text": "NF-4471", "kind": "text", "source": "mapping",
             "group": {"container": "_custom_codes", "prefix": "cod", "item": "nf"}},
        ])
        self.assertEqual(bundle["dynamic"], [
            {"id": "xhj", "trigger": "xhj", "provider": "datetime", "category": "datetime",
             "description": "Data de hoje (DD/MM/AAAA)", "enabled": True, "local": True,
             "render": {"kind": "date_format", "unicode_pattern": "dd/MM/yyyy", "locale": "pt-BR"}},
        ])


class DigestTests(unittest.TestCase):
    def test_excludes_exported_at_and_generator(self):
        static = {"xa": "A"}
        first = se.build_bundle(static, {}, app_version="1.0.0", now=FIXED_TIME)
        later = time.strptime("2027-01-01T00:00:00", "%Y-%m-%dT%H:%M:%S")
        second = se.build_bundle(static, {}, app_version="2.0.0", now=later)
        self.assertEqual(se.bundle_digest(first), se.bundle_digest(second))

    def test_content_change_changes_the_digest(self):
        a = se.build_bundle({"xa": "A"}, {}, now=FIXED_TIME)
        b = se.build_bundle({"xa": "B"}, {}, now=FIXED_TIME)
        self.assertNotEqual(se.bundle_digest(a), se.bundle_digest(b))

    def test_digest_bytes_are_reproducible(self):
        import hashlib

        bundle = se.build_bundle({"xa": "A"}, {}, now=FIXED_TIME)
        payload = dict(bundle)
        payload.pop("exported_at")
        payload.pop("generator")
        expected = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(se.bundle_digest(bundle), expected)


class ExportDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logger = RecordingLogger()

    def test_absent_value_is_silently_off(self):
        self.assertIsNone(se.resolve_export_dir(None, self.logger))
        self.assertIsNone(se.resolve_export_dir("", self.logger))
        self.assertEqual(self.logger.warnings, [])

    def test_relative_path_rejected(self):
        self.assertIsNone(se.resolve_export_dir("some/relative", self.logger))
        self.assertTrue(any("absoluto" in w for w in self.logger.warnings))

    def test_missing_directory_warns_and_is_not_created(self):
        missing = os.path.join(self.tmp.name, "nope")
        self.assertIsNone(se.resolve_export_dir(missing, self.logger))
        self.assertFalse(os.path.exists(missing))
        self.assertTrue(self.logger.warnings)

    def test_path_that_is_a_file_warns(self):
        target = os.path.join(self.tmp.name, "afile")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("x")
        self.assertIsNone(se.resolve_export_dir(target, self.logger))
        self.assertTrue(any("diretório" in w for w in self.logger.warnings))

    def test_existing_directory_accepted(self):
        self.assertEqual(se.resolve_export_dir(self.tmp.name, self.logger), self.tmp.name)


class ExportBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest_dir = os.path.join(self.tmp.name, "cloud")
        os.makedirs(self.dest_dir)
        self.state_path = os.path.join(self.tmp.name, "sync_export.state")
        self.bundle_path = os.path.join(self.dest_dir, "txt_xpander_bundle.json")
        self.logger = RecordingLogger()

    _DEFAULT_DIR = object()

    def export(self, static, registry=None, export_dir=_DEFAULT_DIR, **kwargs):
        return se.export_bundle(
            static,
            registry or {},
            self.dest_dir if export_dir is self._DEFAULT_DIR else export_dir,
            self.state_path,
            logger=self.logger,
            **kwargs,
        )

    def read_bundle(self):
        with open(self.bundle_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_writes_the_bundle_and_the_state_file(self):
        self.assertTrue(self.export({"xa": "A"}))
        self.assertEqual(triggers(self.read_bundle()), ["xa"])
        with open(self.state_path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
        self.assertEqual(state["path"], self.bundle_path)
        self.assertEqual(len(state["sha256"]), 64)

    def test_no_export_dir_means_no_side_effects(self):
        self.assertFalse(self.export({"xa": "A"}, export_dir=None))
        self.assertFalse(os.path.exists(self.bundle_path))
        self.assertFalse(os.path.exists(self.state_path))

    def test_second_identical_export_is_skipped(self):
        self.assertTrue(self.export({"xa": "A"}))
        mtime = os.path.getmtime(self.bundle_path)
        self.assertFalse(self.export({"xa": "A"}))
        self.assertEqual(os.path.getmtime(self.bundle_path), mtime)

    def test_changed_library_forces_a_rewrite(self):
        self.export({"xa": "A"})
        self.assertTrue(self.export({"xa": "B"}))
        self.assertEqual(self.read_bundle()["entries"][0]["text"], "B")

    def test_app_version_change_alone_forces_no_rewrite(self):
        self.assertTrue(self.export({"xa": "A"}, app_version="1.0.0"))
        self.assertFalse(self.export({"xa": "A"}, app_version="2.0.0"))
        self.assertEqual(self.read_bundle()["generator"]["version"], "1.0.0")

    def test_deleted_bundle_is_rewritten(self):
        self.export({"xa": "A"})
        os.remove(self.bundle_path)
        self.assertTrue(self.export({"xa": "A"}))
        self.assertTrue(os.path.exists(self.bundle_path))

    def test_repointed_export_dir_writes_to_the_new_location(self):
        other = os.path.join(self.tmp.name, "other")
        os.makedirs(other)
        self.export({"xa": "A"})
        self.assertTrue(self.export({"xa": "A"}, export_dir=other))
        self.assertTrue(os.path.exists(os.path.join(other, "txt_xpander_bundle.json")))

    def test_a_to_b_to_a_round_trip_rewrites_a(self):
        other = os.path.join(self.tmp.name, "other")
        os.makedirs(other)
        self.export({"xa": "A"})
        os.remove(self.bundle_path)  # simulate A going stale while pointed at B
        self.export({"xa": "A"}, export_dir=other)
        self.assertTrue(self.export({"xa": "A"}))
        self.assertTrue(os.path.exists(self.bundle_path))

    def test_missing_state_file_forces_an_export(self):
        self.export({"xa": "A"})
        os.remove(self.state_path)
        self.assertTrue(self.export({"xa": "A"}))

    def test_unreadable_state_file_forces_an_export(self):
        self.export({"xa": "A"})
        with open(self.state_path, "w", encoding="utf-8") as handle:
            handle.write("not json")
        self.assertTrue(self.export({"xa": "A"}))

    def test_unwritable_dir_warns_and_returns_false(self):
        missing = os.path.join(self.tmp.name, "gone")
        self.assertFalse(self.export({"xa": "A"}, export_dir=missing))
        self.assertTrue(self.logger.warnings)

    def test_write_failure_warns_and_never_raises(self):
        original = se.write_json_atomic

        def boom(path, data):
            if path.endswith("txt_xpander_bundle.json"):
                raise OSError("disk full")
            return original(path, data)

        se.write_json_atomic = boom
        self.addCleanup(lambda: setattr(se, "write_json_atomic", original))
        self.assertFalse(self.export({"xa": "A"}))
        self.assertTrue(any("disk full" in w for w in self.logger.warnings))

    def test_permission_error_is_retried_once(self):
        original = se.write_json_atomic
        calls = []

        def flaky(path, data):
            calls.append(path)
            if path.endswith("txt_xpander_bundle.json") and len(calls) == 1:
                raise PermissionError("locked by the cloud client")
            return original(path, data)

        se.write_json_atomic = flaky
        self.addCleanup(lambda: setattr(se, "write_json_atomic", original))
        original_delay = se.PERMISSION_RETRY_DELAY
        se.PERMISSION_RETRY_DELAY = 0
        self.addCleanup(lambda: setattr(se, "PERMISSION_RETRY_DELAY", original_delay))

        self.assertTrue(self.export({"xa": "A"}))
        self.assertTrue(os.path.exists(self.bundle_path))

    def test_atomic_write_leaves_no_temp_file(self):
        self.export({"xa": "A"})
        self.assertEqual(os.listdir(self.dest_dir), ["txt_xpander_bundle.json"])

    def test_mirror_dir_equal_to_export_dir_warns_but_still_exports(self):
        self.assertTrue(self.export({"xa": "A"}, mirror_dir=self.dest_dir))
        self.assertTrue(os.path.exists(self.bundle_path))
        self.assertTrue(any("mesmo diretório" in w for w in self.logger.warnings))

    def test_distinct_mirror_dir_does_not_warn(self):
        other = os.path.join(self.tmp.name, "mirror")
        os.makedirs(other)
        self.assertTrue(self.export({"xa": "A"}, mirror_dir=other))
        self.assertEqual(self.logger.warnings, [])

    def test_missing_mirror_dir_does_not_raise(self):
        self.assertTrue(self.export({"xa": "A"}, mirror_dir=os.path.join(self.tmp.name, "nope")))


class CallSiteTests(unittest.TestCase):
    """§1.10: all five paths that change the live library must export.

    Two of them (the registry writers) reassign ``self.dynamic_registry`` only
    after their write, which is why the wrapper re-reads both files from disk.
    """

    def setUp(self):
        from unittest import mock

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from app_module import txt_xpander as tx

        self.tx = tx
        self.mock = mock
        # The app keeps its log file open for the life of the process, so the
        # directory cannot be removed while the test run lasts.
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.base = self.tmp.name
        self.dest_dir = os.path.join(self.base, "cloud")
        os.makedirs(self.dest_dir)
        self.bundle_path = os.path.join(self.dest_dir, "txt_xpander_bundle.json")

        with open(os.path.join(self.base, "snippets.json"), "w", encoding="utf-8") as handle:
            json.dump({"xhi": "hello"}, handle)
        with open(os.path.join(self.base, "dynamic_snippets.json"), "w", encoding="utf-8") as handle:
            json.dump({"xhj": {"provider": "datetime", "format": "%d/%m/%Y"}}, handle)

        previous = os.environ.get("TXT_XPANDER_HOME")
        os.environ["TXT_XPANDER_HOME"] = self.base
        self.addCleanup(
            lambda: os.environ.pop("TXT_XPANDER_HOME", None)
            if previous is None
            else os.environ.__setitem__("TXT_XPANDER_HOME", previous)
        )
        with mock.patch.object(tx, "get_runtime_base_dir", return_value=self.base), \
                mock.patch.object(tx, "get_runtime_resource_dir", return_value=self.base):
            self.app = tx.TextExpander()

        self.app.settings["sync_export_dir"] = self.dest_dir
        self.app.notify_status = lambda *a, **k: None
        self.app.notify_error = lambda *a, **k: None

    def read_bundle(self):
        with open(self.bundle_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def dynamic_ids(self):
        return [row["id"] for row in self.read_bundle()["dynamic"]]

    def test_save_snippets_exports(self):
        self.assertTrue(self.app.save_snippets({"xhi": "changed"}))
        self.assertEqual(entry_for(self.read_bundle(), "xhi")["text"], "changed")

    def test_absent_key_means_no_bundle_at_all(self):
        self.app.settings.pop("sync_export_dir")
        self.assertTrue(self.app.save_snippets({"xhi": "changed"}))
        self.assertFalse(os.path.exists(self.bundle_path))

    def test_restore_backup_exports(self):
        backup = os.path.join(self.base, "old.json")
        with open(backup, "w", encoding="utf-8") as handle:
            json.dump({"xold": "restored"}, handle)
        ok, error = self.app.restore_backup(backup)
        self.assertTrue(ok, error)
        self.assertEqual(triggers(self.read_bundle()), ["xold"])

    def test_import_library_exports(self):
        source = os.path.join(self.base, "incoming.json")
        with open(source, "w", encoding="utf-8") as handle:
            json.dump({"ximported": "value"}, handle)
        ok, error = self.app.import_library(source, mode="replace")
        self.assertTrue(ok, error)
        self.assertEqual(triggers(self.read_bundle()), ["ximported"])

    def test_registry_toggle_reaches_the_bundle(self):
        self.app.save_snippets({"xhi": "hello"})
        self.assertEqual(self.dynamic_ids(), ["xhj"])
        self.app._toggle_registry_entry("xhj", False)
        self.assertEqual(self.dynamic_ids(), [])

    def test_registry_rename_reaches_the_bundle(self):
        self.app.save_snippets({"xhi": "hello"})
        self.app._rename_registry_entry("xhj", "data")
        row = self.read_bundle()["dynamic"][0]
        self.assertEqual(row["id"], "xhj")
        self.assertEqual(row["trigger"], "data")

    def test_export_reads_disk_not_self_snippets(self):
        # self.snippets can be stale (restore/import write before reloading) and
        # holds bound callables; the bundle must reflect the file.
        self.app.snippets = {"xstale": "never exported"}
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            json.dump({"xdisk": "from disk"}, handle)
        self.app.export_sync_bundle()
        self.assertEqual(triggers(self.read_bundle()), ["xdisk"])

    def test_invalid_snippets_file_warns_without_raising(self):
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write("[]")
        self.app.export_sync_bundle()  # must not raise
        self.assertFalse(os.path.exists(self.bundle_path))

    def test_generator_version_comes_from_the_module_docstring(self):
        self.app.save_snippets({"xhi": "hello"})
        self.assertEqual(self.read_bundle()["generator"]["version"], self.tx.APP_VERSION)
        self.assertIsNotNone(self.tx.APP_VERSION)


if __name__ == "__main__":
    unittest.main()
