import re
from urllib.parse import parse_qs, quote, urlparse


WA_ME_HOSTS = {"wa.me", "www.wa.me"}
WHATSAPP_QUERY_HOSTS = {"api.whatsapp.com", "web.whatsapp.com", "www.api.whatsapp.com", "www.web.whatsapp.com"}


def extract_phone_candidate(raw_text):
    """Return the raw phone-like candidate from plain text or known WhatsApp URLs."""
    text = (raw_text or "").strip()
    if not text:
        return None

    url_match = re.search(r"(https?://\S+|(?:wa\.me|api\.whatsapp\.com|web\.whatsapp\.com)\S*)", text, re.IGNORECASE)
    if not url_match:
        return text

    raw_url = url_match.group(1).rstrip(").,;")
    normalized_url = raw_url if raw_url.lower().startswith(("http://", "https://")) else f"https://{raw_url}"
    parsed = urlparse(normalized_url)
    host = parsed.netloc.lower()

    if host in WA_ME_HOSTS:
        path_number = parsed.path.strip("/")
        if path_number:
            return f"+{path_number}"
        return None

    if host in WHATSAPP_QUERY_HOSTS:
        phone = parse_qs(parsed.query).get("phone", [None])[0]
        if phone:
            return f"+{phone}"
        return None

    return text


def normalize_phone_number(raw_text, default_country_code="55"):
    """Normalize a phone to the digits-only format required by wa.me links."""
    candidate = extract_phone_candidate(raw_text)
    if candidate is None:
        return None

    text = candidate.strip()
    if not text:
        return None

    sanitized_default_country = re.sub(r"\D", "", default_country_code or "")
    if not sanitized_default_country:
        raise ValueError("default_country_code must contain at least one digit")

    cleaned = re.sub(r"[^\d+]", "", text)
    explicit_international = False

    if cleaned.startswith("+"):
        explicit_international = True
        digits = re.sub(r"\D", "", cleaned[1:])
    elif cleaned.startswith("00"):
        explicit_international = True
        digits = re.sub(r"\D", "", cleaned[2:])
    else:
        digits = re.sub(r"\D", "", cleaned)

        if digits.startswith("0"):
            digits = digits[1:]

        if len(digits) in (10, 11):
            digits = f"{sanitized_default_country}{digits}"
        elif 12 <= len(digits) <= 15:
            pass
        else:
            return None

    if explicit_international and not (8 <= len(digits) <= 15):
        return None

    return digits or None


def build_whatsapp_url(phone_number, message=""):
    """Build a WhatsApp wa.me URL from a normalized phone and optional message."""
    digits = re.sub(r"\D", "", phone_number or "")
    if not digits:
        raise ValueError("phone_number must contain digits")

    url = f"https://wa.me/{digits}"
    if message and str(message).strip():
        return f"{url}?text={quote(message, safe='')}"
    return url
