"""Interface language for SnipType's own UI.

Brazilian Portuguese is the source language: every user-facing string is
written in Portuguese and doubles as its own message id, so the default build
needs no catalog. ``_()`` looks the id up in the catalog of the active language
and falls back to the Portuguese text when there is no entry.

Translate at *display* time. A module-level constant evaluated at import would
freeze in whatever language was active then, so constants hold the Portuguese
id wrapped in the no-op marker ``N_()`` and callers pass them through ``_()``
when they build a widget or message. ``tests/test_i18n.py`` scans the source for
both markers and fails on an id without an English entry.

Until the user picks a language in Configurações > Geral, the interface
follows the Windows display language: English there means English here, any
other language means Portuguese. The choice is only persisted once the user
makes one, so a Windows language change is followed on the next launch.

Snippet *output* (dates written out in words, Central Bank and stock
summaries, WhatsApp text) is content, not interface, and stays in Portuguese.
"""

import ctypes
import sys

from i18n_en_us import EN_US

DEFAULT_LANGUAGE = "pt-BR"
# Shown in each language's own name so a user who picked the wrong one can
# still find their way back.
LANGUAGES = {
    "pt-BR": "Português (Brasil)",
    "en-US": "English (US)",
}
_CATALOGS = {"pt-BR": {}, "en-US": EN_US}

_LANG_ENGLISH = 0x09  # PRIMARYLANGID of a Windows LANGID

_language = DEFAULT_LANGUAGE


def system_language():
    """The language to use when the user has not chosen one."""
    # ceiling: Windows only; macOS/Linux start in Portuguese until someone
    # needs their locale honored too.
    if sys.platform.startswith("win"):
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if langid & 0x3FF == _LANG_ENGLISH:
            return "en-US"
    return DEFAULT_LANGUAGE


def set_language(code):
    """Make ``code`` the active language; no or an unknown code follows the system."""
    global _language
    _language = code if code in LANGUAGES else system_language()


def language():
    return _language


def _(message):
    """Return ``message`` (a Portuguese id) in the active language."""
    return _CATALOGS[_language].get(message, message)


def N_(message):
    """Mark a Portuguese id for translation without translating it yet."""
    return message


def lazy(message):
    """A pystray-style label callable that translates on every render."""
    return lambda *_args: _(message)
