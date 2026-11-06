"""Built-in snippet tokens: ``%%_date…%%`` and ``%%_cursor%%``.

Both live in the ``_`` namespace, which no static trigger may use
(``editor_session.static_trigger_problem``), so they can never shadow a user
snippet. Pure: no Tk, clipboard or keyboard; callers pass ``now``.

``%%_date%%`` grammar, after the name: an optional offset ``+N`` or ``-N``
followed by ``d`` (days), ``w`` (weeks), ``m`` (months) or ``y`` (years), N at
most three digits, then an optional ``:format``. The format cannot use
``strftime``'s ``%`` (it would end the token), so it uses the letter patterns
in ``_PATTERNS``; every other character is copied literally. A token cannot
hold whitespace, so "05 de março" is written as three tokens around plain text.
Output is Portuguese, like every other snippet output.

``%%_cursor%%`` marks where the caret ends after the expansion is pasted. The
resolver substitutes it with ``CARET_MARK`` in the same single pass as the
other values, so a ``%%_cursor%%`` that arrives inside clipboard text stays
literal; ``split_cursor`` then removes the mark and counts the characters the
caret has to move back over.
"""

import calendar
from datetime import datetime, timedelta
import re

from rich_text_support import extract_plain_text, is_rich_text_payload, rebuild_rich_text

CURSOR_NAME = "_cursor"
# U+FDD0 is a Unicode noncharacter, reserved for exactly this kind of internal
# marker, so it does not occur in text a person pasted or typed.
CARET_MARK = chr(0xFDD0)
DEFAULT_DATE_FORMAT = "dd/MM/yyyy"

_DATE_RE = re.compile(r"_date(?:(?P<sign>[+-])(?P<amount>\d{1,3})(?P<unit>[dwmy]))?(?::(?P<format>.+))?")

_MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",  # i18n: not ui
           "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")  # i18n: not ui
_WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira",  # i18n: not ui
             "quinta-feira", "sexta-feira", "sábado", "domingo")  # i18n: not ui

# Longest first, so "MMMM" is never read as "MM" + "MM".
_PATTERNS = (
    ("yyyy", lambda d: f"{d.year:04d}"),
    ("MMMM", lambda d: _MONTHS[d.month - 1]),
    ("dddd", lambda d: _WEEKDAYS[d.weekday()]),
    ("MMM", lambda d: _MONTHS[d.month - 1][:3]),
    ("ddd", lambda d: _WEEKDAYS[d.weekday()][:3]),
    ("yy", lambda d: f"{d.year % 100:02d}"),
    ("MM", lambda d: f"{d.month:02d}"),
    ("dd", lambda d: f"{d.day:02d}"),
    ("HH", lambda d: f"{d.hour:02d}"),
    ("mm", lambda d: f"{d.minute:02d}"),
    ("ss", lambda d: f"{d.second:02d}"),
    ("M", lambda d: str(d.month)),
    ("d", lambda d: str(d.day)),
    ("H", lambda d: str(d.hour)),
)
_PATTERN_RE = re.compile("|".join(re.escape(pattern) for pattern, _render in _PATTERNS))
_RENDERERS = dict(_PATTERNS)


def builtin_kind(name):
    """``"cursor"``, ``"date"`` or None for a variable name."""
    if name == CURSOR_NAME:
        return "cursor"
    if _DATE_RE.fullmatch(name):
        return "date"
    return None


def _add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def render_date(name, now):
    """The text a ``%%_date…%%`` token named ``name`` expands to at ``now``."""
    match = _DATE_RE.fullmatch(name)
    if match is None:
        raise ValueError(f"not a date token: {name!r}")
    value = now
    if match["amount"]:
        amount = int(match["amount"]) * (-1 if match["sign"] == "-" else 1)
        unit = match["unit"]
        if unit == "d":
            value = value + timedelta(days=amount)
        elif unit == "w":
            value = value + timedelta(weeks=amount)
        elif unit == "m":
            value = _add_months(value, amount)
        else:
            value = _add_months(value, 12 * amount)
    fmt = match["format"] or DEFAULT_DATE_FORMAT
    return _PATTERN_RE.sub(lambda token: _RENDERERS[token.group(0)](value), fmt)


def builtin_value(name, now=None):
    """The substitution for a built-in token: the date text or ``CARET_MARK``."""
    if name == CURSOR_NAME:
        return CARET_MARK
    return render_date(name, now or datetime.now())


def split_cursor(payload):
    """Return ``(payload without CARET_MARK, characters after the first mark)``.

    The count is what the caret moves back over after the paste. A CRLF counts
    once, as editors step over a line break in one keypress.
    """
    text = extract_plain_text(payload)
    index = text.find(CARET_MARK)
    if index < 0:
        return payload, 0
    clean = text.replace(CARET_MARK, "")
    back = len(clean[index:].replace("\r\n", "\n"))
    if is_rich_text_payload(payload):
        return rebuild_rich_text(payload, clean), back
    return clean, back
