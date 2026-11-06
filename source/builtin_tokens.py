"""Built-in snippet tokens: ``%%_date…%%``, ``%%_cursor%%`` and the keys.

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

``%%_enter%%`` and ``%%_tab%%`` press that key between pieces of text. They
become marks the same way, and ``plan_insertion`` turns the resolved payload
into paste and key steps.

``%%_if:COND%%`` … ``%%_elif:COND%%`` … ``%%_else%%`` … ``%%_endif%%`` keep
only the branch whose condition holds when the snippet expands (blocks nest).
``resolve_conditions`` runs before anything else reads the text, so a branch
that is dropped never asks for its form fields nor runs its dynamic snippets.
A line break touching a marker is layout: one right after ``_if``, ``_elif``
or ``_else`` and one right before ``_elif``, ``_else`` or ``_endif`` are
dropped, so each branch can sit on its own line.
"""

import calendar
from datetime import datetime, timedelta
import re

from i18n import N_, _
from rich_text_support import (
    build_rich_text_payload,
    extract_plain_text,
    is_rich_text_payload,
    normalize_style_spans,
    rebuild_rich_text,
)

CURSOR_NAME = "_cursor"
# U+FDD0 is a Unicode noncharacter, reserved for exactly this kind of internal
# marker, so it does not occur in text a person pasted or typed.
CARET_MARK = chr(0xFDD0)
DEFAULT_DATE_FORMAT = "dd/MM/yyyy"
# Token name -> the key it presses. More noncharacters mark each one.
KEYS = {"_enter": "enter", "_tab": "tab"}
_KEY_MARKS = {"enter": chr(0xFDD1), "tab": chr(0xFDD2)}
_MARK_KEYS = {mark: key for key, mark in _KEY_MARKS.items()}
# Every mark above lies in U+FDD0..U+FDEF, a block of noncharacters. A mark
# must come only from a built-in token: text from anywhere else (the snippet
# itself, the clipboard, a provider, a form) goes through ``strip_marks``, or
# a U+FDD1 copied from a web page would press Enter.
_MARK_BLOCK = {code: None for code in range(0xFDD0, 0xFDF0)}
# How a key that was not pressed is written when the rest of a stopped
# sequence is left on the clipboard as text.
KEY_TEXT = {"enter": "\n", "tab": "\t"}

_DATE_RE = re.compile(r"_date(?:(?P<sign>[+-])(?P<amount>\d{1,3})(?P<unit>[dwmy]))?(?::(?P<format>.+))?")
# Any _if/_elif is a condition marker, whatever follows it: an unknown
# condition is reported, never asked for as a form field.
_CONDITION_RE = re.compile(r"_(?P<word>if|elif)(?::(?P<condition>.*))?|_(?P<bare>else|endif)")
_TOKEN_RE = re.compile(r"%%([^%\s]+)%%")
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# Morning 05:00-11:59, afternoon 12:00-17:59, night 18:00-04:59.
CONDITIONS = {
    "morning": lambda now: 5 <= now.hour < 12,
    "afternoon": lambda now: 12 <= now.hour < 18,
    "night": lambda now: now.hour >= 18 or now.hour < 5,
    "weekday": lambda now: now.weekday() < 5,
    "weekend": lambda now: now.weekday() >= 5,
    **{day: (lambda now, index=index: now.weekday() == index) for index, day in enumerate(_DAYS)},
}
UNKNOWN_CONDITION = N_(
    "Condição desconhecida. Use morning, afternoon, night, weekday, weekend "
    "ou mon, tue, wed, thu, fri, sat, sun."
)
STRAY_MARKER = N_("%%_elif%%, %%_else%% ou %%_endif%% sem um %%_if%% antes.")
AFTER_ELSE = N_("%%_elif%% ou %%_else%% depois do %%_else%% da mesma condição.")
UNCLOSED = N_("Falta um %%_endif%% para fechar a condição.")


class ConditionError(ValueError):
    """A malformed condition block. ``message_id`` is the untranslated message."""

    def __init__(self, message_id):
        super().__init__(_(message_id))
        self.message_id = message_id

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


def strip_marks(text):
    """``text`` without any mark character, so data can never act as a token."""
    return text.translate(_MARK_BLOCK)


def builtin_kind(name):
    """``"cursor"``, ``"key"``, ``"date"``, ``"condition"`` or None for a variable name."""
    if name == CURSOR_NAME:
        return "cursor"
    if name in KEYS:
        return "key"
    if _DATE_RE.fullmatch(name):
        return "date"
    if _CONDITION_RE.fullmatch(name):
        return "condition"
    return None


def _holds(condition, now):
    test = CONDITIONS.get(condition)
    if test is None:
        raise ConditionError(UNKNOWN_CONDITION)
    return test(now)


def _without_trailing_break(chunk):
    if chunk.endswith("\r\n"):
        return chunk[:-2]
    return chunk[:-1] if chunk.endswith("\n") else chunk


def _after_leading_break(text, index):
    if text.startswith("\r\n", index):
        return index + 2
    return index + 1 if text.startswith("\n", index) else index


def resolve_conditions(text, now=None):
    """``text`` with each condition block replaced by the branch that holds at ``now``.

    Raises :class:`ConditionError` for a malformed block, checking every
    marker, including those in branches that are dropped.
    """
    if "%%_" not in text:
        return text
    now = now or datetime.now()
    out = []
    # One frame per open block: [parent emits, a branch was taken, _else seen].
    stack = []
    active = True
    position = 0
    for match in _TOKEN_RE.finditer(text):
        marker = _CONDITION_RE.fullmatch(match.group(1))
        if marker is None:
            continue
        word = marker["word"] or marker["bare"]
        chunk = text[position:match.start()]
        if word != "if":
            chunk = _without_trailing_break(chunk)
        if active:
            out.append(chunk)
        position = match.end()
        if word != "endif":
            position = _after_leading_break(text, position)
        if word == "if":
            frame = [active, False, False]
            stack.append(frame)
            chosen = _holds(marker["condition"], now) and active
        else:
            if not stack:
                raise ConditionError(STRAY_MARKER)
            frame = stack[-1]
            if word == "endif":
                stack.pop()
                active = frame[0]
                continue
            if frame[2]:
                raise ConditionError(AFTER_ELSE)
            if word == "else":
                frame[2] = True
                chosen = frame[0] and not frame[1]
            else:
                chosen = _holds(marker["condition"], now) and frame[0] and not frame[1]
        frame[1] = frame[1] or chosen
        active = chosen
    if stack:
        raise ConditionError(UNCLOSED)
    out.append(text[position:])
    return "".join(out)


def condition_problem(text):
    """Why ``text``'s condition blocks are malformed, as a message id, or None."""
    try:
        resolve_conditions(text, datetime(2000, 1, 1))
    except ConditionError as error:
        return error.message_id
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
    """The substitution for a built-in token: the date text, ``CARET_MARK`` or a key's mark."""
    if name == CURSOR_NAME:
        return CARET_MARK
    if name in KEYS:
        return _KEY_MARKS[KEYS[name]]
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


def _slice(payload, start, end):
    """``payload`` from ``start`` to ``end``, its styles clipped to that range."""
    text = extract_plain_text(payload)[start:end]
    if not is_rich_text_payload(payload):
        return text
    spans = [
        {"tag": span["tag"], "start": max(span["start"], start) - start, "end": min(span["end"], end) - start}
        for span in normalize_style_spans(payload.get("spans", []), len(payload["text"]))
        if span["start"] < end and span["end"] > start
    ]
    return build_rich_text_payload(text, spans)


def plan_insertion(payload, keys=True):
    """Return ``(steps, caret_back)`` for a resolved payload.

    ``steps`` are ``("text", payload)`` and ``("key", name)`` in order; without
    a key it is the one text step, empty or not. The caret moves back only
    from a ``%%_cursor%%`` after the last key: one before a key would have to
    travel back across what the key did (another field, a sent message), so
    it is dropped. ``keys=False`` (the fast route, which does not watch the
    keyboard while it inserts) drops every key mark instead of pressing it.
    """
    text = extract_plain_text(payload)
    if not keys and any(mark in text for mark in _MARK_KEYS):
        kept = "".join(char for char in text if char not in _MARK_KEYS)
        payload = rebuild_rich_text(payload, kept) if is_rich_text_payload(payload) else kept
        text = kept
    caret = text.find(CARET_MARK)
    last_key = max((text.rfind(mark) for mark in _MARK_KEYS), default=-1)
    clean_payload, caret_back = split_cursor(payload)
    if caret < last_key:
        caret_back = 0
    clean = extract_plain_text(clean_payload)
    steps, start = [], 0
    for index, char in enumerate(clean):
        key = _MARK_KEYS.get(char)
        if key is None:
            continue
        if index > start:
            steps.append(("text", _slice(clean_payload, start, index)))
        steps.append(("key", key))
        start = index + 1
    if start < len(clean) or not steps:
        steps.append(("text", _slice(clean_payload, start, len(clean)) if steps else clean_payload))
    return steps, caret_back


def steps_text(steps):
    """The steps as plain text, keys written as ``KEY_TEXT``: what a stopped sequence leaves to paste."""
    return "".join(
        KEY_TEXT[value] if kind == "key" else extract_plain_text(value) for kind, value in steps
    )
