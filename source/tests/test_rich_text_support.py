import unittest

from rich_text_support import (
    build_rich_text_payload,
    extract_plain_text,
    get_clipboard_payload,
    is_rich_text_payload,
    normalize_rich_text_payload,
)


class RichTextSupportTests(unittest.TestCase):
    def test_build_rich_text_payload_returns_plain_string_without_spans(self):
        payload = build_rich_text_payload("hello", [])
        self.assertEqual("hello", payload)

    def test_build_rich_text_payload_builds_html_and_rtf(self):
        payload = build_rich_text_payload(
            "hello world",
            [
                {"tag": "bold", "start": 0, "end": 5},
                {"tag": "code", "start": 6, "end": 11},
                {"tag": "strike", "start": 6, "end": 11},
            ],
        )

        self.assertTrue(is_rich_text_payload(payload))
        self.assertEqual("hello world", payload["text"])
        self.assertIn("<strong>hello</strong>", payload["html"])
        self.assertIn("<s><code>world</code></s>", payload["html"])
        self.assertIn(r"\b ", payload["rtf"])
        self.assertIn(r"\f1 ", payload["rtf"])
        self.assertIn(r"\strike ", payload["rtf"])

    def test_extract_plain_text_reads_rich_text_payload(self):
        payload = {
            "__kind__": "rich_text",
            "text": "plain value",
            "spans": [],
        }
        self.assertEqual("plain value", extract_plain_text(payload))

    def test_normalize_rich_text_payload_backfills_missing_formats(self):
        payload = normalize_rich_text_payload(
            {
                "__kind__": "rich_text",
                "text": "abc",
                "spans": [{"tag": "italic", "start": 0, "end": 3}],
            }
        )

        self.assertIn("html", payload)
        self.assertIn("rtf", payload)
        self.assertIn("<em>abc</em>", payload["html"])

    def test_get_clipboard_payload_keeps_plain_text_for_unformatted_values(self):
        payload = get_clipboard_payload("just text")
        self.assertEqual({"text": "just text"}, payload)

    def test_get_clipboard_payload_includes_rich_formats(self):
        rich_payload = build_rich_text_payload(
            "abc",
            [
                {"tag": "underline", "start": 0, "end": 3},
                {"tag": "strike", "start": 0, "end": 3},
            ],
        )
        payload = get_clipboard_payload(rich_payload)

        self.assertEqual("abc", payload["text"])
        self.assertIn("html", payload)
        self.assertIn("rtf", payload)
        self.assertIn("<u><s>abc</s></u>", payload["html"])


if __name__ == "__main__":
    unittest.main()

