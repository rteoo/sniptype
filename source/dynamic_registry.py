"""Data-driven registry for runtime dynamic snippets.

The callables (date formatting, BCB fetches, stock lookups, WhatsApp flows) stay
in Python, but everything *about* each dynamic trigger — its name, provider,
provider parameters, slow flag, description, category and enabled state — lives in
``dynamic_snippets.json`` (bundled) and an optional per-user override in the data
directory. Providers register by name; an unknown provider is logged and skipped
so a bad entry never crashes startup.
"""

import time

from snippet_utils import load_json_file


# registry 'method' -> BCBConsultor attribute
BCB_METHODS = {
    "dolar": "get_dolar",
    "selic": "get_selic_meta",
    "ipcam": "get_ipca_mensal",
    "ipca12": "get_ipca_12m",
    "cdi": "get_cdi",
    "ptax": "get_ptax_sgs",
    "economia": "get_resumo_economico",
}

# registry 'method' -> B3FundamentosConsultor attribute
STOCK_METHODS = {
    "cotacao": "get_cotacao_atual",
    "preco_lucro": "get_preco_lucro",
    "market_cap": "get_market_cap",
    "preco_vp": "get_preco_vp",
    "dividend_yield": "get_dividend_yield",
    "ebitda": "get_ebitda",
    "margem_liquida": "get_margem_liquida",
    "roe": "get_roe",
    "divida_total": "get_divida_total",
    "divida_liquida": "get_divida_liquida",
    "caixa": "get_caixa",
    "volume_medio": "get_volume_medio",
    "receita_liquida": "get_receita_liquida",
    "beta": "get_beta",
    "high_low_52w": "get_52week_high_low",
    "resumo_fundamentos": "get_resumo_fundamentos",
}

CATEGORY_ORDER = ("datetime", "economy", "stock", "whatsapp")

# registry 'mode' -> canonical WhatsApp trigger understood by execute_whatsapp_action.
# Dispatching by mode (not the entry's key) lets a user rename the trigger safely.
WHATSAPP_MODES = {
    "open": "xwapp",
    "insert": "xlwapp",
    "prompt": "xpwapp",
}


def load_registry(bundled_path, user_path=None, logger=None):
    """Load the bundled registry and overlay an optional user override.

    The overlay is per-field within each trigger, so a thin user override (e.g.
    just ``{"enabled": false}``) changes only that field and future bundled edits
    to other fields still reach the user. A missing/invalid file yields an empty
    layer so one bad file never wipes the other.
    """
    bundled = _safe_load(bundled_path, logger, "registro dinâmico")
    if not user_path:
        return dict(bundled)
    user = _safe_load(user_path, logger, "registro dinâmico do usuário")

    merged = {trigger: dict(entry) if isinstance(entry, dict) else entry for trigger, entry in bundled.items()}
    for trigger, entry in user.items():
        if isinstance(entry, dict) and isinstance(merged.get(trigger), dict):
            merged[trigger] = {**merged[trigger], **entry}
        else:
            merged[trigger] = entry
    return merged


def _safe_load(path, logger, label):
    if not path:
        return {}
    try:
        data = load_json_file(path)
    except FileNotFoundError:
        return {}
    except Exception as e:
        if logger:
            logger.warning(f"Falha ao ler {label} ({path}): {e}")
        return {}
    return data if isinstance(data, dict) else {}


def _datetime_provider(trigger, entry, context):
    if entry.get("method") == "extenso":
        return context.data_extenso
    fmt = entry.get("format", "%d/%m/%Y")
    return lambda fmt=fmt: time.strftime(fmt)


def _bcb_provider(trigger, entry, context):
    attr = BCB_METHODS.get(entry.get("method"))
    if attr is None:
        return None
    return getattr(context.bcb, attr)


def _stock_provider(trigger, entry, context):
    attr = STOCK_METHODS.get(entry.get("method"))
    if attr is None:
        return None
    label = entry.get("dialog", entry.get("description", trigger))

    def run_stock():
        ticker = context.ask_ticker_input(label)
        if not ticker:
            return "[Cancelado]"
        return getattr(context.b3_consultor, attr)(ticker)

    return run_stock


def _whatsapp_provider(trigger, entry, context):
    # Dispatch by mode, not the (possibly renamed) trigger key, so renaming the
    # registry entry keeps working.
    canonical = WHATSAPP_MODES.get(entry.get("mode"))
    if canonical is None:
        return None

    def run_whatsapp():
        return context.run_whatsapp_action(canonical)

    return run_whatsapp


PROVIDERS = {
    "datetime": _datetime_provider,
    "bcb": _bcb_provider,
    "stock": _stock_provider,
    "whatsapp": _whatsapp_provider,
}


def is_enabled(entry):
    return bool(entry.get("enabled", True))


def build_dynamic_snippets(registry, context, logger=None):
    """Bind enabled registry entries to provider callables.

    Returns (snippets, slow_triggers): a dict of trigger -> callable and the set
    of triggers flagged ``slow``. Disabled entries are skipped; unknown providers
    and unknown methods are logged and skipped.
    """
    snippets = {}
    slow_triggers = set()

    for trigger, entry in registry.items():
        if not isinstance(entry, dict) or not is_enabled(entry):
            continue
        provider_name = entry.get("provider")
        factory = PROVIDERS.get(provider_name)
        if factory is None:
            if logger:
                logger.warning(f"Provider desconhecido '{provider_name}' para '{trigger}'; ignorado.")
            continue
        callable_snippet = factory(trigger, entry, context)
        if callable_snippet is None:
            if logger:
                logger.warning(f"Método inválido em '{trigger}' (provider {provider_name}); ignorado.")
            continue
        snippets[trigger] = callable_snippet
        if entry.get("slow"):
            slow_triggers.add(trigger)

    return snippets, slow_triggers


def reference_entries_by_category(registry):
    """Return {category: [(trigger, description, enabled), ...]} for the GUI tabs.

    Preserves registry (insertion) order within each category so the reference
    tabs always match the registered triggers instead of a hand-maintained list.
    """
    grouped = {}
    for trigger, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        category = entry.get("category", entry.get("provider", "other"))
        grouped.setdefault(category, []).append(
            (trigger, entry.get("description", ""), is_enabled(entry))
        )
    return grouped
