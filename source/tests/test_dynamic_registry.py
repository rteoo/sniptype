import json
import os
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
