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


if __name__ == "__main__":
    unittest.main()
