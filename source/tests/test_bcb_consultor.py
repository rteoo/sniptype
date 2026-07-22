"""Adversarial tests for the Brazilian Central Bank lookup module.

Every test is hermetic: ``urlopen`` and the module clock are mocked so no real
network call happens and cache expiry is exercised with a controlled clock.
The module imports ``urlopen``/``datetime``/``timedelta`` as flat names, so the
patch site is ``bcb_consultor`` itself.
"""

import unittest
from datetime import datetime, timedelta
from unittest import mock
from urllib.error import URLError

import bcb_consultor
from bcb_consultor import BCBConsultor


class _FakeResponse:
    """Minimal ``urlopen`` return value usable as a context manager."""

    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FrozenClock:
    """Drop-in for ``bcb_consultor.datetime`` with a controllable ``now()``."""

    def __init__(self, start):
        self.value = start

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value = self.value + timedelta(seconds=seconds)


SGS_BODY = '[{"valor":"13.75","data":"15/01/2026"}]'
DOLAR_BODY = (
    '{"value":[{"cotacaoCompra":5.40,"cotacaoVenda":5.4321,'
    '"dataHoraCotacao":"2026-01-15 13:08:00.0"}]}'
)


class FetchSgsTests(unittest.TestCase):
    def test_parses_valor_and_data_from_json(self):
        consultor = BCBConsultor()
        with mock.patch.object(bcb_consultor, "urlopen", return_value=_FakeResponse(SGS_BODY)):
            data = consultor._fetch_sgs(432)

        self.assertEqual({"valor": 13.75, "data": "15/01/2026"}, data)

    def test_empty_series_returns_none(self):
        consultor = BCBConsultor()
        with mock.patch.object(bcb_consultor, "urlopen", return_value=_FakeResponse("[]")):
            self.assertIsNone(consultor._fetch_sgs(432))

    def test_url_error_propagates_out_of_fetch_sgs(self):
        consultor = BCBConsultor()
        with mock.patch.object(bcb_consultor, "urlopen", side_effect=URLError("timeout")):
            with self.assertRaises(URLError):
                consultor._fetch_sgs(432)

    def test_malformed_json_body_propagates(self):
        consultor = BCBConsultor()
        with mock.patch.object(bcb_consultor, "urlopen", return_value=_FakeResponse("not json")):
            with self.assertRaises(ValueError):
                consultor._fetch_sgs(432)

    def test_series_code_is_embedded_in_request_url(self):
        consultor = BCBConsultor()
        with mock.patch.object(bcb_consultor, "urlopen", return_value=_FakeResponse(SGS_BODY)) as opener:
            consultor._fetch_sgs(13522)

        url = opener.call_args.args[0]
        self.assertIn("bcdata.sgs.13522", url)


class GetterFormattingTests(unittest.TestCase):
    def _sgs(self, valor, data="15/01/2026"):
        return mock.patch.object(
            BCBConsultor, "_fetch_sgs", return_value={"valor": valor, "data": data}
        )

    def test_selic_uses_two_decimals_and_dot_separator(self):
        consultor = BCBConsultor()
        with self._sgs(13.75):
            self.assertEqual(
                "Taxa Selic: 13.75% a.a. (ref: 15/01/2026)", consultor.get_selic_meta()
            )

    def test_cdi_formatting(self):
        consultor = BCBConsultor()
        with self._sgs(13.65):
            self.assertEqual(
                "13.65% acum. mês (ref: 15/01/2026)", consultor.get_cdi()
            )

    def test_ptax_sgs_uses_four_decimals(self):
        consultor = BCBConsultor()
        with self._sgs(5.4321):
            self.assertEqual("R$ 5.4321 (ref: 15/01/2026)", consultor.get_ptax_sgs())

    def test_ipca_mensal_converts_date_to_month_year(self):
        consultor = BCBConsultor()
        with self._sgs(0.52, data="15/01/2026"):
            self.assertEqual(
                "IPCA Mensal: 0.52% ref. 01/2026", consultor.get_ipca_mensal()
            )

    def test_ipca_12m_converts_date_to_month_year(self):
        consultor = BCBConsultor()
        with self._sgs(4.62, data="31/12/2025"):
            self.assertEqual(
                "IPCA 12 Meses: 4.62% ref. 12/2025", consultor.get_ipca_12m()
            )

    def test_selic_unavailable_when_series_empty(self):
        consultor = BCBConsultor()
        with mock.patch.object(BCBConsultor, "_fetch_sgs", return_value=None):
            self.assertEqual("[Dado indisponível]", consultor.get_selic_meta())

    def test_dolar_formatting(self):
        consultor = BCBConsultor()
        payload = {"compra": 5.40, "venda": 5.4321, "data": "2026-01-15"}
        with mock.patch.object(BCBConsultor, "_fetch_dolar", return_value=payload):
            self.assertEqual(
                "US$ 1,00 = R$ 5.43 (compra: R$ 5.40) - 2026-01-15",
                consultor.get_dolar(),
            )

    def test_dolar_unavailable_when_fetch_returns_none(self):
        consultor = BCBConsultor()
        with mock.patch.object(BCBConsultor, "_fetch_dolar", return_value=None):
            self.assertEqual("[Cotação indisponível]", consultor.get_dolar())

    def test_resumo_economico_includes_all_indicators(self):
        consultor = BCBConsultor()
        dolar = {"compra": 5.40, "venda": 5.4321, "data": "2026-01-15"}
        with mock.patch.object(BCBConsultor, "_fetch_dolar", return_value=dolar), mock.patch.object(
            BCBConsultor, "_fetch_sgs", return_value={"valor": 13.75, "data": "15/01/2026"}
        ):
            resumo = consultor.get_resumo_economico()

        self.assertIn("INDICADORES ECONÔMICOS", resumo)
        self.assertIn("Dólar: R$ 5.43", resumo)
        self.assertIn("Selic Meta: 13.75% a.a.", resumo)
        self.assertIn("CDI: 13.75% (mês)", resumo)

    def test_resumo_economico_survives_a_raising_fetch(self):
        consultor = BCBConsultor()
        with mock.patch.object(BCBConsultor, "_fetch_dolar", side_effect=URLError("down")):
            resumo = consultor.get_resumo_economico()

        self.assertTrue(resumo.startswith("[Erro ao gerar resumo"))


class ValueParsingTests(unittest.TestCase):
    def test_comma_decimal_valor_degrades_to_error_string_not_crash(self):
        # The BCB SGS API returns a dot-decimal string; a comma-decimal body is
        # not parsed. The module must return an error marker, never raise.
        consultor = BCBConsultor()
        body = '[{"valor":"13,75","data":"15/01/2026"}]'
        with mock.patch.object(bcb_consultor, "urlopen", return_value=_FakeResponse(body)):
            result = consultor.get_selic_meta()

        self.assertTrue(result.startswith("[Erro"))

    def test_unexpected_date_shape_degrades_to_error_string(self):
        consultor = BCBConsultor()
        with mock.patch.object(
            BCBConsultor, "_fetch_sgs", return_value={"valor": 0.52, "data": "2026-01-15"}
        ):
            result = consultor.get_ipca_mensal()

        self.assertTrue(result.startswith("[Erro"))


class FetchDolarTests(unittest.TestCase):
    def test_uses_mm_dd_yyyy_date_in_request_url(self):
        consultor = BCBConsultor()
        clock = _FrozenClock(datetime(2026, 1, 15, 10, 0, 0))
        with mock.patch.object(bcb_consultor, "datetime", clock), mock.patch.object(
            bcb_consultor, "urlopen", return_value=_FakeResponse(DOLAR_BODY)
        ) as opener:
            data = consultor._fetch_dolar()

        self.assertEqual(5.4321, data["venda"])
        self.assertEqual(5.40, data["compra"])
        self.assertEqual("2026-01-15", data["data"])
        self.assertIn("01-15-2026", opener.call_args_list[0].args[0])

    def test_retries_previous_days_when_first_day_fails(self):
        consultor = BCBConsultor()
        clock = _FrozenClock(datetime(2026, 1, 15, 10, 0, 0))
        with mock.patch.object(bcb_consultor, "datetime", clock), mock.patch.object(
            bcb_consultor,
            "urlopen",
            side_effect=[URLError("no data"), _FakeResponse(DOLAR_BODY)],
        ) as opener:
            data = consultor._fetch_dolar()

        self.assertEqual(5.4321, data["venda"])
        self.assertEqual(2, opener.call_count)
        # Second attempt walks back one calendar day.
        self.assertIn("01-14-2026", opener.call_args_list[1].args[0])

    def test_returns_none_when_every_day_fails(self):
        consultor = BCBConsultor()
        clock = _FrozenClock(datetime(2026, 1, 15, 10, 0, 0))
        with mock.patch.object(bcb_consultor, "datetime", clock), mock.patch.object(
            bcb_consultor, "urlopen", side_effect=URLError("no data")
        ) as opener:
            self.assertIsNone(consultor._fetch_dolar())

        self.assertEqual(5, opener.call_count)


class CachingTests(unittest.TestCase):
    def _clock(self):
        return _FrozenClock(datetime(2026, 1, 15, 12, 0, 0))

    def test_cache_hit_within_window_avoids_second_fetch(self):
        consultor = BCBConsultor(cache_seconds=300)
        clock = self._clock()
        with mock.patch.object(bcb_consultor, "datetime", clock), mock.patch.object(
            BCBConsultor, "_fetch_sgs", return_value={"valor": 13.75, "data": "15/01/2026"}
        ) as fetch:
            first = consultor.get_selic_meta()
            clock.advance(299)
            second = consultor.get_selic_meta()

            self.assertEqual(first, second)
            self.assertEqual(1, fetch.call_count)

    def test_cache_refetches_after_300_second_boundary(self):
        consultor = BCBConsultor(cache_seconds=300)
        clock = self._clock()
        with mock.patch.object(bcb_consultor, "datetime", clock), mock.patch.object(
            BCBConsultor, "_fetch_sgs", return_value={"valor": 13.75, "data": "15/01/2026"}
        ) as fetch:
            consultor.get_selic_meta()
            clock.advance(299)
            consultor.get_selic_meta()
            self.assertEqual(1, fetch.call_count)
            clock.advance(1)  # exactly 300s from the cached timestamp
            consultor.get_selic_meta()
            self.assertEqual(2, fetch.call_count)

    def test_error_response_does_not_poison_cache(self):
        consultor = BCBConsultor(cache_seconds=300)
        with mock.patch.object(
            BCBConsultor,
            "_fetch_sgs",
            side_effect=[URLError("down"), {"valor": 13.75, "data": "15/01/2026"}],
        ) as fetch:
            first = consultor.get_selic_meta()
            second = consultor.get_selic_meta()

        self.assertTrue(first.startswith("[Erro"))
        self.assertIn("13.75", second)
        self.assertEqual(2, fetch.call_count)

    def test_stale_cache_served_when_refresh_fails(self):
        consultor = BCBConsultor(cache_seconds=300)
        clock = self._clock()
        with mock.patch.object(bcb_consultor, "datetime", clock), mock.patch.object(
            BCBConsultor,
            "_fetch_sgs",
            side_effect=[{"valor": 13.75, "data": "15/01/2026"}, URLError("down")],
        ) as fetch:
            fresh = consultor.get_selic_meta()
            clock.advance(301)
            stale = consultor.get_selic_meta()

        self.assertEqual(fresh, stale)
        self.assertEqual(2, fetch.call_count)

    def test_cache_is_keyed_per_series(self):
        consultor = BCBConsultor()
        with mock.patch.object(
            BCBConsultor,
            "_fetch_sgs",
            side_effect=lambda codigo: {"valor": float(codigo), "data": "15/01/2026"},
        ) as fetch:
            consultor.get_selic_meta()
            consultor.get_selic_meta()  # served from the selic cache
            consultor.get_cdi()  # distinct key -> distinct fetch

        self.assertEqual(2, fetch.call_count)
        codes = [call.args[0] for call in fetch.call_args_list]
        self.assertEqual([BCBConsultor.SERIES["selic_meta"], BCBConsultor.SERIES["cdi"]], codes)


if __name__ == "__main__":
    unittest.main()
