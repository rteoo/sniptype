"""Per-OS palette and font resolution for the Tkinter windows.

The manager GUI was written Windows-first with a hardcoded light palette and
``Segoe UI`` everywhere. On macOS that produced unreadable windows: Aqua themes
the widgets the app leaves uncolored according to the *system* appearance, so a
dark-mode ``tk.Entry`` renders black-on-black inside a ``#F4F6FA`` frame, and
``Segoe UI`` silently substitutes to a different font with different metrics.

This module is the seam. Call sites ask for a semantic token
(``theme().surface``, ``theme().text``) and a size (``ui_font(9, "bold")``)
instead of naming a color or a font family:

* **Windows** resolves to the exact literals the GUI shipped with, so the
  Windows appearance is byte-for-byte unchanged (asserted in the tests).
* **macOS** resolves to Aqua's dynamic system colors (``systemTextColor`` and
  friends), which follow the light/dark appearance natively, plus a small set
  of derived grays for the tokens Aqua only exposes with an alpha channel --
  Tk drops the alpha and hands back pure white, which would be invisible.
* **Linux** reuses the same literals: Aqua's color names do not exist on X11,
  and the GUI is untested there anyway.

Resolution needs a live widget on macOS (the system colors are queried through
Tk), so :func:`bind` is called by each top-level window builder and the result
is cached until the next ``bind``. Re-binding per window is deliberate: it is
what makes reopening the manager pick up an appearance the user changed while
it was closed. A live switch with the window open is not handled -- the tokens
mapped to system color *names* repaint themselves, the derived grays do not.
"""

from tkinter import font as tkfont

from platform_support import current_os


# The GUI's body size, in the Windows point scale every ``font=`` call uses.
# Other platforms shift their sizes by the distance between this and their own
# system default, so 9 stays "body text" rather than "unreadably small".
BODY_FONT_SIZE = 9

_WINDOWS_FAMILY = "Segoe UI"
_WINDOWS_EMOJI_FAMILY = "Segoe UI Emoji"
# Not in ``font.families()`` -- it is the hidden system font Tk resolves
# ``TkDefaultFont`` to -- but Tk accepts it by name in a font spec.
_MAC_FAMILY = ".AppleSystemUIFont"
_MAC_EMOJI_FAMILY = "Apple Color Emoji"
_LINUX_FAMILY = "TkDefaultFont"

# Monospace, for the trigger columns.
_MONO_FAMILIES = {
    "windows": "Consolas",
    "darwin": "Menlo",
    "linux": "TkFixedFont",
}

# The toolbar's glyph buttons. Windows needs the dedicated symbol face; the
# macOS system font already carries the glyphs.
_SYMBOL_FAMILIES = {
    "windows": "Segoe UI Symbol",
    "darwin": _MAC_FAMILY,
    "linux": _LINUX_FAMILY,
}


class Theme:
    """A resolved palette plus the font family/size shift for this platform."""

    __slots__ = (
        "kind", "system", "family", "emoji_family", "mono_family", "symbol_family",
        "size_delta",
        "surface", "surface_alt", "surface_alt_active", "surface_hover",
        "card", "field", "field_hover",
        "text", "text_strong", "text_muted", "text_on_accent",
        "border", "divider",
        "accent", "accent_active", "link", "warning", "success",
        "select_bg", "select_fg", "text_native",
    )

    def __init__(self, kind, system, family, emoji_family, mono_family,
                 symbol_family, size_delta, colors):
        self.kind = kind
        self.system = system
        self.family = family
        self.emoji_family = emoji_family
        self.mono_family = mono_family
        self.symbol_family = symbol_family
        self.size_delta = size_delta
        for name, value in colors.items():
            setattr(self, name, value)

    def font(self, size=BODY_FONT_SIZE, weight=None):
        """Return a font spec tuple for the GUI's shared family."""
        return _spec(self.family, size + self.size_delta, weight)

    def emoji_font(self, size=BODY_FONT_SIZE, weight=None):
        return _spec(self.emoji_family, size + self.size_delta, weight)

    def mono_font(self, size=BODY_FONT_SIZE, weight=None):
        return _spec(self.mono_family, size + self.size_delta, weight)

    @property
    def is_dark(self):
        return self.kind == "dark"

    def entry_colors(self):
        """Colors every text-entry widget needs so Aqua cannot theme it blind.

        A ``tk.Entry``/``tk.Text`` that sets neither ``bg`` nor ``fg`` inherits
        the system appearance while its parent frame carries an explicit color;
        that mismatch is what renders as a black box in dark mode.

        Empty off macOS, and that is the point: Win32's own defaults for these
        widgets are already right (system window background, system window
        text, the user's highlight color). Pinning them there would swap the
        user's selection color for the app's blue -- a Windows regression for
        no gain.
        """
        if self.system != "darwin":
            return {}
        return {
            "bg": self.field,
            "fg": self.text,
            "insertbackground": self.text,
            "selectbackground": self.select_bg,
            "selectforeground": self.select_fg,
            "disabledbackground": self.surface_alt,
            "disabledforeground": self.text_muted,
        }

    def text_colors(self):
        """:meth:`entry_colors` for ``tk.Text``, which spells 'disabled' differently."""
        colors = self.entry_colors()
        if not colors:
            return colors
        colors.pop("disabledbackground", None)
        colors.pop("disabledforeground", None)
        colors["inactiveselectbackground"] = self.select_bg
        return colors

    def listbox_colors(self):
        """See :meth:`entry_colors` -- macOS only, for the same reason."""
        if self.system != "darwin":
            return {}
        return {
            "bg": self.field,
            "fg": self.text,
            "selectbackground": self.select_bg,
            "selectforeground": self.select_fg,
        }

    def plain_button_colors(self):
        """Foreground for buttons that keep the platform's native face.

        Empty off macOS: Windows' own default already is the system button
        text color, and overriding it is the one thing this change must not do.
        Aqua leaves those buttons with Tk's literal ``Black`` default, which is
        what puts black titles on a dark-mode button in the manager window.
        """
        if self.system != "darwin":
            return {}
        return {"fg": self.text_native, "activeforeground": self.text_native}

    def checkbutton_colors(self, bg):
        """Colors for a checkbox sitting on ``bg``.

        ``selectcolor`` is macOS-only: Win32's default for the indicator is
        already the system window color.
        """
        colors = {
            "bg": bg,
            "fg": self.text_native,
            "activebackground": bg,
            "activeforeground": self.text_native,
        }
        if self.system == "darwin":
            colors["selectcolor"] = self.field
        return colors

    def button_colors(self, accent=False):
        if accent:
            return {
                "bg": self.accent,
                "fg": self.text_on_accent,
                "activebackground": self.accent_active,
                "activeforeground": self.text_on_accent,
            }
        return {
            "bg": self.surface_alt,
            "fg": self.text_native,
            "activebackground": self.surface_alt_active,
            "activeforeground": self.text_native,
        }


def _spec(family, size, weight=None):
    return (family, size) if weight is None else (family, size, weight)


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

# The literals the manager GUI shipped with. Windows keeps these exactly.
_LIGHT = {
    "surface": "#F4F6FA",
    "surface_alt": "#E7ECF5",
    "surface_alt_active": "#D9E2F2",
    "surface_hover": "#E6E9EF",
    "card": "#FFFFFF",
    "field": "#FFFFFF",
    "field_hover": "#E8EEF9",
    "text": "#1F2937",
    "text_strong": "#374151",
    "text_muted": "#5B6472",
    "text_on_accent": "#FFFFFF",
    "border": "#D7DEE8",
    "divider": "#C8CDD6",
    "accent": "#265CFF",
    "accent_active": "#1a4fd4",
    "link": "#2D5BD1",
    "warning": "#B45309",
    "success": "#166534",
    "select_bg": "#265CFF",
    "select_fg": "#FFFFFF",
    # Foreground for widgets the pre-change GUI left uncolored. Resolved to
    # each platform's own default so filling it in changes nothing there.
    "text_native": "#1F2937",
}

# Win32's defaults for the widgets this GUI leaves uncolored (tkWinDefault.h).
# Naming them explicitly is a no-op on Windows and keeps the seam honest.
_WINDOWS_NATIVE = {
    "text_native": "SystemButtonText",
}

# Aqua exposes most of these as dynamic system colors that repaint themselves
# when the appearance changes -- but only the *opaque* ones survive the trip
# through Tk. ``systemSecondaryLabelColor``, ``systemSeparatorColor`` and
# ``systemPlaceholderTextColor`` all carry an alpha channel that Tk discards,
# yielding pure white in dark mode; those tokens are fixed grays instead.
_MAC_SYSTEM = {
    "surface": "systemWindowBackgroundColor",
    "card": "systemTextBackgroundColor",
    "field": "systemTextBackgroundColor",
    "text": "systemTextColor",
    "text_strong": "systemTextColor",
    "select_bg": "systemSelectedTextBackgroundColor",
    "select_fg": "systemTextColor",
}

_MAC_NATIVE = {
    "text_native": "systemTextColor",
}

_MAC_LIGHT_OVERRIDES = {
    # Apple's neutral gray: legible against both the light and dark surfaces.
    "text_muted": "#6E6E73",
}

_MAC_DARK_OVERRIDES = {
    "surface_alt": "#2C2C2E",
    "surface_alt_active": "#3A3A3C",
    "surface_hover": "#3A3A3C",
    "field_hover": "#2C2C2E",
    "text_muted": "#98989D",
    "border": "#48484A",
    "divider": "#48484A",
    # The light-mode blues lose contrast against a dark surface.
    "link": "#6BA0FF",
    "warning": "#E0A458",
    "success": "#4ADE80",
}


def palette(kind, system=None):
    """Return the color token map for ``kind`` in {'windows', 'light', 'dark'}.

    Pure: no Tk, no platform probing. ``'windows'`` returns the shipped
    literals untouched; it is also what Linux gets, since Aqua's color names
    do not resolve there. ``system`` only selects the platform's native
    defaults for the ``*_native`` tokens.
    """
    colors = dict(_LIGHT)
    if kind == "windows":
        if system == "windows":
            colors.update(_WINDOWS_NATIVE)
        return colors
    colors.update(_MAC_SYSTEM)
    colors.update(_MAC_NATIVE)
    colors.update(_MAC_DARK_OVERRIDES if kind == "dark" else _MAC_LIGHT_OVERRIDES)
    return colors


def font_family(system=None):
    system = system or current_os()
    if system == "windows":
        return _WINDOWS_FAMILY
    if system == "darwin":
        return _MAC_FAMILY
    return _LINUX_FAMILY


def emoji_family(system=None):
    system = system or current_os()
    if system == "windows":
        return _WINDOWS_EMOJI_FAMILY
    if system == "darwin":
        return _MAC_EMOJI_FAMILY
    return _LINUX_FAMILY


def mono_family(system=None):
    return _MONO_FAMILIES.get(system or current_os(), _MONO_FAMILIES["linux"])


def symbol_family(system=None):
    return _SYMBOL_FAMILIES.get(system or current_os(), _SYMBOL_FAMILIES["linux"])


def size_delta(system=None, default_size=None):
    """Shift between the Windows point scale and this platform's system size.

    Windows is the reference (0). Elsewhere the GUI's body size is pinned to
    the platform's own ``TkDefaultFont`` size so a 9 pt Windows label does not
    render two points below every native control around it.
    """
    if (system or current_os()) == "windows" or not default_size:
        return 0
    return int(default_size) - BODY_FONT_SIZE


def ttk_theme_preference(system=None):
    """ttk themes to try, best first. The last is Tk's built-in fallback."""
    system = system or current_os()
    if system == "windows":
        return ("vista", "winnative", "default")
    if system == "darwin":
        return ("aqua", "clam", "default")
    return ("clam", "default")


def apply_ttk_theme(style, system=None):
    """Select the best available ttk theme. Returns the theme actually in use."""
    try:
        available = set(style.theme_names())
    except Exception:
        return None
    for name in ttk_theme_preference(system):
        if name not in available:
            continue
        try:
            style.theme_use(name)
            return name
        except Exception:
            continue
    try:
        return style.theme_use()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Runtime resolution
# ---------------------------------------------------------------------------

def appearance_kind(luminance):
    """Classify a window-background luminance (0..1) as 'light' or 'dark'."""
    return "dark" if luminance < 0.5 else "light"


def _relative_luminance(rgb16):
    # ``winfo_rgb`` answers in 16-bit channels; a plain average is enough to
    # tell Aqua's near-black window background from its near-white one.
    return sum(rgb16) / (3.0 * 65535.0)


def _probe_kind(widget, system):
    if system != "darwin":
        # Linux takes the literal palette too: Aqua's system color names do not
        # exist on X11 and Tk raises on an unknown color.
        return "windows"
    try:
        return appearance_kind(
            _relative_luminance(widget.winfo_rgb("systemWindowBackgroundColor"))
        )
    except Exception:
        # An appearance we cannot read is not a reason to ship an unreadable
        # window: the light palette is the historical behavior.
        return "light"


def _probe_default_size(widget):
    try:
        return int(tkfont.nametofont("TkDefaultFont", root=widget).actual("size"))
    except Exception:
        return None


def build_theme(kind, system=None, default_size=None):
    """Assemble a :class:`Theme`. Pure given ``kind``/``system``/``default_size``."""
    system = system or current_os()
    return Theme(
        kind=kind,
        system=system,
        family=font_family(system),
        emoji_family=emoji_family(system),
        mono_family=mono_family(system),
        symbol_family=symbol_family(system),
        size_delta=size_delta(system, default_size),
        colors=palette(kind, system),
    )


_current = None


def bind(widget=None, system=None):
    """Resolve the theme against ``widget`` and cache it. Returns the theme.

    Called by every top-level window builder, so a window opened after the user
    switched appearance is built from the new palette.
    """
    global _current
    system = system or current_os()
    if widget is None:
        # No widget means no appearance probe; never guess dark, because
        # guessing wrong is exactly the unreadable case being fixed.
        _current = build_theme("light" if system == "darwin" else "windows", system)
        return _current
    _current = build_theme(
        _probe_kind(widget, system), system, _probe_default_size(widget)
    )
    return _current


def theme():
    """Return the cached theme, resolving a widget-free default on first use."""
    if _current is None:
        return bind(None)
    return _current


def reset():
    """Drop the cached theme (tests)."""
    global _current
    _current = None


def ui_font(size=BODY_FONT_SIZE, weight=None):
    return theme().font(size, weight)


def emoji_font(size=BODY_FONT_SIZE, weight=None):
    return theme().emoji_font(size, weight)


def mono_font(size=BODY_FONT_SIZE, weight=None):
    return theme().mono_font(size, weight)
