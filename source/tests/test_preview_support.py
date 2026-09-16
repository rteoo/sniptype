import unittest
from unittest import mock

from preview_support import (
    CLIPBOARD_PLACEHOLDER,
    DYNAMIC_PLACEHOLDER_TEMPLATE,
    resolve_preview,
)


class PreviewSupportTests(unittest.TestCase):
    def test_resolves_static_and_mapping_references_from_memory(self):
        snippets = {
            "xname": "Ada",
            "_codes": {"__prefix__": "c", "city": "Goiânia"},
        }

        result = resolve_preview("Hello %%xname%% in %%ccity%%", snippets)

        self.assertEqual("Hello Ada in Goiânia", result.payload)
        self.assertEqual((), result.unavailable)

    def test_never_invokes_dynamic_or_reads_clipboard(self):
        provider = mock.Mock(side_effect=AssertionError("provider invoked"))
        snippets = {"xrate": provider}

        result = resolve_preview("%%clipboard-paste%% / %%xrate%%", snippets)

        self.assertEqual(
            f"{CLIPBOARD_PLACEHOLDER} / "
            + DYNAMIC_PLACEHOLDER_TEMPLATE.format(name="xrate"),
            result.payload,
        )
        self.assertEqual(("clipboard-paste", "xrate"), result.unavailable)
        provider.assert_not_called()

    def test_uses_structured_defaults_and_supplied_values(self):
        fields = [
            {"name": "name", "type": "text", "default": "Ada"},
            {"name": "suffix", "type": "optional", "content": "!", "default": False},
        ]

        defaulted = resolve_preview("Hello %%name%%%%suffix%%", {}, fields)
        supplied = resolve_preview(
            "Hello %%name%%%%suffix%%",
            {},
            fields,
            {"name": "Grace", "suffix": True},
        )

        self.assertEqual("Hello Ada", defaulted.payload)
        self.assertEqual("Hello Grace!", supplied.payload)

    def test_replacement_tokens_are_literal_in_single_pass(self):
        fields = [{"name": "value", "type": "text", "default": ""}]

        result = resolve_preview(
            "Value: %%value%%",
            {"xsecret": "must not be substituted"},
            fields,
            {"value": "%%xsecret%%"},
        )

        self.assertEqual("Value: %%xsecret%%", result.payload)

    def test_rich_payload_preserves_and_remaps_spans(self):
        value = {
            "__kind__": "rich_text",
            "text": "Hi %%name%%",
            "spans": [{"tag": "bold", "start": 3, "end": 11}],
        }
        fields = [{"name": "name", "type": "text", "default": "Ada"}]

        result = resolve_preview(value, {}, fields)

        self.assertEqual("Hi Ada", result.payload["text"])
        self.assertEqual(
            [{"tag": "bold", "start": 3, "end": 6}],
            result.payload["spans"],
        )

    def test_legacy_form_defaults_to_empty_without_metadata(self):
        result = resolve_preview("Hello %%name%%", {})

        self.assertEqual("Hello ", result.payload)


if __name__ == "__main__":
    unittest.main()
