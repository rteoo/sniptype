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


# The GUI's body size, in the Windows point scale every ``font=`` call uses.
# Other platforms shift their sizes by the distance between this and their own
# system default, so the body role stays readable across native themes.
BODY_FONT_SIZE = 10

_WINDOWS_FAMILY = "Segoe UI Variable"
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
        "kind", "system", "preference", "family", "emoji_family", "mono_family",
        "symbol_family", "size_delta",
        "surface", "surface_alt", "surface_alt_active", "surface_hover",
        "card", "field", "field_hover",
        "control", "control_active", "control_border",
        "text", "text_strong", "text_muted", "text_on_accent",
        "border", "divider",
        "accent", "accent_active", "danger", "danger_active", "focus_ring",
        "link", "warning", "success",
        "select_bg", "select_fg", "text_native", "tab_unselected_fg",
        "space_xs", "space_sm", "space_md", "space_lg", "space_xl",
        "tree_row_height",
    )

    def __init__(self, kind, system, family, emoji_family, mono_family,
                 symbol_family, size_delta, colors, preference="system"):
        self.kind = kind
        self.system = system
        self.preference = preference
        self.family = family
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

    # Buttons and checkboxes are the widgets Aqua draws *itself*, and it draws
    # them from the appearance rather than from what the app asks for. It
    # ignores ``-background`` outright and keeps its own light bezel, but it
    # does honour ``-foreground`` -- so a well-meant `fg=systemTextColor` puts
    # white text on that light bezel and the button renders as a blank box
    # (seen on macOS 15 / Tk 9.0). Every button color helper therefore answers
    # nothing on macOS: the native control is already correct in both
    # appearances, and the only way to break it is to paint on it.

    def checkbutton_colors(self, bg):
        """Colors for a checkbox sitting on ``bg``. Native on macOS."""
        if self.system == "darwin":
            return {}
        colors = {
            "bg": bg,
            "fg": self.text_native,
            "activebackground": bg,
            "activeforeground": self.text_native,
        }
        if self.is_dark:
            # Win32 paints ``selectcolor`` behind the indicator in *both*
            # states and draws the check mark in ``fg``; the default white
            # box would hide the light mark.
            colors["selectcolor"] = self.field
            colors["disabledforeground"] = self.text_muted
        return colors

    def toolbar_frame_colors(self):
        """``bg`` for the formatting-toolbar frame (and its stacked status row).

        The toolbar belongs to the editor surface, so it always uses ``card``.
        Toolbar buttons receive their own foreground and interaction colors,
        avoiding the old Win32 white-on-white regression.
        """
        return {"bg": self.card}

    def status_label_options(self):
        """Font and foreground for the format-status label.

        The status is secondary UI, so it shares the app's body family and
        muted semantic color on every platform. The label's ``bg`` is passed
        by the caller (the toolbar's own background).
        """
        return {"font": self.font(8), "fg": self.text_muted}

    def toolbar_button_colors(self, bg):
        """Colors for the flat glyph buttons in the formatting toolbar."""
        if self.system == "darwin":
            return {}
        return {
            "bg": bg,
            "fg": self.text_native,
            "activebackground": self.surface_hover,
            "activeforeground": self.text_native,
        }

    def glyph_button_colors(self, bg):
        """Colors for a small icon button sitting on ``bg`` (the ✎ rename)."""
        if self.system == "darwin":
            return {}
        # No activeforeground: the shipped button did not set one, and adding
        # it would change the pressed state on Windows.
        return {
            "bg": bg,
            "fg": self.text_muted,
            "activebackground": self.field_hover,
        }

    def nav_button_colors(self, bg, selected=False):
        """Colors for a section-navigation button sitting on ``bg``. Native on macOS."""
        if self.system == "darwin":
            return {}
        fg = self.accent if selected else self.text_native
        return {
            "bg": bg,
            "fg": fg,
            "activebackground": self.surface_hover,
            "activeforeground": fg,
        }

    def card_options(self):
        """Tk frame options for a settings card: card surface, quiet border.

        Tk has no reliable cross-platform rounded-corner primitive; a one-pixel
        border preserves the hierarchy without faux rounded controls.
        """
        return {
            "bg": self.card,
            "highlightbackground": self.border,
            "highlightthickness": 1,
            "bd": 0,
        }

    def button_width(self, chars):
        """Fixed button width in characters, or 0 to let the button size itself.

        The widths in the GUI were picked against flat Win32 buttons. Aqua's
        native bezel is wider than the text it wraps, so the same numbers
        overflow their pane there and clip the last button in a row (measured:
        the five-button editor row needs 630px in a 433px pane). Natural
        sizing costs Aqua nothing -- its minimum width is already generous --
        and Windows keeps the tuned numbers.
        """
        return 0 if self.system == "darwin" else chars

    @property
    def manager_window_size(self):
        """``(geometry, min_width, min_height)`` for the manager window.

        macOS needs a wider default: Aqua's native buttons have a minimum
        width the flat Win32 ones do not, so the editor pane that fits its
        formatting toolbar in 433px on Windows needs ~490px here.
        """
        if self.system == "darwin":
            return ("1140x760", 980, 600)
        # X11 font metrics need ~24px more than the previous Windows layout
        # (CI, Ubuntu + Xvfb). The expanded Windows shell uses a wider default
        # and minimum; physical desktop verification is still required.
        if self.system == "linux":
            return ("1080x780", 940, 740)
        return ("1180x800", 1020, 760)

    @property
    def stacked_toolbar_status(self):
        """True where the format status must sit below the toolbar, not beside it.

        Nine native buttons already fill the editor pane on macOS; leaving the
        status label on the same row pushes the last button off the edge.
        """
        return self.system == "darwin"

    def button_chrome(self, compact=False):
        """Platform-safe geometry and focus treatment for manager buttons."""
        if self.system == "darwin":
            return {}
        return {
            "relief": "flat",
            "bd": 0,
            "padx": 12 if compact else 16,
            "pady": 6 if compact else 9,
            "highlightthickness": 1,
            # ``control_border``, not the quiet card ``border``: the ring is
            # what separates a neutral button from the card it sits on.
            "highlightbackground": self.control_border,
            "highlightcolor": self.focus_ring,
            "cursor": "hand2",
        }

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

    def button_colors(self, accent=False, danger=False):
        """Colors for the app's tinted buttons. Native on macOS."""
        if self.system == "darwin":
            return {}
        if danger:
            return {
                "bg": self.danger,
                "fg": self.text_on_accent,
                "activebackground": self.danger_active,
                "activeforeground": self.text_on_accent,
            }
        if accent:
            return {
                "bg": self.accent,
                "fg": self.text_on_accent,
                "activebackground": self.accent_active,
                "activeforeground": self.text_on_accent,
            }
        # Neutral buttons used to paint ``surface_alt`` (#FAFAFA), ~1.04:1
        # against the white cards they sit on, so they read as plain text.
        return {
            "bg": self.control,
            "fg": self.text_native,
            "activebackground": self.control_active,
            "activeforeground": self.text_native,
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
    "surface_hover": "#EAEAEA",
    "card": "#FFFFFF",
    "field": "#FFFFFF",
    "field_hover": "#EAEAEA",
    # Product adaptation: neutral button fill and ring stay distinct from
    # both ``surface`` and ``card`` so secondary actions remain visible.
    "control": "#E6E6E6",
    "control_active": "#DEDEDE",
    "control_border": "#767676",
    "text": "#1A1A1A",
    "text_strong": "#1A1A1A",
    "text_muted": "#5C5C5C",
    "text_on_accent": "#FFFFFF",
    "border": "#D6D6D6",
    "divider": "#D6D6D6",
    "accent": "#005FB8",
    "accent_active": "#004A91",
    "danger": "#A4262C",
    "danger_active": "#8B1E24",
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
    "surface_hover": "#383838",
    "card": "#2B2B2B",
    "field": "#333333",
    "field_hover": "#383838",
    "control": "#383838",
    "control_active": "#414141",
    "control_border": "#A0A0A0",
    "text": "#F5F5F5",
    "text_strong": "#F5F5F5",
    "text_muted": "#C4C4C4",
    "text_on_accent": "#003047",
    "border": "#494949",
    "divider": "#494949",
    "accent": "#60CDFF",
    "accent_active": "#A1E2FF",
    "danger": "#FFB4B8",
    "danger_active": "#FFD0D2",
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
    "surface_hover": "#3A3A3C",
    "field_hover": "#2C2C2E",
    "control": "#3A3A3C",
    "control_active": "#48484A",
    "control_border": "#636366",
    "text_muted": "#98989D",
    "border": "#48484A",
    "divider": "#48484A",
    # The light-mode blues lose contrast against a dark surface.
    "link": "#6BA0FF",
    "warning": "#E0A458",
    "success": "#4ADE80",
    "danger": "#FF6961",
    "danger_active": "#FF453A",
    "focus_ring": "#6BA0FF",
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
    the platform's own ``TkDefaultFont`` size so a 10 pt Windows label does not
    render two points below every native control around it.
    """
    if (system or current_os()) == "windows" or not default_size:
        return 0
    return int(default_size) - BODY_FONT_SIZE


def ttk_theme_preference(system=None, dark=False):
    """ttk themes to try, best first. The last is Tk's built-in fallback."""
    system = system or current_os()
    if dark and system != "darwin":
        # Win32's native Vista theme paints light controls whatever colors Tk
        # supplies. Clam is the portable theme that honors them.
        return ("clam", "default")
    if system == "windows":
        return ("vista", "winnative", "default")
    if system == "darwin":
        return ("aqua", "clam", "default")
    return ("clam", "default")


def apply_ttk_theme(style, system=None, resolved=None):
    """Select the best available ttk theme. Returns the theme actually in use."""
    try:
        available = set(style.theme_names())
    except Exception:
        return None
    dark = (resolved or theme()).is_dark
    for name in ttk_theme_preference(system, dark=dark):
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


def configure_clam_colors(style, resolved=None):
    """Paint the ttk widgets the manager uses when running under ``clam``.

    Only the dark palette selects clam off macOS, and clam's defaults are
    near-white bevels, troughs and popdowns that would glare out of every dark
    window. Vista and Aqua ignore these options, so the light and native
    paths are untouched either way.
    """
    ui = resolved or theme()
    style.configure(
        "Manager.TNotebook",
        bordercolor=ui.border, lightcolor=ui.surface, darkcolor=ui.surface,
    )
    style.configure(
        "Manager.TNotebook.Tab",
        bordercolor=ui.border, lightcolor=ui.surface, darkcolor=ui.surface,
    )
    style.map(
        "Manager.TNotebook.Tab",
        lightcolor=[("selected", ui.card)],
        # Clam shrinks and shifts the selected tab (narrower padding plus an
        # ``expand`` inset); keep its geometry identical to its neighbors.
        padding=[("selected", (18, 10))],
        expand=[("selected", (0, 0, 0, 0))],
    )
    style.configure(
        "TCombobox",
        fieldbackground=ui.field,
        background=ui.control,
        foreground=ui.text,
        arrowcolor=ui.text_muted,
        bordercolor=ui.border,
        lightcolor=ui.border,
        darkcolor=ui.border,
        selectbackground=ui.select_bg,
        selectforeground=ui.select_fg,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", ui.field), ("disabled", ui.surface_alt)],
        foreground=[("readonly", ui.text), ("disabled", ui.text_muted)],
        background=[("active", ui.control_active)],
        selectbackground=[("readonly", ui.field)],
        selectforeground=[("readonly", ui.text)],
    )
    for orientation in ("Vertical", "Horizontal"):
        name = f"{orientation}.TScrollbar"
        style.configure(
            name,
            background=ui.control,
            troughcolor=ui.surface,
            bordercolor=ui.surface,
            arrowcolor=ui.text_muted,
            lightcolor=ui.control,
            darkcolor=ui.control,
        )
        # Clam maps a near-white face onto idle states (e.g. an empty list's
        # full-length thumb), overriding the configured background.
        style.map(
            name,
            background=[("pressed", ui.control_active), ("active", ui.control_active),
                        ("!active", ui.control)],
        )
    style.configure(
        "Manager.Treeview", bordercolor=ui.border, lightcolor=ui.card, darkcolor=ui.card,
    )
    style.configure(
        "Manager.Treeview.Heading",
        bordercolor=ui.border, lightcolor=ui.surface_alt, darkcolor=ui.surface_alt,
        relief="flat",
    )
    style.map("Manager.Treeview.Heading", background=[("active", ui.surface_hover)])
    # Unstyled trees (the notification history) use the base style.
    style.configure(
        "Treeview",
        background=ui.card, fieldbackground=ui.card, foreground=ui.text,
        bordercolor=ui.border, lightcolor=ui.card, darkcolor=ui.card,
    )
    style.map(
        "Treeview",
        background=[("selected", ui.select_bg)],
        foreground=[("selected", ui.select_fg)],
    )
    style.configure(
        "Treeview.Heading",
        background=ui.surface_alt, foreground=ui.text_strong,
        bordercolor=ui.border, lightcolor=ui.surface_alt, darkcolor=ui.surface_alt,
        relief="flat",
    )
    style.map("Treeview.Heading", background=[("active", ui.surface_hover)])
    return style


def prepare_window(window, resolved=None):
    """Theme a new Toplevel: ttk theme, clam colors, popdown defaults, title bar.

    ttk styles and the option database belong to the shared interpreter, not
    to a window, so a dialog opened before the manager (a form at expansion
    time) would otherwise get Vista's light controls inside a dark window.
    Returns the ttk theme in use.
    """
    ui = resolved or theme()
    style = ttk.Style(window)
    name = apply_ttk_theme(style, resolved=ui)
    if name == "clam":
        configure_clam_colors(style, ui)
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
    "system": "Sistema",
    "light": "Claro",
    "dark": "Escuro",
}
APPEARANCE_STATUS = {
    "system": "Segue o tema do sistema.",
    "light": "Tema claro fixo.",
    "dark": "Tema escuro fixo.",
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


def build_theme(kind, system=None, default_size=None, preference="system"):
    """Assemble a :class:`Theme`. Pure given its arguments.

    macOS "system" mode keeps Aqua's dynamic color names. A fixed light/dark
    choice there must use the opaque palette instead; otherwise Aqua resolves
    those names from the OS appearance and silently overrides the user.
    """
    system = system or current_os()
    preference = normalize_preference(preference)
    colors = palette(kind, system)
    if system == "darwin" and preference != "system":
        colors = dict(_DARK if kind == "dark" else _LIGHT)
        colors.update(_MAC_NATIVE)
    return Theme(
        kind=kind,
        system=system,
        family=font_family(system),
        emoji_family=emoji_family(system),
        mono_family=mono_family(system),
        symbol_family=symbol_family(system),
        size_delta=size_delta(system, default_size),
        colors=colors,
        preference=preference,
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
    _current = build_theme(kind, system, default_size, preference=chosen)
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
