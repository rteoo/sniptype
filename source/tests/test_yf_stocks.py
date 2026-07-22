"""Adversarial tests for the yfinance fundamentals wrapper.

yfinance is never imported for real: ``_get_ticker_object`` is patched to hand
back a fake ticker whose ``.info`` dict is fully controlled, so no network call
happens. One test injects a fake ``yfinance`` module to exercise the real lazy
import failure path. Cache expiry uses a controlled clock (``yf_stocks.datetime``).
"""

import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

import yf_stocks
from yf_stocks import B3FundamentosConsultor


class FakeTicker:
    """Stand-in for a yfinance ``Ticker`` object exposing only ``.info``."""

    def __init__(self, info):
        self.info = info


class _FrozenClock:
    """Drop-in for ``yf_stocks.datetime`` with a controllable ``now()``."""

    def __init__(self, start):
        self.value = start

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value = self.value + timedelta(seconds=seconds)


def _patch_ticker(info):
    return mock.patch.object(
        B3FundamentosConsultor, "_get_ticker_object", return_value=FakeTicker(info)
    )


class FormatTickerTests(unittest.TestCase):
    def setUp(self):
        self.c = B3FundamentosConsultor()

    def test_brazilian_ticker_gets_sa_suffix(self):
        self.assertEqual("PETR4.SA", self.c._format_ticker("petr4"))

    def test_whitespace_is_trimmed_and_uppercased(self):
        self.assertEqual("AAPL", self.c._format_ticker("  aapl "))

    def test_existing_sa_suffix_is_preserved(self):
        self.assertEqual("PETR4.SA", self.c._format_ticker("PETR4.SA"))

    def test_lowercase_sa_suffix_is_normalized_not_doubled(self):
        self.assertEqual("PETR4.SA", self.c._format_ticker("petr4.sa"))

    def test_us_ticker_without_digits_is_left_alone(self):
        self.assertEqual("AAPL", self.c._format_ticker("aapl"))

    def test_us_ticker_with_dot_but_no_digit_is_left_alone(self):
        self.assertEqual("BRK.B", self.c._format_ticker("brk.b"))


class FormatNumberTests(unittest.TestCase):
    def setUp(self):
        self.c = B3FundamentosConsultor()

    def test_brl_uses_comma_separator(self):
        self.assertEqual("13,75", self.c._format_number(13.75, 2, "BRL"))

    def test_usd_keeps_dot_separator(self):
        self.assertEqual("13.75", self.c._format_number(13.75, 2, "USD"))

    def test_negative_value_keeps_sign(self):
        self.assertEqual("-5,50", self.c._format_number(-5.5, 2, "BRL"))

    def test_zero_decimals(self):
        self.assertEqual("100", self.c._format_number(100, 0, "BRL"))

    def test_none_returns_na(self):
        self.assertEqual("N/A", self.c._format_number(None))

    def test_literal_na_returns_na(self):
        self.assertEqual("N/A", self.c._format_number("N/A"))

    def test_unformattable_value_returns_na(self):
        self.assertEqual("N/A", self.c._format_number("abc"))


class FormatCurrencyTests(unittest.TestCase):
    def setUp(self):
        self.c = B3FundamentosConsultor()

    def test_billions_scale_brl(self):
        self.assertEqual("R$ 421,5 B", self.c._format_currency(421_500_000_000))

    def test_billions_scale_usd_via_ticker_info(self):
        self.assertEqual(
            "$ 421.5 B",
            self.c._format_currency(421_500_000_000, {"currency": "USD"}),
        )

    def test_millions_scale_brl(self):
        self.assertEqual("R$ 1,5 M", self.c._format_currency(1_500_000))

    def test_thousands_use_brazilian_grouping(self):
        self.assertEqual("R$ 5.000,0", self.c._format_currency(5000))

    def test_negative_billions(self):
        self.assertEqual("R$ -2,0 B", self.c._format_currency(-2_000_000_000))

    def test_zero_is_formatted_not_dropped(self):
        self.assertEqual("R$ 0,0", self.c._format_currency(0))

    def test_none_and_na_return_na(self):
        self.assertEqual("N/A", self.c._format_currency(None))
        self.assertEqual("N/A", self.c._format_currency("N/A"))


class SafeGetTests(unittest.TestCase):
    def setUp(self):
        self.c = B3FundamentosConsultor()

    def test_returns_present_value(self):
        self.assertEqual(1, self.c._safe_get({"a": 1}, "a"))

    def test_missing_key_returns_default(self):
        self.assertEqual("def", self.c._safe_get({"a": 1}, "b", "def"))

    def test_none_value_returns_default(self):
        self.assertEqual("def", self.c._safe_get({"a": None}, "a", "def"))

    def test_nan_value_returns_default(self):
        self.assertEqual("def", self.c._safe_get({"a": float("nan")}, "a", "def"))

    def test_zero_is_a_real_value(self):
        self.assertEqual(0, self.c._safe_get({"a": 0}, "a", "def"))

    def test_non_mapping_input_returns_default(self):
        self.assertEqual("def", self.c._safe_get("not-a-dict", "a", "def"))


class QuoteAndMetricTests(unittest.TestCase):
    def test_cotacao_brl(self):
        with _patch_ticker({"currentPrice": 31.45, "currency": "BRL"}):
            self.assertEqual(
                "Cotação PETR4: R$ 31,45",
                B3FundamentosConsultor().get_cotacao_atual("PETR4"),
            )

    def test_cotacao_usd(self):
        with _patch_ticker({"currentPrice": 150.25, "currency": "USD"}):
            self.assertEqual(
                "Cotação AAPL: $ 150.25",
                B3FundamentosConsultor().get_cotacao_atual("AAPL"),
            )

    def test_cotacao_falls_back_to_regular_market_price(self):
        with _patch_ticker({"regularMarketPrice": 10.0, "currency": "BRL"}):
            self.assertEqual(
                "Cotação PETR4: R$ 10,00",
                B3FundamentosConsultor().get_cotacao_atual("PETR4"),
            )

    def test_cotacao_nan_price_is_treated_as_missing(self):
        with _patch_ticker({"currentPrice": float("nan"), "currency": "BRL"}):
            self.assertEqual(
                "Cotação: N/A", B3FundamentosConsultor().get_cotacao_atual("PETR4")
            )

    def test_cotacao_missing_price_returns_na(self):
        with _patch_ticker({"currency": "BRL"}):
            self.assertEqual(
                "Cotação: N/A", B3FundamentosConsultor().get_cotacao_atual("PETR4")
            )

    def test_market_cap_brl(self):
        with _patch_ticker({"marketCap": 421_500_000_000, "currency": "BRL"}):
            self.assertEqual(
                "Market Cap PETR4: R$ 421,5 B",
                B3FundamentosConsultor().get_market_cap("PETR4"),
            )

    def test_market_cap_missing_returns_na(self):
        with _patch_ticker({"currency": "BRL"}):
            self.assertEqual(
                "Market Cap: N/A", B3FundamentosConsultor().get_market_cap("PETR4")
            )

    def test_preco_lucro_trailing_then_forward(self):
        with _patch_ticker({"forwardPE": 7.2}):
            self.assertEqual(
                "P/L PETR4: 7,20", B3FundamentosConsultor().get_preco_lucro("PETR4")
            )

    def test_preco_lucro_zero_returns_na(self):
        with _patch_ticker({"trailingPE": 0}):
            self.assertEqual(
                "P/L: N/A", B3FundamentosConsultor().get_preco_lucro("PETR4")
            )

    def test_preco_vp(self):
        with _patch_ticker({"priceToBook": 1.2}):
            self.assertEqual(
                "P/VP PETR4: 1,20", B3FundamentosConsultor().get_preco_vp("PETR4")
            )

    def test_dividend_yield_positive(self):
        with _patch_ticker({"dividendYield": 12.5}):
            self.assertEqual(
                "DY PETR4: 12,50%",
                B3FundamentosConsultor().get_dividend_yield("PETR4"),
            )

    def test_dividend_yield_zero_returns_na(self):
        with _patch_ticker({"dividendYield": 0}):
            self.assertEqual(
                "DY: N/A", B3FundamentosConsultor().get_dividend_yield("PETR4")
            )

    def test_dividend_yield_negative_returns_na(self):
        with _patch_ticker({"dividendYield": -1.0}):
            self.assertEqual(
                "DY: N/A", B3FundamentosConsultor().get_dividend_yield("PETR4")
            )

    def test_margem_liquida_scaled_to_percent(self):
        with _patch_ticker({"profitMargins": 0.20}):
            self.assertEqual(
                "Margem Líq. PETR4: 20,00%",
                B3FundamentosConsultor().get_margem_liquida("PETR4"),
            )

    def test_roe_scaled_to_percent(self):
        with _patch_ticker({"returnOnEquity": 0.35}):
            self.assertEqual(
                "ROE PETR4: 35,00%", B3FundamentosConsultor().get_roe("PETR4")
            )

    def test_ebitda_currency_formatted(self):
        with _patch_ticker({"ebitda": 250_000_000_000, "currency": "BRL"}):
            self.assertEqual(
                "EBITDA PETR4: R$ 250,0 B",
                B3FundamentosConsultor().get_ebitda("PETR4"),
            )

    def test_receita_liquida_currency_formatted(self):
        with _patch_ticker({"totalRevenue": 500_000_000_000, "currency": "BRL"}):
            self.assertEqual(
                "Receita Líq. PETR4: R$ 500,0 B",
                B3FundamentosConsultor().get_receita_liquida("PETR4"),
            )


class DebtAndCashTests(unittest.TestCase):
    def test_divida_total_zero_is_shown(self):
        with _patch_ticker({"totalDebt": 0, "currency": "BRL"}):
            self.assertEqual(
                "Dív. Total PETR4: R$ 0,0",
                B3FundamentosConsultor().get_divida_total("PETR4"),
            )

    def test_divida_total_missing_returns_na(self):
        with _patch_ticker({"currency": "BRL"}):
            self.assertEqual(
                "Dív. Total: N/A", B3FundamentosConsultor().get_divida_total("PETR4")
            )

    def test_caixa_zero_is_shown(self):
        with _patch_ticker({"totalCash": 0, "currency": "BRL"}):
            self.assertEqual(
                "Caixa PETR4: R$ 0,0", B3FundamentosConsultor().get_caixa("PETR4")
            )

    def test_divida_liquida_debt_minus_cash(self):
        with _patch_ticker(
            {"totalDebt": 300_000_000_000, "totalCash": 100_000_000_000, "currency": "BRL"}
        ):
            self.assertEqual(
                "Dív. Líq. PETR4: R$ 200,0 B",
                B3FundamentosConsultor().get_divida_liquida("PETR4"),
            )

    def test_divida_liquida_without_cash_flags_sem_caixa(self):
        with _patch_ticker({"totalDebt": 300_000_000_000, "currency": "BRL"}):
            self.assertEqual(
                "Dív. Líq. PETR4: R$ 300,0 B (sem caixa)",
                B3FundamentosConsultor().get_divida_liquida("PETR4"),
            )

    def test_divida_liquida_missing_both_returns_na(self):
        with _patch_ticker({"currency": "BRL"}):
            self.assertEqual(
                "Dív. Líq.: N/A",
                B3FundamentosConsultor().get_divida_liquida("PETR4"),
            )


class BetaAndRangeTests(unittest.TestCase):
    def test_beta_below_one_is_less_volatile(self):
        with _patch_ticker({"beta": 0.85}):
            self.assertEqual(
                "Beta PETR4: 0,85 (menos volátil que o mercado)",
                B3FundamentosConsultor().get_beta("PETR4"),
            )

    def test_beta_equal_one_matches_market(self):
        with _patch_ticker({"beta": 1.0}):
            self.assertEqual(
                "Beta PETR4: 1,00 (igual ao mercado)",
                B3FundamentosConsultor().get_beta("PETR4"),
            )

    def test_beta_above_one_is_more_volatile(self):
        with _patch_ticker({"beta": 1.5}):
            self.assertEqual(
                "Beta PETR4: 1,50 (mais volátil que o mercado)",
                B3FundamentosConsultor().get_beta("PETR4"),
            )

    def test_beta_zero_returns_na(self):
        with _patch_ticker({"beta": 0}):
            self.assertEqual("Beta: N/A", B3FundamentosConsultor().get_beta("PETR4"))

    def test_52_week_near_high(self):
        with _patch_ticker(
            {
                "fiftyTwoWeekHigh": 40.0,
                "fiftyTwoWeekLow": 20.0,
                "currentPrice": 39.0,
                "currency": "BRL",
            }
        ):
            self.assertEqual(
                "52 Semanas PETR4: Mín R$ 20,00 | Máx R$ 40,00 (próximo da máxima)",
                B3FundamentosConsultor().get_52week_high_low("PETR4"),
            )

    def test_52_week_missing_bounds_returns_na(self):
        with _patch_ticker({"fiftyTwoWeekHigh": 40.0, "currency": "BRL"}):
            self.assertEqual(
                "52 Semanas: N/A",
                B3FundamentosConsultor().get_52week_high_low("PETR4"),
            )


class VolumeTests(unittest.TestCase):
    def test_volume_in_millions(self):
        with _patch_ticker({"averageDailyVolume10Day": 5_000_000}):
            self.assertEqual(
                "Vol. Médio PETR4: 5.0 M",
                B3FundamentosConsultor().get_volume_medio("PETR4"),
            )

    def test_volume_thousands_grouping(self):
        with _patch_ticker({"averageVolume": 500_000}):
            self.assertEqual(
                "Vol. Médio PETR4: 500.000",
                B3FundamentosConsultor().get_volume_medio("PETR4"),
            )

    def test_volume_zero_returns_na(self):
        with _patch_ticker({"averageVolume": 0}):
            self.assertEqual(
                "Vol. Médio: N/A",
                B3FundamentosConsultor().get_volume_medio("PETR4"),
            )


class ResumoTests(unittest.TestCase):
    FULL_INFO = {
        "symbol": "PETR4.SA",
        "currency": "BRL",
        "currentPrice": 31.45,
        "fiftyTwoWeekHigh": 40.0,
        "fiftyTwoWeekLow": 20.0,
        "beta": 0.85,
        "marketCap": 421_500_000_000,
        "totalRevenue": 500_000_000_000,
        "ebitda": 250_000_000_000,
        "netIncomeToCommon": 100_000_000_000,
        "profitMargins": 0.20,
        "trailingPE": 8.5,
        "dividendYield": 12.5,
        "priceToBook": 1.2,
        "returnOnEquity": 0.35,
        "totalDebt": 300_000_000_000,
        "totalCash": 100_000_000_000,
    }

    def test_resumo_contains_all_computed_fields(self):
        with _patch_ticker(self.FULL_INFO):
            resumo = B3FundamentosConsultor().get_resumo_fundamentos("PETR4")

        for fragment in (
            "📈 PETR4  |  R$ 31,45",
            "Mín R$ 20,00 | Máx R$ 40,00",
            "Beta: 0,85",
            "Market Cap: R$ 421,5 B",
            "Margem Líq.: 20,00%",
            "P/L: 8,50",
            "DY: 12,50%",
            "P/VP: 1,20",
            "ROE: 35,00%",
            "Dívida Líq.: R$ 200,0 B",
        ):
            self.assertIn(fragment, resumo)

    def test_resumo_with_empty_info_degrades_without_crashing(self):
        with _patch_ticker({}):
            resumo = B3FundamentosConsultor().get_resumo_fundamentos("XYZ")

        self.assertIn("📈 XYZ", resumo)
        self.assertIn("N/A", resumo)


class ErrorHandlingTests(unittest.TestCase):
    def test_getters_degrade_when_ticker_object_is_an_error_string(self):
        # ``_get_cached_or_fetch`` returns an error string when the yfinance
        # fetch raises; the getter then hits ``.info`` on a str and must fall
        # back to N/A rather than propagate the AttributeError.
        with mock.patch.object(
            B3FundamentosConsultor, "_get_ticker_object", return_value="[Erro: down]"
        ):
            c = B3FundamentosConsultor()
            self.assertEqual("Cotação: N/A", c.get_cotacao_atual("PETR4"))
            self.assertEqual("Market Cap: N/A", c.get_market_cap("PETR4"))
            self.assertTrue(
                c.get_resumo_fundamentos("PETR4").startswith("[Erro ao gerar resumo")
            )

    def test_yfinance_import_failure_is_swallowed_end_to_end(self):
        fake = types.ModuleType("yfinance")

        def _raise(*args, **kwargs):
            raise RuntimeError("yfinance boom")

        fake.Ticker = _raise
        saved = sys.modules.get("yfinance")
        sys.modules["yfinance"] = fake
        try:
            result = B3FundamentosConsultor().get_cotacao_atual("PETR4")
        finally:
            if saved is not None:
                sys.modules["yfinance"] = saved
            else:
                del sys.modules["yfinance"]

        self.assertEqual("Cotação: N/A", result)


class CachingTests(unittest.TestCase):
    def _clock(self):
        return _FrozenClock(datetime(2026, 1, 15, 12, 0, 0))

    def test_cache_hit_within_window_avoids_refetch(self):
        clock = self._clock()
        consultor = B3FundamentosConsultor(cache_seconds=600)
        tickers = [
            FakeTicker({"currentPrice": 10.0, "currency": "BRL"}),
            FakeTicker({"currentPrice": 20.0, "currency": "BRL"}),
        ]
        with mock.patch.object(yf_stocks, "datetime", clock), mock.patch.object(
            B3FundamentosConsultor, "_get_ticker_object", side_effect=tickers
        ) as fetch:
            first = consultor.get_cotacao_atual("PETR4")
            clock.advance(599)
            second = consultor.get_cotacao_atual("PETR4")

            self.assertEqual(first, second)
            self.assertIn("10,00", first)
            self.assertEqual(1, fetch.call_count)

    def test_cache_refetches_after_600_second_boundary(self):
        clock = self._clock()
        consultor = B3FundamentosConsultor(cache_seconds=600)
        tickers = [
            FakeTicker({"currentPrice": 10.0, "currency": "BRL"}),
            FakeTicker({"currentPrice": 20.0, "currency": "BRL"}),
        ]
        with mock.patch.object(yf_stocks, "datetime", clock), mock.patch.object(
            B3FundamentosConsultor, "_get_ticker_object", side_effect=tickers
        ) as fetch:
            consultor.get_cotacao_atual("PETR4")
            clock.advance(600)
            refreshed = consultor.get_cotacao_atual("PETR4")

            self.assertEqual(2, fetch.call_count)
            self.assertIn("20,00", refreshed)

    def test_cache_is_keyed_per_metric(self):
        consultor = B3FundamentosConsultor()
        info = {"currentPrice": 10.0, "marketCap": 421_500_000_000, "currency": "BRL"}
        with mock.patch.object(
            B3FundamentosConsultor, "_get_ticker_object", return_value=FakeTicker(info)
        ) as fetch:
            consultor.get_cotacao_atual("PETR4")
            consultor.get_cotacao_atual("PETR4")  # served from the price cache
            consultor.get_market_cap("PETR4")  # distinct metric key -> distinct fetch

        self.assertEqual(2, fetch.call_count)

    def test_cache_is_keyed_per_ticker(self):
        consultor = B3FundamentosConsultor()
        info = {"currentPrice": 10.0, "currency": "BRL"}
        with mock.patch.object(
            B3FundamentosConsultor, "_get_ticker_object", return_value=FakeTicker(info)
        ) as fetch:
            consultor.get_cotacao_atual("PETR4")
            consultor.get_cotacao_atual("AAPL")  # distinct ticker key -> distinct fetch

        self.assertEqual(2, fetch.call_count)

    def test_error_at_getter_level_is_not_poisoning_ticker_object_cache(self):
        # A raising fetch returns an error string and is never cached at the
        # ticker-object layer, so a subsequent success is served fresh.
        consultor = B3FundamentosConsultor()
        with mock.patch.object(
            B3FundamentosConsultor,
            "_get_ticker_object",
            side_effect=["[Erro: down]", FakeTicker({"currentPrice": 42.0, "currency": "BRL"})],
        ) as fetch:
            first = consultor.get_cotacao_atual("PETR4")
            # New consultor call for a different metric to force a fresh fetch
            second = consultor.get_market_cap("PETR4")

        self.assertEqual("Cotação: N/A", first)
        self.assertEqual(2, fetch.call_count)
        # marketCap absent from the second ticker -> N/A, but proves refetch ran.
        self.assertEqual("Market Cap: N/A", second)


if __name__ == "__main__":
    unittest.main()
