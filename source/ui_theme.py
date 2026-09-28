"""Per-OS palette, appearance preference and font resolution for Tk windows.

The manager GUI was written Windows-first with a hardcoded light palette and
Windows fonts everywhere. On macOS that produced unreadable windows: Aqua themes
the widgets the app leaves uncolored according to the *system* appearance, so a
dark-mode ``tk.Entry`` renders black-on-black inside a ``#F4F6FA`` frame, and
``Segoe UI`` silently substitutes to a different font with different metrics.

This module is the seam. Call sites ask for a semantic token
(``theme().surface``, ``theme().text``) and a size (``ui_font(9, "bold")``)
instead of naming a color or a font family:

* **Windows** resolves to the opaque Windows Design System 1.0.0 palette and
  follows the user's app-theme preference by default. The light palette keeps
  the native selection behavior of controls the app does not paint itself.
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

The user's appearance choice (``system``/``light``/``dark``, persisted as the
``appearance`` setting) is module state set once via :func:`set_preference`,
not a ``bind`` argument, so every dialog that re-binds against its own parent
keeps the same appearance as the manager.
"""

import ctypes
from tkinter import font as tkfont
from tkinter import ttk

from platform_support import current_os
from i18n import N_


# The GUI's body size, in the Windows point scale every ``font=`` call uses.
# Other platforms shift their sizes by the distance between this and their own
# system default, so the body role stays readable across native themes.
BODY_FONT_SIZE = 10
# The rest of the Windows 11 type ramp in the same scale: Caption (12 px),
# Subtitle (for panes and cards) and Title (for pages), the last two
# semibold. Nothing in the GUI goes below the caption size.
CAPTION_FONT_SIZE = 9
SUBTITLE_FONT_SIZE = 12
TITLE_FONT_SIZE = 16
# From here up, Windows switches to the variable font's display optical size.
DISPLAY_FONT_SIZE = 14

# Tk names the Windows 11 variable font per optical size and weight; plain
# "Segoe UI Variable" is not a family at all and silently resolves to Arial.
# Windows 10 has no variable font, so it gets the static Segoe UI faces.
# Semibold is a separate family in both: asking Tk for "bold" would synthesize
# a heavier weight than Windows itself uses for headings.
_WINDOWS_11_FAMILIES = {
    "text": "Segoe UI Variable Text",
    "text_strong": "Segoe UI Variable Text Semibold",
    "display": "Segoe UI Variable Display",
    # GDI truncates family names to 31 characters; this is the real name.
    "display_strong": "Segoe UI Variable Display Semib",
}
_WINDOWS_10_FAMILIES = {
    "text": "Segoe UI",
    "text_strong": "Segoe UI Semibold",
    "display": "Segoe UI",
    "display_strong": "Segoe UI Semibold",
}
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
        "kind", "system", "preference", "family", "strong_family",
        "display_family", "display_strong_family", "emoji_family", "mono_family",
        "symbol_family", "size_delta",
        "surface", "surface_alt", "surface_alt_active",
        "card", "field",
        "control", "control_hover", "control_active",
        "control_stroke", "control_stroke_bottom", "stroke_strong",
        "card_border", "scrollbar_thumb",
        "text", "text_strong", "text_muted", "text_on_accent",
        "border", "divider",
        "accent", "accent_hover", "accent_active", "danger", "focus_ring",
        "link", "warning", "success",
        "select_bg", "select_fg", "text_native", "tab_unselected_fg",
        "space_xs", "space_sm", "space_md", "space_lg", "space_xl",
        "tree_row_height",
    )

    def __init__(self, kind, system, family, emoji_family, mono_family,
                 symbol_family, size_delta, colors, preference="system",
                 strong_family=None, display_family=None, display_strong_family=None):
        self.kind = kind
        self.system = system
        self.preference = preference
        self.family = family
        # Optional per-role faces (Windows). None means the role reuses
        # ``family``, with "bold" as a weight.
        self.strong_family = strong_family
        self.display_family = display_family or family
        self.display_strong_family = display_strong_family or strong_family
        self.emoji_family = emoji_family
        self.mono_family = mono_family
        self.symbol_family = symbol_family
        self.size_delta = size_delta
        for name, value in colors.items():
            setattr(self, name, value)
        self.space_xs = 4
        self.space_sm = 8
        self.space_md = 12
        self.space_lg = 16
        self.space_xl = 24
        self.tree_row_height = 44

    def font(self, size=BODY_FONT_SIZE, weight=None):
        """Return a font spec tuple for the GUI's shared family."""
        display = size >= DISPLAY_FONT_SIZE
        if weight == "bold" and self.strong_family:
            family = self.display_strong_family if display else self.strong_family
            return _spec(family, size + self.size_delta)
        family = self.display_family if display else self.family
        return _spec(family, size + self.size_delta, weight)

    def caption_font(self):
        return self.font(CAPTION_FONT_SIZE)

    def subtitle_font(self):
        return self.font(SUBTITLE_FONT_SIZE, "bold")

    def title_font(self):
        return self.font(TITLE_FONT_SIZE, "bold")

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

        Empty for the light Windows/Linux palette, and that is the point:
        Win32's own defaults for these widgets are already right there (system
        window background, system window text, the user's highlight color).
        The opaque dark palette needs them painted, because the OS otherwise
        leaves these classic Tk widgets light under light-on-dark text.
        """
        if self.system != "darwin" and not self.is_dark:
            return {}
        return {
            "bg": self.field,
            "fg": self.text,
            "insertbackground": self.text,
            "selectbackground": self.select_bg,
            "selectforeground": self.select_fg,
            "disabledbackground": self.surface_alt,
            "disabledforeground": self.text_muted,
            # Read-only entries otherwise keep Win32's light button face under
            # the light dark-mode text, which makes their value invisible.
            "readonlybackground": self.surface_alt,
        }

    def text_colors(self):
        """:meth:`entry_colors` for ``tk.Text``, which spells 'disabled' differently."""
        colors = self.entry_colors()
        if not colors:
            return colors
        colors.pop("disabledbackground", None)
        colors.pop("disabledforeground", None)
        colors.pop("readonlybackground", None)
        colors["inactiveselectbackground"] = self.select_bg
        return colors

    def listbox_colors(self):
        """See :meth:`entry_colors` for the same native-versus-painted seam."""
        if self.system != "darwin" and not self.is_dark:
            return {}
        return {
            "bg": self.field,
            "fg": self.text,
            "selectbackground": self.select_bg,
            "selectforeground": self.select_fg,
        }

    def toolbar_frame_colors(self):
        """``bg`` for the formatting-toolbar frame (and its stacked status row).

        The toolbar belongs to the editor surface, so it always uses ``card``.
        """
        return {"bg": self.card}

    def status_label_options(self):
        """Font and foreground for the format-status label.

        The status is secondary UI, so it shares the app's body family and
        muted semantic color on every platform. The label's ``bg`` is passed
        by the caller (the toolbar's own background).
        """
        return {"font": self.caption_font(), "fg": self.text_muted}

    @property
    def manager_window_size(self):
        """``(geometry, min_width, min_height)`` for the manager window.

        macOS needs a wider default: Aqua's native buttons have a minimum
        width the flat Win32 ones do not, so the editor pane that fits its
        formatting toolbar in 433px on Windows needs ~490px here. Every size
        includes the ~160px navigation sidebar, which took over the height the
        header and tab strip used, so the pages keep their tuned widths.
        """
        if self.system == "darwin":
            return ("1300x760", 1140, 600)
        # X11 font metrics and the taller shared controls need more vertical
        # room (CI, Ubuntu + Xvfb). The expanded Windows shell uses a wider
        # default and minimum; physical desktop verification is still required.
        if self.system == "linux":
            return ("1240x800", 1100, 780)
        return ("1280x800", 1180, 760)

    @property
    def stacked_toolbar_status(self):
        """True where the format status must sit below the toolbar, not beside it.

        Nine native buttons already fill the editor pane on macOS; leaving the
        status label on the same row pushes the last button off the edge.
        """
        return self.system == "darwin"

    def field_chrome(self):
        """Flat one-pixel border for ``tk.Entry``/``tk.Text``, as the manager uses.

        The default sunken relief draws its right and bottom edges white, so
        on a white card the field looked cut off at both.
        """
        return {
            "relief": "flat",
            "highlightthickness": 1,
            "highlightbackground": self.border,
            "highlightcolor": self.focus_ring,
        }



def _spec(family, size, weight=None):
    return (family, size) if weight is None else (family, size, weight)


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

# Windows Design System 1.0.0 opaque surfaces. Tk cannot reproduce Mica or Acrylic
# reliably across platforms, so hierarchy comes from restrained contrast,
# spacing and selection states instead.
_LIGHT = {
    "surface": "#F3F3F3",
    "surface_alt": "#FFFFFF",
    "surface_alt_active": "#DEDEDE",
    "card": "#FFFFFF",
    "field": "#FFFFFF",
    # Windows 11 control fills, flattened over a white card. A neutral
    # button is near-white and separated from its surface by the elevation
    # stroke (lighter sides, darker bottom edge), not by a grey fill.
    "control": "#FBFBFB",
    "control_hover": "#F6F6F6",
    "control_active": "#F5F5F5",
    "control_stroke": "#E5E5E5",
    "control_stroke_bottom": "#C4C4C4",
    # Field underline, checkbox/switch outline and off-state knob.
    "stroke_strong": "#8A8A8A",
    "card_border": "#E5E5E5",
    "scrollbar_thumb": "#8A8A8A",
    "text": "#1A1A1A",
    "text_strong": "#1A1A1A",
    "text_muted": "#5C5C5C",
    "text_on_accent": "#FFFFFF",
    "border": "#D6D6D6",
    "divider": "#D6D6D6",
    "accent": "#005FB8",
    "accent_hover": "#1A6FBF",
    "accent_active": "#004A91",
    "danger": "#A4262C",
    "focus_ring": "#005FB8",
    "link": "#005FB8",
    "warning": "#7A4D00",
    "success": "#0F6B36",
    "select_bg": "#DCEEFF",
    "select_fg": "#1A1A1A",
    # Foreground for widgets the pre-change GUI left uncolored. Resolved to
    # each platform's own default so filling it in changes nothing there.
    "text_native": "#1A1A1A",
    # Unselected notebook-tab label. The selected tab uses the accent token.
    "tab_unselected_fg": "#5C5C5C",
}

# Opaque Windows Design System dark surfaces keep classic Tk predictable on
# Windows and Linux. The light-blue accent uses dark text for contrast.
_DARK = {
    "surface": "#202020",
    "surface_alt": "#333333",
    "surface_alt_active": "#414141",
    "card": "#2B2B2B",
    "field": "#333333",
    "control": "#383838",
    "control_hover": "#3D3D3D",
    "control_active": "#323232",
    "control_stroke": "#454545",
    "control_stroke_bottom": "#3B3B3B",
    "stroke_strong": "#9E9E9E",
    "card_border": "#1C1C1C",
    "scrollbar_thumb": "#9F9F9F",
    "text": "#F5F5F5",
    "text_strong": "#F5F5F5",
    "text_muted": "#C4C4C4",
    "text_on_accent": "#003047",
    "border": "#494949",
    "divider": "#494949",
    "accent": "#60CDFF",
    "accent_hover": "#5BBBE9",
    "accent_active": "#A1E2FF",
    "danger": "#FFB4B8",
    "focus_ring": "#75D5FF",
    "link": "#75D5FF",
    "warning": "#FFD479",
    "success": "#8EDBA5",
    "select_bg": "#153F54",
    "select_fg": "#F5F5F5",
    "text_native": "#F5F5F5",
    "tab_unselected_fg": "#C4C4C4",
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
    "tab_unselected_fg": "systemTextColor",
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
    "control": "#3A3A3C",
    "control_active": "#48484A",
    "text_muted": "#98989D",
    "border": "#48484A",
    "divider": "#48484A",
    # The light-mode blues lose contrast against a dark surface.
    "link": "#6BA0FF",
    "warning": "#E0A458",
    "success": "#4ADE80",
    "danger": "#FF6961",
    "focus_ring": "#6BA0FF",
    # Only the Fluent controls (Windows/Linux) read these; keep the map
    # coherent anyway so no light literal leaks into a dark palette.
    **{token: _DARK[token] for token in (
        "control_hover", "control_stroke", "control_stroke_bottom",
        "stroke_strong", "card_border", "scrollbar_thumb",
    )},
}


def palette(kind, system=None):
    """Return the color token map for ``kind`` in {'windows', 'light', 'dark'}.

    Pure: no Tk, no platform probing. Off macOS, ``'windows'``/``'light'``
    return the opaque Fluent palette and ``'dark'`` the opaque dark one;
    Linux takes the same literals because Aqua's color names do not resolve
    there. With no ``system``, ``'light'``/``'dark'`` keep their historical
    meaning: the macOS Aqua maps.
    """
    if system is None and kind in {"light", "dark"}:
        system = "darwin"
    if system != "darwin":
        if kind == "dark":
            return dict(_DARK)
        colors = dict(_LIGHT)
        if system == "windows":
            colors.update(_WINDOWS_NATIVE)
        return colors
    colors = dict(_LIGHT)
    colors.update(_MAC_SYSTEM)
    colors.update(_MAC_NATIVE)
    colors.update(_MAC_DARK_OVERRIDES if kind == "dark" else _MAC_LIGHT_OVERRIDES)
    return colors


def windows_font_families(available=None):
    """The Segoe faces for each text role, picked from the installed families.

    ``available`` is ``font.families()`` from a live interpreter. Without it
    the answer is the Windows 10 set, which every supported Windows has.
    """
    if available is not None and _WINDOWS_11_FAMILIES["text"] in available:
        return dict(_WINDOWS_11_FAMILIES)
    return dict(_WINDOWS_10_FAMILIES)


def font_family(system=None, available=None):
    system = system or current_os()
    if system == "windows":
        return windows_font_families(available)["text"]
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
    the platform's own ``TkDefaultFont`` size so a 10 pt Windows label does not
    render two points below every native control around it.
    """
    if (system or current_os()) == "windows" or not default_size:
        return 0
    return int(default_size) - BODY_FONT_SIZE


def ttk_theme_preference(system=None):
    """ttk themes to try on macOS, best first. The last is Tk's built-in fallback.

    Windows and Linux do not choose from Tk's themes: they get the Fluent
    theme built by :mod:`ui_widgets`.
    """
    if (system or current_os()) == "darwin":
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


def prepare_window(window, resolved=None):
    """Theme a new Toplevel: ttk theme, popdown defaults, title bar.

    ttk styles and the option database belong to the shared interpreter, not
    to a window, so a dialog opened before the manager (a form at expansion
    time) would otherwise get another palette's controls inside its window.
    Returns the ttk theme in use.
    """
    ui = resolved or theme()
    if ui.system == "darwin":
        name = apply_ttk_theme(ttk.Style(window), ui.system)
    else:
        import ui_widgets  # builds on this module's tokens

        name = ui_widgets.install(window, ui)
    apply_option_defaults(window, ui)
    if ui.system == "windows":
        # A withdrawn Toplevel has no Win32 frame yet; ask again once mapped.
        apply_window_chrome(window, ui)
        window.bind(
            "<Map>",
            lambda event: apply_window_chrome(window, ui) if event.widget is window else None,
            add="+",
        )
    return name


def apply_option_defaults(root, resolved=None):
    """Point Tk's option database at the palette for widgets the app never builds.

    The ttk Combobox popdown is a classic ``tk.Listbox`` Tk creates on demand,
    so no call site can color it. The database is per-root and outlives a
    window, which is why this also *resets* the light values after a dark
    session rather than only setting dark ones.
    """
    ui = resolved or theme()
    if ui.system == "darwin" and not ui.is_dark:
        return
    if ui.system == "windows" and not ui.is_dark:
        values = ("SystemWindow", "SystemWindowText", "SystemHighlight", "SystemHighlightText")
    else:
        values = (ui.field, ui.text, ui.select_bg, ui.select_fg)
    for option, value in zip(
        ("background", "foreground", "selectBackground", "selectForeground"), values,
    ):
        root.option_add(f"*TCombobox*Listbox.{option}", value)
    # Tk's idle focus ring around a Listbox is near-white; on the dark cards it
    # draws a bright frame. Call sites that pass their own ring still win.
    if ui.is_dark:
        ring = (ui.border, ui.focus_ring)
    elif ui.system == "windows":
        ring = ("SystemButtonFace", "SystemWindowFrame")
    else:
        ring = ("#d9d9d9", "#000000")  # Tk's X11 defaults
    root.option_add("*Listbox.highlightBackground", ring[0])
    root.option_add("*Listbox.highlightColor", ring[1])


def apply_window_chrome(window, resolved=None):
    """Ask Windows 11 for a title bar matching the palette. Returns success.

    Without it a dark window keeps the white system caption. Older Windows
    builds reject attribute 20; that is a cosmetic loss, never an error.
    """
    ui = resolved or theme()
    if ui.system != "windows":
        return False
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        enabled = ctypes.c_int(1 if ui.is_dark else 0)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled),  # DWMWA_USE_IMMERSIVE_DARK_MODE
        )
        return result == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Appearance preference
# ---------------------------------------------------------------------------

APPEARANCE_CHOICES = ("system", "light", "dark")

# PT-BR copy for the Configurações > Aparência card, shared with Snipvoice.
APPEARANCE_LABELS = {
    "system": N_("Sistema"),
    "light": N_("Claro"),
    "dark": N_("Escuro"),
}
APPEARANCE_STATUS = {
    "system": N_("Segue o tema do sistema."),
    "light": N_("Tema claro fixo."),
    "dark": N_("Tema escuro fixo."),
}

_preference = "system"


def normalize_preference(value):
    """Return one of ``system``, ``light`` or ``dark`` for persisted input."""
    return value if value in APPEARANCE_CHOICES else "system"


def set_preference(value):
    """Record the user's appearance choice for every later :func:`bind`."""
    global _preference
    _preference = normalize_preference(value)
    return _preference


def preference():
    return _preference


def _windows_apps_use_light_theme():
    """Read the Windows app-theme switch; ``None`` when it cannot be read."""
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return bool(value)
    except (ImportError, OSError, TypeError, ValueError):
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
    if system == "windows":
        # Only an explicit "apps use dark" answer selects dark; an unreadable
        # key keeps the light palette the app always shipped.
        return "dark" if _windows_apps_use_light_theme() is False else "windows"
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


# Installed font families, probed once: enumerating them costs a few
# milliseconds and fonts do not appear mid-session in practice.
_font_families = None


def _probe_font_families(widget):
    global _font_families
    if _font_families is None:
        try:
            _font_families = frozenset(tkfont.families(widget))
        except Exception:
            return None
    return _font_families


def build_theme(kind, system=None, default_size=None, preference="system",
                font_families=None):
    """Assemble a :class:`Theme`. Pure given its arguments.

    macOS "system" mode keeps Aqua's dynamic color names. A fixed light/dark
    choice there must use the opaque palette instead; otherwise Aqua resolves
    those names from the OS appearance and silently overrides the user.
    ``font_families`` is the installed set, which picks the Windows faces.
    """
    system = system or current_os()
    preference = normalize_preference(preference)
    colors = palette(kind, system)
    if system == "darwin" and preference != "system":
        colors = dict(_DARK if kind == "dark" else _LIGHT)
        colors.update(_MAC_NATIVE)
    faces = windows_font_families(font_families) if system == "windows" else {}
    return Theme(
        kind=kind,
        system=system,
        family=font_family(system, font_families),
        emoji_family=emoji_family(system),
        mono_family=mono_family(system),
        symbol_family=symbol_family(system),
        size_delta=size_delta(system, default_size),
        colors=colors,
        preference=preference,
        strong_family=faces.get("text_strong"),
        display_family=faces.get("display"),
        display_strong_family=faces.get("display_strong"),
    )


_current = None


def bind(widget=None, system=None):
    """Resolve the theme against ``widget`` and cache it. Returns the theme.

    Called by every top-level window builder, so a window opened after the user
    switched appearance is built from the new palette.
    """
    global _current
    system = system or current_os()
    chosen = _preference
    if chosen == "dark":
        kind = "dark"
    elif chosen == "light":
        kind = "light" if system == "darwin" else "windows"
    elif widget is None:
        # No widget means no appearance probe; never guess dark, because
        # guessing wrong is exactly the unreadable case being fixed.
        kind = "light" if system == "darwin" else "windows"
    else:
        kind = _probe_kind(widget, system)
    default_size = _probe_default_size(widget) if widget is not None else None
    families = (
        _probe_font_families(widget)
        if widget is not None and system == "windows" else None
    )
    _current = build_theme(
        kind, system, default_size, preference=chosen, font_families=families,
    )
    return _current


def theme():
    """Return the cached theme, resolving a widget-free default on first use."""
    if _current is None:
        return bind(None)
    return _current


def reset():
    """Drop the cached theme and preference (tests)."""
    global _current, _preference
    _current = None
    _preference = "system"


def ui_font(size=BODY_FONT_SIZE, weight=None):
    return theme().font(size, weight)


def emoji_font(size=BODY_FONT_SIZE, weight=None):
    return theme().emoji_font(size, weight)


def mono_font(size=BODY_FONT_SIZE, weight=None):
    return theme().mono_font(size, weight)
