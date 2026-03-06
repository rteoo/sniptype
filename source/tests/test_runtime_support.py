import unittest

from runtime_support import (
    _html_clipboard_bytes,
    build_snippet_failure_notification,
    truncate_notification_text,
)


class RuntimeSupportTests(unittest.TestCase):
    def test_html_clipboard_bytes_include_required_header(self):
        payload = _html_clipboard_bytes("<div><strong>abc</strong></div>")

        self.assertIn(b"Version:0.9", payload)
        self.assertIn(b"StartHTML:", payload)
        self.assertIn(b"EndHTML:", payload)
        self.assertIn(b"StartFragment:", payload)
        self.assertIn(b"EndFragment:", payload)
        self.assertIn(b"<strong>abc</strong>", payload)

    def test_build_snippet_failure_notification_handles_error_wrappers(self):
        message = build_snippet_failure_notification("xdolar", "[Erro: timeout na API]")

        self.assertIn("xdolar", message)
        self.assertIn("timeout na API", message)

    def test_build_snippet_failure_notification_handles_unavailable_api_values(self):
        message = build_snippet_failure_notification("xcot", "Cotação: N/A")

        self.assertEqual("Falha no snippet xcot: dado indisponível.", message)

    def test_build_snippet_failure_notification_ignores_cancelled_and_partial_results(self):
        self.assertIsNone(build_snippet_failure_notification("xfund", "[Cancelado]"))
        self.assertIsNone(
            build_snippet_failure_notification(
                "xfund",
                "📈 PETR4 | R$ 31,00\n📘 P/VP: N/A\n🎯 ROE: 18,50%",
            )
        )

    def test_truncate_notification_text_normalizes_whitespace_and_truncates(self):
        message = truncate_notification_text("linha 1\nlinha 2\tlinha 3", max_length=18)

        self.assertEqual("linha 1 linha 2...", message)


if __name__ == "__main__":
    unittest.main()
