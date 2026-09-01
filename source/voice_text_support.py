"""Deterministic, user-configured corrections for voice transcripts."""

import re


MAX_REPLACEMENTS = 200
MAX_TERM_LENGTH = 120
MAX_REPLACEMENT_LENGTH = 240


def validate_replacements(value):
    """Return a normalized replacement mapping, or an empty mapping.

    Settings are user-editable JSON, so malformed values are ignored rather
    than allowed to affect the voice worker.
    """
    if not isinstance(value, dict) or len(value) > MAX_REPLACEMENTS:
        return {}
    result = {}
    for source, replacement in value.items():
        if not isinstance(source, str) or not isinstance(replacement, str):
            return {}
        source = source.strip()
        if (
            not source
            or not replacement.strip()
            or len(source) > MAX_TERM_LENGTH
            or len(replacement) > MAX_REPLACEMENT_LENGTH
        ):
            return {}
        if source.casefold() in {item.casefold() for item in result}:
            return {}
        result[source] = replacement
    return result


class VoiceTextReplacements:
    """Compiled, one-pass phrase replacer."""

    def __init__(self, replacements=None):
        self.replacements = validate_replacements(replacements)
        self._lookup = {
            source.casefold(): replacement
            for source, replacement in self.replacements.items()
        }
        alternatives = sorted(self.replacements, key=len, reverse=True)
        self._pattern = (
            re.compile(
                r"(?<!\w)(?:" + "|".join(re.escape(item) for item in alternatives) + r")(?!\w)",
                re.IGNORECASE | re.UNICODE,
            )
            if alternatives
            else None
        )

    def apply(self, text):
        if not isinstance(text, str) or self._pattern is None:
            return text
        return self._pattern.sub(lambda match: self._replacement(match.group()), text)

    def _replacement(self, matched):
        # Case-folding chooses the configured spelling while preserving its
        # exact replacement text; replacements never feed back into matching.
        return self._lookup.get(matched.casefold(), matched)


def apply_voice_replacements(text, replacements):
    return VoiceTextReplacements(replacements).apply(text)
