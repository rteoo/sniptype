"""Per-OS palette, appearance preference and font resolution for Tk windows.

The manager GUI was written Windows-first with a hardcoded light palette and
Windows fonts everywhere. On macOS that produced unreadable windows: Aqua themes
the widgets the app leaves uncolored according to the *system* appearance, so a
dark-mode ``tk.Entry`` renders black-on-black inside a ``#F4F6FA`` frame, and
``Segoe UI`` silently substitutes to a different font with different metrics.

This module is the seam. Call sites ask for a semantic token
(``theme().surface``, ``theme().text``) and a size (``ui_font(9, "bold")``)
instead of naming a color or a font family:

* **Windows** resolves to the opaque Teô Personal Design System 2.7.1 Windows
  native family (Ink & Copper): neutral Windows surfaces, the copper primary
  and the family's pixel type roles. Dark is the default appearance. The
  light palette keeps the native selection behavior of controls the app does
  not paint itself.
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
``appearance`` setting; :func:`default_preference` when unset) is module
state set once via :func:`set_preference`, not a ``bind`` argument, so every
dialog that re-binds against its own parent keeps the same appearance as the
manager.
"""

import ctypes
from tkinter import font as tkfont
from tkinter import ttk

from platform_support import current_os
from i18n import N_


# Call sites name a type role by its historical Windows point size, which is
# what every ``font=`` call passes. macOS and Linux shift these sizes by the
# distance between the body size and their own system default, so the body
# role stays readable across native themes.
BODY_FONT_SIZE = 10
# Caption, Subtitle (panes and cards) and Title (pages), the last two
# semibold. Nothing in the GUI goes below the caption size.
CAPTION_FONT_SIZE = 9
SUBTITLE_FONT_SIZE = 12
TITLE_FONT_SIZE = 16
# From here up, the size is a title in the variable font's display optical size.
DISPLAY_FONT_SIZE = 14

# Windows resolves those sizes to the DS 2.7.1 Windows family roles, in pixels
# at 100% scaling (``native/windows/tokens.css``): caption 12, body 14,
# heading 18, title 28. Tk point sizes cannot express 14 px, so the roles are
# negative (pixel) Tk sizes scaled by the display DPI.
TYPE_ROLE_PIXELS = {"caption": 12, "body": 14, "heading": 18, "title": 28}
_ROLE_FOR_SIZE = {
    CAPTION_FONT_SIZE: "caption",
    BODY_FONT_SIZE: "body",
    SUBTITLE_FONT_SIZE: "heading",
    DISPLAY_FONT_SIZE: "title",
    TITLE_FONT_SIZE: "title",
}

# DS 2.7.1 Windows densities as (control height, list row height) in pixels at
# 100% scaling (``native/windows/patterns.md``). Compact is the default.
DENSITY_METRICS = {
    "compact": (32, 32),
    "comfortable": (40, 44),
    "touch": (44, 48),
}
DEFAULT_DENSITY = "compact"
# Aqua rows keep the height they always had: the Windows family density does
# not apply to macOS's native controls.
_MAC_TREE_ROW_HEIGHT = 44

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

# Monospace, for literal triggers and paths only. Windows prefers the
# family's Cascadia Mono (no ligatures), then Cascadia Code, when installed.
_MONO_FAMILIES = {
    "windows": "Consolas",
    "darwin": "Menlo",
    "linux": "TkFixedFont",
}
_WINDOWS_MONO_PREFERENCE = ("Cascadia Mono", "Cascadia Code")

# Segoe Fluent Icons (Windows 11), then Segoe MDL2 Assets (Windows 10); the
# Fluent controls render their icon glyphs from the first one Pillow opens.
ICON_FONT_FILES = ("SegoeIcons.ttf", "segmdl2.ttf")

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
        "symbol_family", "size_delta", "scale", "density",
        "surface", "surface_alt", "surface_alt_active",
        "card", "field",
        "control", "control_hover", "control_active",
        "control_stroke", "control_stroke_bottom", "stroke_strong", "field_border",
        "card_border", "scrollbar_thumb",
        "text", "text_strong", "text_muted", "text_on_accent",
        "border", "divider",
        "accent", "accent_hover", "accent_active", "accent_border", "focus_ring",
        "link", "danger", "danger_bg", "warning", "warning_bg",
        "success", "success_bg", "info", "info_bg",
        "select_bg", "select_fg", "text_native", "overlay",
        "space_xs", "space_sm", "space_md", "space_lg", "space_xl",
        "control_height", "tree_row_height",
    )

    def __init__(self, kind, system, family, emoji_family, mono_family,
                 symbol_family, size_delta, colors, preference="system",
                 strong_family=None, display_family=None, display_strong_family=None,
                 scale=1.0, density=DEFAULT_DENSITY):
        if density not in DENSITY_METRICS:
            raise ValueError(f"unknown density: {density!r}")
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
        # Display pixels per DS pixel: 1.0 at 96 DPI (100%).
        self.scale = scale
        self.density = density
        for name, value in colors.items():
            setattr(self, name, value)
        # Translucent hover/press layers of the Fluent controls: darken in
        # light, lighten in dark.
        self.overlay = _DARK_OVERLAY if kind == "dark" else _LIGHT_OVERLAY
        self.space_xs = 4
        self.space_sm = 8
        self.space_md = 12
        self.space_lg = 16
        self.space_xl = 24
        control, row = DENSITY_METRICS[density]
        self.control_height = self.px(control)
        self.tree_row_height = (
            _MAC_TREE_ROW_HEIGHT if system == "darwin" else self.px(row)
        )

    def px(self, value):
        """``value`` DS pixels as display pixels at this theme's scale."""
        return max(1, round(value * self.scale))

    def _size(self, size):
        """The Tk font size for a call site's historical point ``size``.

        Windows answers the DS pixel role as a negative (pixel) size; a size
        outside the ramp has no role and fails loudly rather than guessing.
        """
        if self.system != "windows":
            return size + self.size_delta
        try:
            role = _ROLE_FOR_SIZE[size]
        except KeyError:
            raise ValueError(f"font size {size!r} has no DS type role") from None
        return -self.px(TYPE_ROLE_PIXELS[role])

    def font(self, size=BODY_FONT_SIZE, weight=None):
        """Return a font spec tuple for the GUI's shared family."""
        display = size >= DISPLAY_FONT_SIZE
        if weight == "bold" and self.strong_family:
            family = self.display_strong_family if display else self.strong_family
            return _spec(family, self._size(size))
        family = self.display_family if display else self.family
        return _spec(family, self._size(size), weight)

    def caption_font(self):
        return self.font(CAPTION_FONT_SIZE)

    def subtitle_font(self):
        return self.font(SUBTITLE_FONT_SIZE, "bold")

    def title_font(self):
        return self.font(TITLE_FONT_SIZE, "bold")

    def emoji_font(self, size=BODY_FONT_SIZE, weight=None):
        return _spec(self.emoji_family, self._size(size), weight)

    def mono_font(self, size=BODY_FONT_SIZE, weight=None):
        return _spec(self.mono_family, self._size(size), weight)

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

# Teô Personal DS 2.7.1, Windows native family (Ink & Copper). Surfaces are
# the family's opaque neutrals (``native/windows/tokens.css``): the canvas and
# navigation sit on ``surface``, collections on ``card``, editing on
# ``field``. Tk cannot reproduce Mica or Acrylic, so hierarchy comes from
# these opaque layers, spacing and selection. Copper marks the primary action
# and selection; it never washes a surface.
_LIGHT = {
    "surface": "#E9E8E7",
    "surface_alt": "#E9E8E7",
    "surface_alt_active": "#E8E6E3",
    "card": "#F6F5F4",
    "field": "#FFFFFF",
    # A neutral button is the content fill inside a 1px field border, as the
    # family's buttons are. Pressed has no DS value; Tk needs one distinct
    # from hover, so it is the hover tone one step darker (an adaptation).
    "control": "#FFFFFF",
    "control_hover": "#E8E6E3",
    "control_active": "#DEDCD8",
    "control_stroke": "#7B8088",
    "control_stroke_bottom": "#7B8088",
    # Field and checkbox/switch outline (WCAG 1.4.11 boundary).
    "stroke_strong": "#7B8088",
    "field_border": "#7B8088",
    "card_border": "#D8D8D8",
    "scrollbar_thumb": "#606060",
    "text": "#202630",
    "text_strong": "#202630",
    "text_muted": "#606060",
    "text_on_accent": "#15100A",
    "border": "#D8D8D8",
    "divider": "#D8D8D8",
    "accent": "#E6A05A",
    "accent_hover": "#D99551",
    "accent_active": "#BE7836",
    # Copper as a mark (nav pill, checked edge, field focus underline): raw
    # copper is under 3:1 on the light surfaces, its deep tone is not.
    "accent_border": "#A0520A",
    "focus_ring": "#263C56",
    "link": "#A0520A",
    "danger": "#9B2C2C",
    "danger_bg": "#FCE8E8",
    "warning": "#7A4A00",
    "warning_bg": "#FFF1D6",
    "success": "#16643B",
    "success_bg": "#E6F6EC",
    "info": "#263C56",
    "info_bg": "#E8EEF5",
    "select_bg": "#E8E6E3",
    "select_fg": "#202630",
    # Foreground for widgets the pre-change GUI left uncolored. Resolved to
    # each platform's own default so filling it in changes nothing there.
    "text_native": "#202630",
}

# The family's dark appearance, the default. Copper keeps its dark label.
_DARK = {
    "surface": "#292929",
    "surface_alt": "#292929",
    "surface_alt_active": "#484848",
    "card": "#232323",
    "field": "#1C1C1E",
    "control": "#1C1C1E",
    "control_hover": "#484848",
    # Tk adaptation, as in the light palette: pressed between rest and hover.
    "control_active": "#3A3A3A",
    "control_stroke": "#999CA3",
    "control_stroke_bottom": "#999CA3",
    "stroke_strong": "#999CA3",
    "field_border": "#999CA3",
    "card_border": "#454545",
    "scrollbar_thumb": "#BCBCBC",
    "text": "#F2EFE9",
    "text_strong": "#F2EFE9",
    "text_muted": "#BCBCBC",
    "text_on_accent": "#15100A",
    "border": "#454545",
    "divider": "#454545",
    "accent": "#E6A05A",
    "accent_hover": "#EDB47C",
    "accent_active": "#CE8845",
    "accent_border": "#E6A05A",
    "focus_ring": "#F0C293",
    "link": "#EDB47C",
    "danger": "#FF8A85",
    "danger_bg": "#351718",
    "warning": "#FFD27A",
    "warning_bg": "#342A17",
    "success": "#73E0A1",
    "success_bg": "#13271D",
    "info": "#ADC1DC",
    "info_bg": "#202E40",
    "select_bg": "#484848",
    "select_fg": "#F2EFE9",
    "text_native": "#F2EFE9",
}

_LIGHT_OVERLAY = "#000000"
_DARK_OVERLAY = "#FFFFFF"

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
    "control": "#3A3A3C",
    "control_active": "#48484A",
    "text_muted": "#98989D",
    "border": "#48484A",
    "divider": "#48484A",
    # The light link and focus tones lose contrast against a dark surface;
    # these are the DS dark ones.
    "link": "#EDB47C",
    "warning": "#E0A458",
    "success": "#4ADE80",
    "danger": "#FF6961",
    "focus_ring": "#F0C293",
    # Only the Fluent controls (Windows/Linux) read these; keep the map
    # coherent anyway so no light literal leaks into a dark palette.
    **{token: _DARK[token] for token in (
        "control_hover", "control_stroke", "control_stroke_bottom",
        "stroke_strong", "field_border", "card_border", "scrollbar_thumb",
        "danger_bg", "warning_bg", "success_bg", "info", "info_bg",
    )},
    # The bar beside the current navigation item is the one copper mark Tk
    # draws on macOS (ui_widgets.set_selected). The light #A0520A would fall
    # under 3:1 on the dark sidebar; the DS dark link tone clears it.
    "accent_border": "#EDB47C",
}


def palette(kind, system=None):
    """Return the color token map for ``kind`` in {'windows', 'light', 'dark'}.

    Pure: no Tk, no platform probing. Off macOS, ``'windows'``/``'light'``
    return the opaque light Windows-family palette and ``'dark'`` the dark one;
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


def mono_family(system=None, available=None):
    """The monospace family; ``available`` is ``font.families()`` (Windows).

    Without it Windows answers Consolas, which every supported Windows has.
    """
    system = system or current_os()
    if system == "windows" and available is not None:
        for family in _WINDOWS_MONO_PREFERENCE:
            if family in available:
                return family
    return _MONO_FAMILIES.get(system, _MONO_FAMILIES["linux"])


def symbol_family(system=None):
    return _SYMBOL_FAMILIES.get(system or current_os(), _SYMBOL_FAMILIES["linux"])


def size_delta(system=None, default_size=None):
    """Shift between the call sites' point scale and this platform's system size.

    Windows does not shift (0): it resolves pixel type roles instead. Elsewhere
    the GUI's body size is pinned to the platform's own ``TkDefaultFont`` size
    so a 10 pt label does not render two points below every native control
    around it.
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

def default_preference(system=None):
    """The appearance an install with no saved (or a malformed) choice gets.

    The DS 2.7.1 Windows family defaults to Dark, with Light and System as
    explicit choices; Linux renders the same family. macOS keeps System:
    Aqua draws its buttons and checkboxes in the OS appearance whatever the
    app picks, so a fixed default would put light bezels on a dark window.
    """
    return "system" if (system or current_os()) == "darwin" else "dark"


_preference = default_preference()


def normalize_preference(value, system=None):
    """Return one of ``system``, ``light`` or ``dark`` for persisted input.

    Anything else (unset, misspelled) is :func:`default_preference`.
    """
    return value if value in APPEARANCE_CHOICES else default_preference(system)


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


def live_system_kind(system=None):
    """The palette kind System resolves to now, when open windows follow the OS.

    Only the System preference on Windows follows a live change: a fixed
    choice never changes, and Aqua redraws its own controls in the OS
    appearance. Read from the registry, so it needs no window. None when
    open windows keep the palette they were built with.
    """
    system = system or current_os()
    if _preference != "system" or system != "windows":
        return None
    return _probe_kind(None, system)


def display_scale(widget):
    """Display pixels per DS pixel for ``widget``'s interpreter: 1.0 at 96 DPI.

    ``tk scaling`` is pixels per point, 4/3 at 100%.
    """
    return float(widget.tk.call("tk", "scaling")) * 72 / 96


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
                font_families=None, scale=1.0):
    """Assemble a :class:`Theme`. Pure given its arguments.

    macOS "system" mode keeps Aqua's dynamic color names. A fixed light/dark
    choice there must use the opaque palette instead; otherwise Aqua resolves
    those names from the OS appearance and silently overrides the user.
    ``font_families`` is the installed set, which picks the Windows faces.
    ``scale`` is display pixels per DS pixel (:func:`display_scale`).
    """
    system = system or current_os()
    preference = normalize_preference(preference, system)
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
        mono_family=mono_family(system, font_families),
        symbol_family=symbol_family(system),
        size_delta=size_delta(system, default_size),
        colors=colors,
        preference=preference,
        strong_family=faces.get("text_strong"),
        display_family=faces.get("display"),
        display_strong_family=faces.get("display_strong"),
        scale=scale,
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
        scale=display_scale(widget) if widget is not None else 1.0,
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
    _preference = default_preference()


def ui_font(size=BODY_FONT_SIZE, weight=None):
    return theme().font(size, weight)


def emoji_font(size=BODY_FONT_SIZE, weight=None):
    return theme().emoji_font(size, weight)


def mono_font(size=BODY_FONT_SIZE, weight=None):
    return theme().mono_font(size, weight)
