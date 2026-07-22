import unittest

from whatsapp_support import build_whatsapp_url, extract_phone_candidate, normalize_phone_number


class WhatsAppSupportTests(unittest.TestCase):
    def test_extract_phone_candidate_reads_wa_me_link(self):
        candidate = extract_phone_candidate("https://wa.me/5511999999999?text=Oi")

        self.assertEqual("+5511999999999", candidate)

    def test_extract_phone_candidate_reads_api_whatsapp_link(self):
        candidate = extract_phone_candidate("https://api.whatsapp.com/send?phone=5511999999999&text=Oi")

        self.assertEqual("+5511999999999", candidate)

    def test_extract_phone_candidate_returns_none_for_wa_me_without_number(self):
        self.assertIsNone(extract_phone_candidate("https://wa.me/?text=Oi"))

    def test_normalize_phone_number_adds_default_country_code_to_brazilian_local_number(self):
        self.assertEqual("5511999999999", normalize_phone_number("11999999999"))

    def test_normalize_phone_number_drops_single_trunk_zero_before_default_country_code(self):
        self.assertEqual("5511999999999", normalize_phone_number("011999999999"))

    def test_normalize_phone_number_accepts_explicit_international_prefix_plus(self):
        self.assertEqual("12125551234", normalize_phone_number("+1 (212) 555-1234"))

    def test_normalize_phone_number_accepts_explicit_international_prefix_00(self):
        self.assertEqual("5511999999999", normalize_phone_number("005511999999999"))

    def test_normalize_phone_number_accepts_existing_international_number_without_prefix(self):
        self.assertEqual("5511999999999", normalize_phone_number("55 11 99999-9999"))

    def test_normalize_phone_number_extracts_number_from_existing_whatsapp_link(self):
        self.assertEqual("5511999999999", normalize_phone_number("https://wa.me/5511999999999?text=Tenho%20interesse"))

    def test_normalize_phone_number_rejects_invalid_inputs(self):
        self.assertIsNone(normalize_phone_number("abc"))
        self.assertIsNone(normalize_phone_number("99999999"))
        self.assertIsNone(normalize_phone_number("999999999"))
        self.assertIsNone(normalize_phone_number("1234567890123456"))

    def test_build_whatsapp_url_without_message(self):
        self.assertEqual("https://wa.me/5511999999999", build_whatsapp_url("5511999999999"))

    def test_build_whatsapp_url_ignores_whitespace_only_message(self):
        self.assertEqual("https://wa.me/5511999999999", build_whatsapp_url("5511999999999", "   "))

    def test_build_whatsapp_url_with_encoded_message(self):
        url = build_whatsapp_url("5511999999999", "Olá!\nPreço & prazo?")

        self.assertEqual(
            "https://wa.me/5511999999999?text=Ol%C3%A1%21%0APre%C3%A7o%20%26%20prazo%3F",
            url,
        )

    # --- extract_phone_candidate: host routing and URL edge cases ---

    def test_extract_phone_candidate_reads_web_whatsapp_query_link(self):
        self.assertEqual(
            "+5511988887777",
            extract_phone_candidate("https://web.whatsapp.com/send?phone=5511988887777&text=Oi"),
        )

    def test_extract_phone_candidate_strips_trailing_sentence_punctuation(self):
        self.assertEqual(
            "+5511999999999",
            extract_phone_candidate("Fala com ele: https://wa.me/5511999999999)."),
        )

    def test_extract_phone_candidate_handles_http_scheme_and_uppercase_host(self):
        self.assertEqual(
            "+5511999999999", extract_phone_candidate("http://WA.ME/5511999999999")
        )

    def test_extract_phone_candidate_returns_plain_text_unchanged(self):
        self.assertEqual("meu contato", extract_phone_candidate("meu contato"))

    def test_extract_phone_candidate_returns_none_for_query_link_without_phone(self):
        self.assertIsNone(
            extract_phone_candidate("https://api.whatsapp.com/send?text=Oi")
        )

    def test_extract_phone_candidate_returns_raw_text_for_unknown_host(self):
        # A non-WhatsApp URL is not a phone source; the whole text is handed back
        # for the caller to sanitize (see whatsapp_support line 36).
        text = "https://example.com/5511999999999"
        self.assertEqual(text, extract_phone_candidate(text))

    def test_extract_phone_candidate_returns_none_for_empty_input(self):
        self.assertIsNone(extract_phone_candidate(""))
        self.assertIsNone(extract_phone_candidate("   "))
        self.assertIsNone(extract_phone_candidate(None))

    # --- normalize_phone_number: national vs international, punctuation ---

    def test_normalize_phone_number_adds_country_code_to_landline(self):
        self.assertEqual("551133334444", normalize_phone_number("(11) 3333-4444"))

    def test_normalize_phone_number_strips_parentheses_and_spaces_for_mobile(self):
        self.assertEqual("5511999999999", normalize_phone_number("(11) 99999-9999"))

    def test_normalize_phone_number_honours_custom_country_code(self):
        self.assertEqual(
            "12125551234",
            normalize_phone_number("212-555-1234", default_country_code="1"),
        )

    def test_normalize_phone_number_sanitizes_country_code_with_punctuation(self):
        self.assertEqual(
            "5511999999999",
            normalize_phone_number("11999999999", default_country_code="+55 "),
        )

    def test_normalize_phone_number_keeps_twelve_digit_international_number(self):
        self.assertEqual("551133334444", normalize_phone_number("551133334444"))

    def test_normalize_phone_number_rejects_absurdly_long_input(self):
        self.assertIsNone(normalize_phone_number("1" * 20))

    def test_normalize_phone_number_rejects_bare_plus_sign(self):
        self.assertIsNone(normalize_phone_number("+"))

    def test_normalize_phone_number_returns_none_for_empty_and_blank(self):
        self.assertIsNone(normalize_phone_number(""))
        self.assertIsNone(normalize_phone_number("   "))

    def test_normalize_phone_number_raises_for_empty_country_code(self):
        with self.assertRaises(ValueError):
            normalize_phone_number("11999999999", default_country_code="")

    def test_normalize_phone_number_raises_for_none_country_code(self):
        with self.assertRaises(ValueError):
            normalize_phone_number("11999999999", default_country_code=None)

    # --- build_whatsapp_url: encoding and validation ---

    def test_build_whatsapp_url_percent_encodes_reserved_characters(self):
        self.assertEqual(
            "https://wa.me/5511999999999?text=a%20b%26c%23d%3Fe%25f",
            build_whatsapp_url("5511999999999", "a b&c#d?e%f"),
        )

    def test_build_whatsapp_url_encodes_emoji(self):
        self.assertEqual(
            "https://wa.me/5511999999999?text=%F0%9F%98%80",
            build_whatsapp_url("5511999999999", "😀"),
        )

    def test_build_whatsapp_url_encodes_literal_plus(self):
        self.assertEqual(
            "https://wa.me/5511999999999?text=a%2Bb",
            build_whatsapp_url("5511999999999", "a+b"),
        )

    def test_build_whatsapp_url_strips_formatting_from_phone(self):
        self.assertEqual(
            "https://wa.me/5511999999999",
            build_whatsapp_url("+55 (11) 99999-9999"),
        )

    def test_build_whatsapp_url_raises_without_digits(self):
        with self.assertRaises(ValueError):
            build_whatsapp_url(None)
        with self.assertRaises(ValueError):
            build_whatsapp_url("+++")
        with self.assertRaises(ValueError):
            build_whatsapp_url("----", "mensagem")


if __name__ == "__main__":
    unittest.main()
