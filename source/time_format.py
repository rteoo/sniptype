"""Local date and time wording for the manager, in the interface language.

Implements the shared time vocabulary of the Teô DS 2.8 operations proposal
(§12.6, recorded in DESIGN.md): a 24-hour local clock, absolute stamps for
records ("Hoje 14:02", "qua. 14/10 09:10", "14/10/2025") and relative ages
for freshness ("há 3 h"). Pure: callers pass ``now``.

Day and month order is not a translatable string, because the placeholders of
a catalog entry must match across languages; the English branch spells the
month and puts it first, as en-US does.
"""

import i18n
from i18n import N_, _

# Monday first, as ``datetime.weekday()`` and ``calendar.monthcalendar`` count.
WEEKDAYS = (
    N_("seg."), N_("ter."), N_("qua."), N_("qui."), N_("sex."), N_("sáb."), N_("dom."),
)
MONTHS = (
    N_("janeiro"), N_("fevereiro"), N_("março"), N_("abril"), N_("maio"), N_("junho"),
    N_("julho"), N_("agosto"), N_("setembro"), N_("outubro"), N_("novembro"), N_("dezembro"),
)
_EN_MONTHS_SHORT = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _english():
    return i18n.language() == "en-US"


def weekday_name(value):
    """The short weekday of ``value`` ("qua." / "Wed")."""
    return _(WEEKDAYS[value.weekday()])


def month_name(month):
    """The full name of ``month`` (1-12), lower case in Portuguese."""
    return _(MONTHS[month - 1])


def _day_month(value):
    if _english():
        return f"{_EN_MONTHS_SHORT[value.month - 1]} {value.day}"
    return f"{value.day:02d}/{value.month:02d}"


def _full_date(value):
    if _english():
        return f"{_EN_MONTHS_SHORT[value.month - 1]} {value.day}, {value.year}"
    return f"{value.day:02d}/{value.month:02d}/{value.year}"


def clock(value):
    """The 24-hour local time of ``value``, as receipts show it ("14:02")."""
    return value.strftime("%H:%M")


def absolute_stamp(value, now):
    """``value`` as a record stamp relative to the calendar day of ``now``."""
    clock_text = clock(value)
    days = (now.date() - value.date()).days
    if days == 0:
        return _("Hoje {time}").format(time=clock_text)
    if days == 1:
        return _("Ontem {time}").format(time=clock_text)
    if 1 < days < 7:
        return f"{weekday_name(value)} {_day_month(value)} {clock_text}"
    if value.year == now.year:
        return f"{_day_month(value)} {clock_text}"
    return _full_date(value)


def relative_age(value, now):
    """How long ago (or until) ``value``; a week or more is an absolute stamp."""
    seconds = (now - value).total_seconds()
    future = seconds < 0
    seconds = abs(seconds)
    if seconds < 60:
        return _("agora")
    for limit, size, past, ahead in (
        (3600, 60, N_("há {count} min"), N_("em {count} min")),
        (86400, 3600, N_("há {count} h"), N_("em {count} h")),
        (7 * 86400, 86400, N_("há {count} d"), N_("em {count} d")),
    ):
        if seconds < limit:
            return _(ahead if future else past).format(count=int(seconds // size))
    return absolute_stamp(value, now)


def stamp_with_age(value, now):
    """Both, as backups and exports show them: "14/10 09:10 · há 3 h"."""
    stamp = absolute_stamp(value, now)
    age = relative_age(value, now)
    return stamp if age == stamp else f"{stamp} · {age}"


__all__ = [
    "MONTHS",
    "WEEKDAYS",
    "absolute_stamp",
    "clock",
    "month_name",
    "relative_age",
    "stamp_with_age",
    "weekday_name",
]
