import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import dynamic_registry as dr


class FakeBCB:
    def get_dolar(self):
        return "dolar-value"


class FakeStock:
    def get_cotacao_atual(self, ticker):
        return f"cotacao-{ticker}"


class FakeContext:
    """Minimal duck-typed context for the provider binders."""
    def __init__(self):
        self.bcb = FakeBCB()
        self.b3_consultor = FakeStock()
        self._ticker = "PETR4"

    def data_extenso(self):
        return "segunda-feira"

    def ask_ticker_input(self, label):
        return self._ticker

    def run_whatsapp_action(self, trigger):
        return f"wa-{trigger}"


class LoadRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bundled = os.path.join(self.tmp, "dynamic_snippets.json")
        with open(self.bundled, "w", encoding="utf-8") as handle:
            json.dump({"xhj": {"provider": "datetime", "format": "%d/%m/%Y"}}, handle)

    def test_user_override_merges_on_top(self):
        user = os.path.join(self.tmp, "user.json")
        with open(user, "w", encoding="utf-8") as handle:
            json.dump({"xhj": {"provider": "datetime", "format": "%Y", "enabled": False}}, handle)
        registry = dr.load_registry(self.bundled, user)
        self.assertFalse(registry["xhj"]["enabled"])
        self.assertEqual(registry["xhj"]["format"], "%Y")

    def test_thin_override_preserves_bundled_fields(self):
        # A minimal {"enabled": false} override must not freeze the other fields:
        # the bundled 'format' must still come through.
        user = os.path.join(self.tmp, "user.json")
        with open(user, "w", encoding="utf-8") as handle:
            json.dump({"xhj": {"enabled": False}}, handle)
        registry = dr.load_registry(self.bundled, user)
        self.assertFalse(registry["xhj"]["enabled"])
        self.assertEqual(registry["xhj"]["format"], "%d/%m/%Y")  # from bundled
        self.assertEqual(registry["xhj"]["provider"], "datetime")

    def test_thin_trigger_override_renames_without_losing_fields(self):
        user = os.path.join(self.tmp, "user.json")
        with open(user, "w", encoding="utf-8") as handle:
            json.dump({"xhj": {"trigger": "xdata"}}, handle)
        registry = dr.load_registry(self.bundled, user)
        self.assertEqual(dr.effective_trigger("xhj", registry["xhj"]), "xdata")
        self.assertEqual(registry["xhj"]["format"], "%d/%m/%Y")  # from bundled

    def test_missing_user_file_returns_bundled(self):
        registry = dr.load_registry(self.bundled, os.path.join(self.tmp, "nope.json"))
        self.assertIn("xhj", registry)

    def test_invalid_bundled_returns_empty(self):
        with open(self.bundled, "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        self.assertEqual(dr.load_registry(self.bundled), {})


class BuildDynamicSnippetsTests(unittest.TestCase):
    def setUp(self):
        self.ctx = FakeContext()

    def test_binds_each_provider(self):
        registry = {
            "xhj": {"provider": "datetime", "format": "%Y"},
            "xhoje": {"provider": "datetime", "method": "extenso"},
            "xdolar": {"provider": "bcb", "method": "dolar", "slow": True},
            "xcot": {"provider": "stock", "method": "cotacao", "dialog": "Cotação", "slow": True},
            "xwapp": {"provider": "whatsapp", "mode": "open", "slow": True},
        }
        snippets, slow = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertEqual(snippets["xhoje"](), "segunda-feira")
        self.assertEqual(snippets["xdolar"](), "dolar-value")
        self.assertEqual(snippets["xcot"](), "cotacao-PETR4")
        self.assertEqual(snippets["xwapp"](), "wa-xwapp")
        self.assertTrue(callable(snippets["xhj"]))
        self.assertEqual(slow, {"xdolar", "xcot", "xwapp"})

    def test_whatsapp_dispatches_by_mode_after_rename(self):
        # Renaming the trigger key must still dispatch to the canonical action.
        calls = []
        self.ctx.run_whatsapp_action = lambda t: calls.append(t) or f"wa-{t}"
        registry = {"xzap": {"provider": "whatsapp", "mode": "open"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertEqual(snippets["xzap"](), "wa-xwapp")
        self.assertEqual(calls, ["xwapp"])

    def test_whatsapp_unknown_mode_is_skipped(self):
        registry = {"xbad": {"provider": "whatsapp", "mode": "nope"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertEqual(snippets, {})

    def test_disabled_entry_is_skipped(self):
        registry = {"xhj": {"provider": "datetime", "format": "%Y", "enabled": False}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertNotIn("xhj", snippets)

    def test_unknown_provider_is_skipped(self):
        registry = {"xbad": {"provider": "nope"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertEqual(snippets, {})

    def test_unknown_method_is_skipped(self):
        registry = {"xbad": {"provider": "bcb", "method": "does_not_exist"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertEqual(snippets, {})

    def test_trigger_field_renames_binding(self):
        registry = {"xhj": {"provider": "datetime", "format": "%Y", "trigger": "xdata"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertIn("xdata", snippets)
        self.assertNotIn("xhj", snippets)

    def test_trigger_field_renames_slow_set(self):
        registry = {"xdolar": {"provider": "bcb", "method": "dolar", "slow": True,
                               "trigger": "xusd"}}
        snippets, slow = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertEqual(snippets["xusd"](), "dolar-value")
        self.assertEqual(slow, {"xusd"})

    def test_duplicate_effective_trigger_keeps_first(self):
        registry = {
            "xhj": {"provider": "datetime", "format": "%Y"},
            "xnow": {"provider": "datetime", "method": "extenso", "trigger": "xhj"},
        }
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertEqual(len(snippets), 1)
        self.assertNotEqual(snippets["xhj"](), "segunda-feira")  # first entry won

    def test_stock_cancel_returns_marker(self):
        self.ctx._ticker = None
        registry = {"xcot": {"provider": "stock", "method": "cotacao", "dialog": "Cotação"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertEqual(snippets["xcot"](), "[Cancelado]")


class ReferenceEntriesTests(unittest.TestCase):
    def test_groups_by_category_preserving_order(self):
        registry = {
            "xhj": {"provider": "datetime", "category": "datetime", "description": "d1"},
            "xnow": {"provider": "datetime", "category": "datetime", "description": "d2"},
            "xdolar": {"provider": "bcb", "category": "economy", "description": "e1", "enabled": False},
        }
        grouped = dr.reference_entries_by_category(registry)
        self.assertEqual(
            grouped["datetime"],
            [("xhj", "xhj", "d1", True), ("xnow", "xnow", "d2", True)],
        )
        self.assertEqual(grouped["economy"], [("xdolar", "xdolar", "e1", False)])

    def test_renamed_entry_reports_key_and_effective_trigger(self):
        registry = {"xhj": {"provider": "datetime", "category": "datetime",
                            "description": "d1", "trigger": "xdata"}}
        grouped = dr.reference_entries_by_category(registry)
        self.assertEqual(grouped["datetime"], [("xhj", "xdata", "d1", True)])


class EffectiveTriggerTests(unittest.TestCase):
    def test_defaults_to_key(self):
        self.assertEqual(dr.effective_trigger("xhj", {"provider": "datetime"}), "xhj")

    def test_uses_trigger_field(self):
        self.assertEqual(dr.effective_trigger("xhj", {"trigger": "xdata"}), "xdata")

    def test_blank_trigger_falls_back_to_key(self):
        self.assertEqual(dr.effective_trigger("xhj", {"trigger": "   "}), "xhj")
        self.assertEqual(dr.effective_trigger("xhj", {"trigger": None}), "xhj")

    def test_trigger_is_stripped(self):
        self.assertEqual(dr.effective_trigger("xhj", {"trigger": " xdata "}), "xdata")


class DatetimeRenderSpecTests(unittest.TestCase):
    def test_default_format(self):
        self.assertEqual(dr.DEFAULT_DATE_FORMAT, "%d/%m/%Y")
        self.assertEqual(dr.datetime_render_spec({}), ("format", dr.DEFAULT_DATE_FORMAT))
        self.assertEqual(
            dr.datetime_render_spec({"provider": "datetime"}),
            ("format", dr.DEFAULT_DATE_FORMAT),
        )

    def test_explicit_format(self):
        self.assertEqual(dr.datetime_render_spec({"format": "%Y"}), ("format", "%Y"))

    def test_extenso_wins_over_format(self):
        self.assertEqual(dr.datetime_render_spec({"method": "extenso"}), ("extenso", None))
        self.assertEqual(
            dr.datetime_render_spec({"method": "extenso", "format": "%d"}),
            ("extenso", None),
        )

    def test_provider_consumes_the_spec_default(self):
        # The desktop datetime provider's default format is the shared spec's.
        snippets, _ = dr.build_dynamic_snippets({"x": {"provider": "datetime"}}, FakeContext())
        self.assertRegex(snippets["x"](), r"^\d{2}/\d{2}/\d{4}$")


class ValidateRenameTests(unittest.TestCase):
    def setUp(self):
        self.registry = {
            "xhj": {"provider": "datetime"},
            "xdolar": {"provider": "bcb", "method": "dolar"},
        }
        self.snippets = {
            "email": "a@b.com",
            "_cpf_numbers": {"fulano": "123"},
            "xhj": lambda: "hoje",
        }

    def _errors(self, new_trigger):
        return dr.validate_rename(self.registry, "xhj", new_trigger, self.snippets)[0]

    def test_valid_rename_has_no_errors(self):
        errors, _ = dr.validate_rename(self.registry, "xhj", "xdata", self.snippets)
        self.assertEqual(errors, [])

    def test_empty_is_rejected(self):
        self.assertTrue(self._errors("   "))

    def test_whitespace_is_rejected(self):
        self.assertTrue(self._errors("x data"))

    def test_collision_with_other_dynamic_is_rejected(self):
        self.assertTrue(self._errors("xdolar"))

    def test_collision_with_static_snippet_is_rejected(self):
        self.assertTrue(self._errors("email"))

    def test_collision_with_mapping_prefix_is_rejected(self):
        self.assertTrue(self._errors("cpf"))

    def test_collision_with_composed_mapping_trigger_is_rejected(self):
        self.assertTrue(self._errors("cpffulano"))

    def test_renaming_to_own_current_trigger_is_allowed(self):
        self.assertEqual(self._errors("xhj"), [])

    def test_mapping_prefix_start_is_only_a_warning(self):
        errors, warnings = dr.validate_rename(self.registry, "xhj", "cpfdata", self.snippets)
        self.assertEqual(errors, [])
        self.assertTrue(any("prefixo de mapeamento" in w for w in warnings))


class RealContext:
    """Context backed by the real consultors so eager binds (bcb) succeed."""
    def __init__(self):
        from bcb_consultor import BCBConsultor
        from yf_stocks import B3FundamentosConsultor
        self.bcb = BCBConsultor()
        self.b3_consultor = B3FundamentosConsultor()

    def data_extenso(self):
        return ""

    def ask_ticker_input(self, label):
        return None

    def run_whatsapp_action(self, trigger):
        return ""


def _bundled_path():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dynamic_snippets.json"))


class BundledRegistryTests(unittest.TestCase):
    def test_bundled_methods_exist_on_real_consultors(self):
        registry = dr.load_registry(_bundled_path())
        ctx = RealContext()
        for trigger, entry in registry.items():
            provider = entry["provider"]
            if provider == "bcb":
                attr = dr.BCB_METHODS.get(entry.get("method"))
                self.assertIsNotNone(attr, f"unmapped bcb method for {trigger}")
                self.assertTrue(hasattr(ctx.bcb, attr), f"{trigger} -> {attr}")
            elif provider == "stock":
                attr = dr.STOCK_METHODS.get(entry.get("method"))
                self.assertIsNotNone(attr, f"unmapped stock method for {trigger}")
                self.assertTrue(hasattr(ctx.b3_consultor, attr), f"{trigger} -> {attr}")

    def test_bundled_file_binds_cleanly(self):
        registry = dr.load_registry(_bundled_path())
        snippets, slow = dr.build_dynamic_snippets(registry, RealContext())
        # Every registry trigger should bind (no typo'd provider/method names).
        self.assertEqual(set(registry.keys()), set(snippets.keys()))
        self.assertIn("xdolar", snippets)
        self.assertIn("xcot", slow)


# --------------------------------------------------------------------------- #
# Adversarial: load_registry robustness
# --------------------------------------------------------------------------- #
class LoadRegistryAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bundled = os.path.join(self.tmp, "dynamic_snippets.json")
        with open(self.bundled, "w", encoding="utf-8") as handle:
            json.dump({"xhj": {"provider": "datetime", "format": "%d/%m/%Y"}}, handle)

    def _write_user(self, raw):
        path = os.path.join(self.tmp, "user.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(raw)
        return path

    def test_bundled_root_list_returns_empty(self):
        with open(self.bundled, "w", encoding="utf-8") as handle:
            json.dump([1, 2, 3], handle)
        self.assertEqual(dr.load_registry(self.bundled), {})

    def test_bundled_root_scalar_returns_empty(self):
        with open(self.bundled, "w", encoding="utf-8") as handle:
            handle.write("42")
        self.assertEqual(dr.load_registry(self.bundled), {})

    def test_user_root_list_is_ignored(self):
        user = self._write_user("[1, 2, 3]")
        registry = dr.load_registry(self.bundled, user)
        self.assertIn("xhj", registry)
        self.assertEqual(registry["xhj"]["format"], "%d/%m/%Y")

    def test_empty_user_dict_leaves_bundled(self):
        user = self._write_user("{}")
        registry = dr.load_registry(self.bundled, user)
        self.assertEqual(registry["xhj"]["format"], "%d/%m/%Y")

    def test_malformed_user_json_returns_bundled_and_warns(self):
        user = self._write_user("{ not json")
        logger = MagicMock()
        registry = dr.load_registry(self.bundled, user, logger=logger)
        self.assertIn("xhj", registry)
        logger.warning.assert_called_once()

    def test_user_adds_new_trigger(self):
        user = self._write_user(json.dumps({"xnew": {"provider": "datetime", "format": "%H"}}))
        registry = dr.load_registry(self.bundled, user)
        self.assertIn("xnew", registry)
        self.assertIn("xhj", registry)

    def test_user_nondict_entry_keeps_bundled_entry(self):
        # REGRESSION: a single malformed override entry (non-dict) used to
        # replace the good bundled entry wholesale, silently dropping the
        # trigger. It must be ignored -- the per-entry version of the
        # "one bad layer never wipes the other" guarantee.
        user = self._write_user(json.dumps({"xhj": "garbage"}))
        registry = dr.load_registry(self.bundled, user)
        self.assertEqual(registry["xhj"], {"provider": "datetime", "format": "%d/%m/%Y"})
        snippets, _ = dr.build_dynamic_snippets(registry, FakeContext())
        self.assertIn("xhj", snippets)

    def test_bundled_nondict_entry_survives_load_then_skipped_by_build(self):
        with open(self.bundled, "w", encoding="utf-8") as handle:
            json.dump(
                {"xhj": "notadict", "xok": {"provider": "datetime", "format": "%Y"}},
                handle,
            )
        registry = dr.load_registry(self.bundled)
        self.assertEqual(registry["xhj"], "notadict")
        snippets, _ = dr.build_dynamic_snippets(registry, FakeContext())
        self.assertNotIn("xhj", snippets)
        self.assertIn("xok", snippets)


# --------------------------------------------------------------------------- #
# Adversarial: effective_trigger edge inputs
# --------------------------------------------------------------------------- #
class EffectiveTriggerAdversarialTests(unittest.TestCase):
    def test_non_string_trigger_falls_back_to_key(self):
        self.assertEqual(dr.effective_trigger("xhj", {"trigger": 5}), "xhj")
        self.assertEqual(dr.effective_trigger("xhj", {"trigger": ["x"]}), "xhj")

    def test_entry_not_a_dict_returns_key(self):
        self.assertEqual(dr.effective_trigger("xhj", "notadict"), "xhj")
        self.assertEqual(dr.effective_trigger("xhj", None), "xhj")

    def test_tab_newline_trigger_falls_back(self):
        self.assertEqual(dr.effective_trigger("xhj", {"trigger": "\t\n"}), "xhj")


# --------------------------------------------------------------------------- #
# Adversarial: build_dynamic_snippets
# --------------------------------------------------------------------------- #
class BuildDynamicAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.ctx = FakeContext()

    def test_two_entries_renamed_to_same_trigger_first_wins(self):
        logger = MagicMock()
        registry = {
            "a": {"provider": "datetime", "format": "%Y", "trigger": "xsame"},
            "b": {"provider": "datetime", "method": "extenso", "trigger": "xsame"},
        }
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx, logger=logger)
        self.assertEqual(list(snippets.keys()), ["xsame"])
        # The first entry (a format lambda) won; not the extenso method.
        self.assertNotEqual(snippets["xsame"](), "segunda-feira")
        logger.warning.assert_called_once()
        self.assertIn("xsame", logger.warning.call_args[0][0])

    def test_non_dict_entry_is_skipped(self):
        snippets, _ = dr.build_dynamic_snippets({"x": "notadict"}, self.ctx)
        self.assertEqual(snippets, {})

    def test_datetime_unknown_method_falls_back_to_format(self):
        # Unlike bcb/stock, datetime never returns None: any method other than
        # 'extenso' is ignored and the format branch is used.
        registry = {"x": {"provider": "datetime", "method": "bogus", "format": "%Y"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertIn("x", snippets)
        self.assertTrue(snippets["x"]().isdigit())

    def test_datetime_default_format_when_absent(self):
        registry = {"x": {"provider": "datetime"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertRegex(snippets["x"](), r"^\d{2}/\d{2}/\d{4}$")

    def test_unknown_provider_logs_warning(self):
        logger = MagicMock()
        snippets, _ = dr.build_dynamic_snippets({"xbad": {"provider": "nope"}}, self.ctx, logger=logger)
        self.assertEqual(snippets, {})
        logger.warning.assert_called_once()
        self.assertIn("nope", logger.warning.call_args[0][0])

    def test_unknown_method_logs_warning(self):
        logger = MagicMock()
        registry = {"xbad": {"provider": "bcb", "method": "does_not_exist"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx, logger=logger)
        self.assertEqual(snippets, {})
        logger.warning.assert_called_once()
        self.assertIn("xbad", logger.warning.call_args[0][0])

    def test_bcb_bind_does_not_invoke_the_method(self):
        class CountingBCB:
            def __init__(self):
                self.calls = 0

            def get_dolar(self):
                self.calls += 1
                return "dolar-value"

        self.ctx.bcb = CountingBCB()
        registry = {"xdolar": {"provider": "bcb", "method": "dolar"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertEqual(self.ctx.bcb.calls, 0)  # binding must not fetch
        self.assertEqual(snippets["xdolar"](), "dolar-value")
        self.assertEqual(self.ctx.bcb.calls, 1)

    def test_stock_bind_does_not_open_dialog(self):
        called = []
        self.ctx.ask_ticker_input = lambda label: called.append(label) or "PETR4"
        registry = {"xcot": {"provider": "stock", "method": "cotacao", "dialog": "Cotação"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertEqual(called, [])  # no dialog at bind time
        self.assertEqual(snippets["xcot"](), "cotacao-PETR4")
        self.assertEqual(called, ["Cotação"])

    def test_string_enabled_false_still_binds(self):
        # Footgun characterization: is_enabled uses bool(), so the JSON string
        # "false" is truthy and does NOT disable the entry. Only a real boolean
        # false (or 0/empty) disables it.
        registry = {"x": {"provider": "datetime", "format": "%Y", "enabled": "false"}}
        snippets, _ = dr.build_dynamic_snippets(registry, self.ctx)
        self.assertIn("x", snippets)


# --------------------------------------------------------------------------- #
# Adversarial: reference_entries_by_category
# --------------------------------------------------------------------------- #
class ReferenceEntriesAdversarialTests(unittest.TestCase):
    def test_non_dict_entry_is_skipped(self):
        registry = {
            "junk": "notadict",
            "y": {"provider": "datetime", "category": "datetime", "description": "d"},
        }
        grouped = dr.reference_entries_by_category(registry)
        self.assertEqual(grouped, {"datetime": [("y", "y", "d", True)]})

    def test_category_defaults_to_provider(self):
        registry = {"y": {"provider": "bcb", "description": "d"}}
        grouped = dr.reference_entries_by_category(registry)
        self.assertEqual(grouped, {"bcb": [("y", "y", "d", True)]})

    def test_category_defaults_to_other_without_provider(self):
        registry = {"y": {"description": "d"}}
        grouped = dr.reference_entries_by_category(registry)
        self.assertEqual(grouped, {"other": [("y", "y", "d", True)]})


# --------------------------------------------------------------------------- #
# Adversarial: validate_rename
# --------------------------------------------------------------------------- #
class ValidateRenameAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.registry = {
            "xhj": {"provider": "datetime"},
            "xdolar": {"provider": "bcb", "method": "dolar"},
        }
        self.snippets = {
            "email": "a@b.com",
            "relatorio": {"__kind__": "rich_text", "text": "R"},
            "_cpf_numbers": {"fulano": "123"},
        }

    def _errors(self, new_trigger):
        return dr.validate_rename(self.registry, "xhj", new_trigger, self.snippets)[0]

    def test_none_trigger_rejected_without_crash(self):
        errors = self._errors(None)
        self.assertTrue(errors)
        self.assertIn("vazio", errors[0])

    def test_non_string_trigger_rejected(self):
        self.assertTrue(self._errors(5))

    def test_tab_only_trigger_rejected(self):
        self.assertTrue(self._errors("\t\t"))

    def test_padded_trigger_is_stripped_then_collision_detected(self):
        # " xdolar " strips to "xdolar", which collides with the other dynamic.
        errors = self._errors(" xdolar ")
        self.assertTrue(any("din" in e for e in errors))

    def test_collision_with_rich_text_static_is_rejected(self):
        # A rich-text dict snippet still counts as a static trigger name.
        errors = self._errors("relatorio")
        self.assertTrue(any("est" in e.lower() for e in errors))


# --------------------------------------------------------------------------- #
# Adversarial: composed_mapping_triggers
# --------------------------------------------------------------------------- #
class ComposedMappingTriggersTests(unittest.TestCase):
    def test_builtin_cpf_prefix_composes_items(self):
        composed = dr.composed_mapping_triggers(
            {"_cpf_numbers": {"fulano": "1", "ciclano": "2"}}
        )
        self.assertEqual(composed, {"cpffulano", "cpfciclano"})

    def test_custom_codes_prefix_excludes_reserved_key(self):
        composed = dr.composed_mapping_triggers(
            {"_custom_codes": {"__prefix__": "cc", "a": "1", "b": "2"}}
        )
        self.assertEqual(composed, {"cca", "ccb"})


# --------------------------------------------------------------------------- #
# Adversarial: is_enabled
# --------------------------------------------------------------------------- #
class IsEnabledTests(unittest.TestCase):
    def test_default_true(self):
        self.assertTrue(dr.is_enabled({}))

    def test_explicit_false(self):
        self.assertFalse(dr.is_enabled({"enabled": False}))

    def test_zero_is_false(self):
        self.assertFalse(dr.is_enabled({"enabled": 0}))

    def test_empty_string_is_false(self):
        self.assertFalse(dr.is_enabled({"enabled": ""}))

    def test_nonempty_string_false_is_truthy(self):
        # Footgun: the string "false" is truthy under bool().
        self.assertTrue(dr.is_enabled({"enabled": "false"}))


if __name__ == "__main__":
    unittest.main()
