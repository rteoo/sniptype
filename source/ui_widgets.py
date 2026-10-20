"""Windows 11 (Fluent) ttk theme and the widget factories the GUI builds with.

Tk has no rounded-corner primitive and classic Tk buttons have no hover or
pressed look, which is most of why the manager read as a Windows 95 app. Every
control shape here is therefore a Pillow-drawn image used as a ttk image
element: nine-slice stretched by Tk, drawn once per palette at the display's
scaling, anti-aliased by supersampling.

Only Windows and Linux use it. macOS keeps the native Aqua widgets it always
had: each factory returns the classic Tk widget there, uncolored. Aqua draws
buttons and checkboxes itself, correctly in both appearances; it ignores
``-background`` but honors ``-foreground``, so painting one is how a label
turns invisible on its light bezel (macOS 15 / Tk 9.0).

Two Tk behaviors shape the design, both measured on Tk 8.6.15:

* A ttk image element is composited over the *style's* background, not over
  the parent widget, so a rounded corner shows the style background. Each
  factory therefore uses a per-surface style (``Bg<RRGGBB>.<base>``) whose
  background is the parent's color; ttk falls back to ``<base>`` for the
  layout and every other option.
* An element cannot be redefined once created, so each palette is its own
  theme (``sniptype-fluent-light`` / ``-dark``) created once per interpreter;
  an appearance change rebuilds the manager and selects the other theme.

The images of a theme live as long as the root and are released while it is
destroyed. A ``PhotoImage`` deletes its Tk image when garbage-collected, and a
collection on a thread other than the GUI thread can abort Tcl (see the
``gc.collect()`` calls around the manager's teardown).
"""

import base64
import io
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFont

import ui_theme
from i18n import _

# Supersampling factor for anti-aliased edges.
_SS = 4
# Side of the tiled middle of every nine-slice image, in pixels.
_SLICE_MIDDLE = 128

# Glyphs of the icon fonts in ``ui_theme.ICON_FONT_FILES``; both carry every
# codepoint below. Elsewhere there is no icon font and controls show their
# text alone.
ICONS = {
    "add": "\ue710",
    "bell": "\uea8f",
    "bold": "\ue8dd",
    "chevron_down": "\ue70d",
    "clear_format": "\uea99",
    "code": "\ue943",
    "copy": "\ue8c8",
    "delete": "\ue74d",
    "down": "\ue74b",
    "document": "\ue8a5",
    "edit": "\ue70f",
    "error": "\ue783",
    "export": "\ue898",
    "favorite": "\ue734",
    "folder": "\ue838",
    "form": "\ue9d5",
    "history": "\ue81c",
    "import": "\ue896",
    "info": "\ue946",
    "italic": "\ue8db",
    "keyboard": "\ue765",
    "lightning": "\ue945",
    "more": "\ue712",
    "pause": "\ue769",
    "play": "\ue768",
    "preview": "\ue7b3",
    "refresh": "\ue72c",
    "rename": "\ue8ac",
    "restore": "\ue777",
    "save": "\ue74e",
    "settings": "\ue713",
    "strike": "\uede0",
    "tag": "\ue8ec",
    "underline": "\ue8dc",
    "up": "\ue74a",
    "warning": "\ue7ba",
}

VARIANTS = ("standard", "accent", "danger", "subtle", "nav", "toolbar")

_BUTTON_STYLES = {
    "standard": "TButton",
    "accent": "Accent.TButton",
    "danger": "Danger.TButton",
    "subtle": "Subtle.TButton",
    "nav": "Nav.TButton",
    "toolbar": "Toolbar.TButton",
}


def uses_fluent(ui=None):
    """True where the GUI is built from this theme (everywhere but macOS)."""
    return (ui or ui_theme.theme()).system != "darwin"


def theme_name(ui):
    return "sniptype-fluent-dark" if ui.is_dark else "sniptype-fluent-light"


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

def _rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))


def _rgba(color, alpha=1.0):
    return (*_rgb(color), round(255 * alpha))


def mix(first, second, amount):
    """``first`` moved ``amount`` (0..1) of the way to ``second``, as #RRGGBB."""
    a, b = _rgb(first), _rgb(second)
    return "#" + "".join(
        f"{round(x + (y - x) * amount):02X}" for x, y in zip(a, b)
    )


def resolve_color(widget, color):
    """Any Tk color (a system name included) as ``#RRGGBB``."""
    red, green, blue = widget.winfo_rgb(color)
    return f"#{red >> 8:02X}{green >> 8:02X}{blue >> 8:02X}"


def surface_of(widget):
    """The color a child of ``widget`` sits on, as ``#RRGGBB``.

    Themed containers record it in ``surface_color``; classic Tk frames and
    toplevels answer ``-background``.
    """
    color = getattr(widget, "surface_color", None)
    if color is None:
        color = widget.cget("background")
    return resolve_color(widget, color)


# ---------------------------------------------------------------------------
# Image drawing
# ---------------------------------------------------------------------------

_CLEAR = (0, 0, 0, 0)


class _Artist:
    """Draws the theme's images at one display scale and keeps them alive.

    Tk cannot paint outside a widget, so a focus ring drawn outside a face
    (outset, as Windows draws it) needs room inside the widget: every
    focusable face reserves ``margin`` transparent pixels around itself, the
    ring takes the outer ``ring`` of them, and the rest is a gap of the
    surface the style sits on. The gap is what separates the ring from a
    copper fill, which the dark ring alone matches at only 1.35:1.
    """

    def __init__(self, master, scale):
        self.master = master
        self.scale = scale
        self.images = []
        self.ring = self.px(2)
        self.margin = self.ring + self.px(1)

    def px(self, value):
        return max(1, round(value * self.scale))

    def photo(self, image):
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        photo = tk.PhotoImage(
            master=self.master,
            data=base64.b64encode(buffer.getvalue()).decode("ascii"),
        )
        self.images.append(photo)
        return photo

    @staticmethod
    def canvas(width, height):
        return Image.new("RGBA", (width * _SS, height * _SS), (0, 0, 0, 0))

    @staticmethod
    def rounded(draw, box, radius, fill):
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            return
        draw.rounded_rectangle(
            (round(x0 * _SS), round(y0 * _SS), round(x1 * _SS) - 1, round(y1 * _SS) - 1),
            radius=round(max(0, radius) * _SS),
            fill=fill,
        )

    def finish(self, image, width, height):
        # A box filter averages each supersampled cell exactly; Lanczos rings
        # at the edges and shifts a one-pixel stroke off its token color.
        return self.photo(image.resize((width, height), Image.BOX))

    def slice_size(self, radius, margin=0):
        """Nine-slice border and image side for a shape of ``radius``.

        ttk *tiles* the middle of an image element rather than stretching
        it, and every tile of an image with alpha is a separate blended draw
        (a read-back of the window on Windows). The middle is therefore wide:
        a 2px one turned a card into tens of thousands of draws and one
        manager layout pass into ~30 seconds.
        """
        border = margin + radius + self.px(2)
        return border, 2 * border + _SLICE_MIDDLE

    def focus_ring(self, draw, box, radius, color):
        """The outset ring in the outer ``ring`` pixels of ``box``.

        Clears what it encloses: the gap stays transparent, so it shows the
        style's surface.
        """
        x0, y0, x1, y1 = box
        ring = self.ring
        self.rounded(draw, box, radius, color)
        self.rounded(draw, (x0 + ring, y0 + ring, x1 - ring, y1 - ring), radius - ring, _CLEAR)

    def face(self, radius, fill, stroke=None, bottom=None, bottom_width=None,
             focus=None, margin=0):
        """A rounded control face; returns ``(image, slice border)``.

        ``stroke`` outlines it; ``bottom`` recolors the bottom edge (the
        underline of a text field), which ``bottom_width`` thickens.
        ``margin`` reserves a transparent band around the face; ``focus``
        draws the focus ring in it (see the class docstring).
        """
        if focus is not None and margin < self.margin:
            raise ValueError("a focus ring needs the focus margin")
        border, side = self.slice_size(radius, margin)
        image = self.canvas(side, side)
        draw = ImageDraw.Draw(image)
        if focus is not None:
            self.focus_ring(draw, (0, 0, side, side), radius + margin, focus)
        x0 = y0 = margin
        x1 = y1 = side - margin
        line = self.px(1)
        if stroke is None:
            self.rounded(draw, (x0, y0, x1, y1), radius, fill)
            return self.finish(image, side, side), border
        edge = self.px(bottom_width) if bottom_width else line
        self.rounded(draw, (x0, y0, x1, y1), radius, bottom or stroke)
        self.rounded(draw, (x0, y0, x1, y1 - edge), radius, stroke)
        self.rounded(draw, (x0 + line, y0 + line, x1 - line, y1 - edge), radius - line, fill)
        return self.finish(image, side, side), border

    def blank(self, width, height):
        return self.finish(self.canvas(width, height), width, height)

    def pill(self, width, height, color):
        image = self.canvas(width, height)
        self.rounded(ImageDraw.Draw(image), (0, 0, width, height), width / 2, color)
        return self.finish(image, width, height)

    def polyline(self, width, height, points, color, stroke):
        image = self.canvas(width, height)
        ImageDraw.Draw(image).line(
            [(x * _SS, y * _SS) for x, y in points],
            fill=color, width=round(stroke * _SS), joint="curve",
        )
        return self.finish(image, width, height)

    def _outlined(self, draw, box, radius, fill, stroke):
        x0, y0, x1, y1 = box
        if stroke is None:
            self.rounded(draw, box, radius, fill)
            return
        line = self.px(1)
        self.rounded(draw, box, radius, stroke)
        self.rounded(draw, (x0 + line, y0 + line, x1 - line, y1 - line), radius - line, fill)

    def checkbox(self, box, gap, fill, stroke=None, check=None, focus=None):
        """A check box ``box`` px square inside the focus margin, then ``gap``
        transparent pixels that space it from its label."""
        margin = self.margin
        side = box + 2 * margin
        image = self.canvas(side + gap, side)
        draw = ImageDraw.Draw(image)
        radius = self.px(4)
        if focus is not None:
            self.focus_ring(draw, (0, 0, side, side), radius + margin, focus)
        self._outlined(draw, (margin, margin, margin + box, margin + box), radius, fill, stroke)
        if check is not None:
            unit = box / 20
            draw.line(
                [((margin + x * unit) * _SS, (margin + y * unit) * _SS)
                 for x, y in ((5.5, 10.5), (8.5, 13.5), (14.5, 7.0))],
                fill=check, width=round(1.4 * unit * _SS), joint="curve",
            )
        return self.finish(image, side + gap, side)

    def switch(self, track_width, height, gap, fill, knob, knob_size, on,
               stroke=None, focus=None):
        """A switch track inside the focus margin, then ``gap`` transparent pixels."""
        margin = self.margin
        width, full_height = track_width + 2 * margin, height + 2 * margin
        image = self.canvas(width + gap, full_height)
        draw = ImageDraw.Draw(image)
        radius = height / 2
        if focus is not None:
            self.focus_ring(draw, (0, 0, width, full_height), radius + margin, focus)
        self._outlined(
            draw, (margin, margin, margin + track_width, margin + height), radius, fill, stroke)
        center_x = margin + (track_width - radius if on else radius)
        center_y = margin + radius
        half = knob_size / 2
        draw.ellipse(
            ((center_x - half) * _SS, (center_y - half) * _SS,
             (center_x + half) * _SS, (center_y + half) * _SS),
            fill=knob,
        )
        return self.finish(image, width + gap, full_height)


def _icon_font(size):
    for name in ui_theme.ICON_FONT_FILES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return None


def _render_icon(artist, glyph, color, size, gap, leading=False):
    """The glyph in a ``size`` square, plus ``gap`` transparent pixels after it
    (before it when ``leading``, for an icon that follows its text).

    The gap is how an icon keeps its distance from a button's text: ttk's
    compound label has no spacing option.
    """
    font = _icon_font(size)
    if font is None:
        return None
    image = Image.new("RGBA", (size + gap, size), (0, 0, 0, 0))
    center = (gap if leading else 0) + size / 2
    ImageDraw.Draw(image).text((center, size / 2), glyph, font=font, fill=color, anchor="mm")
    return artist.photo(image)


# ---------------------------------------------------------------------------
# Theme creation
# ---------------------------------------------------------------------------

# (interpreter, theme) -> _ThemeState; dropped with the root, see install().
_themes = {}


class _ThemeState:
    def __init__(self, ui, artist):
        self.ui = ui
        self.artist = artist
        self.surface_styles = set()
        self.icons = {}
        # Image element name -> ([(state spec, image), ...], default image), in
        # the order ttk matches them: the first spec the widget is in wins.
        self.elements = {}


def _state(widget, ui=None):
    ui = ui or ui_theme.theme()
    return _themes.get((str(widget.tk.interpaddr()), theme_name(ui)))


def install(window, ui=None):
    """Create (once) and select this palette's Fluent theme. Returns its name."""
    ui = ui or ui_theme.theme()
    style = ttk.Style(window)
    name = theme_name(ui)
    key = (str(window.tk.interpaddr()), name)
    if name not in style.theme_names():
        style.theme_create(name, parent="clam")
        style.theme_use(name)
        artist = _Artist(window, ui_theme.display_scale(window))
        state = _ThemeState(ui, artist)
        _themes[key] = state
        _configure(style, ui, artist, state.elements)
        # Release the images while the root is being destroyed on the GUI
        # thread; left to interpreter exit, they would be freed elsewhere.
        root = window.nametowidget(".")
        root.bind(
            "<Destroy>",
            lambda event: _themes.pop(key, None) if event.widget is root else None,
            add="+",
        )
    else:
        style.theme_use(name)
    # The popdown list is a classic Listbox Tk creates on demand.
    window.option_add("*TCombobox*Listbox.font", ui.font())
    return name


def _configure(style, ui, artist, elements):
    """Define every element and style of this palette's theme.

    ``elements`` records each state-dependent image element as ttk matches
    it (see :class:`_ThemeState`).
    """
    px = artist.px
    light = not ui.is_dark
    base = ui.card
    overlay = ui.overlay
    text = ui.text
    muted = ui.text_muted
    font = ui.font()
    radius = px(4)
    margin = artist.margin
    ring = ui.focus_ring

    style.configure(
        ".",
        background=ui.surface, foreground=text, font=font,
        bordercolor=ui.field_border, lightcolor=ui.surface, darkcolor=ui.surface,
        troughcolor=ui.surface, focuscolor=ring,
        selectbackground=ui.select_bg, selectforeground=ui.select_fg,
        insertcolor=text, fieldbackground=ui.field,
    )
    style.map(".", foreground=[("disabled", muted)])

    def states(draw, rest, variants=(), disabled=(), focusable=True):
        """``([(state spec, image), ...], rest image)`` in ttk match order.

        ``draw(*args, focus=None)`` paints one state. Disabled comes first.
        A focusable control then repeats every variant with the focus ring,
        because focus composes with pressed, selected and hover rather than
        hiding them; the plain variants follow.
        """
        specs = [(state, draw(*args)) for state, args in disabled]
        if focusable:
            specs += [(f"focus {state}", draw(*args, focus=ring)) for state, args in variants]
            specs.append(("focus", draw(*rest, focus=ring)))
        specs += [(state, draw(*args)) for state, args in variants]
        return specs, draw(*rest)

    # -- Buttons ------------------------------------------------------------
    def face(fill, stroke=None, bottom=None, bottom_width=None, focus=None):
        return artist.face(radius, fill, stroke, bottom, bottom_width,
                           focus=focus, margin=margin)[0]

    def face_element(name, faces, margin=margin):
        specs, default = faces
        elements[name] = faces
        border, _side = artist.slice_size(radius, margin)
        # An image element defaults to its image's size as a minimum; the
        # wide tiling middle must not become the smallest control. Its
        # children sit inside the focus margin, and the density sets the
        # height of the visible face.
        style.element_create(
            name, "image", default, *specs,
            border=border, padding=margin, sticky="nsew",
            width=2 * border, height=ui.control_height + 2 * margin,
        )

    stroke = ui.field_border
    disabled_fill = mix(base, overlay, 0.02)
    neutral_disabled = [("disabled", (disabled_fill, stroke))]
    neutral = states(face, (ui.control, stroke), [
        ("pressed", (ui.control_active, stroke)),
        ("active", (ui.control_hover, stroke)),
    ], neutral_disabled)
    face_element("Fluent.Button.face", neutral)
    # The dark danger label is under 4.5:1 on the neutral hover fill, so a
    # destructive button hovers on its own state tint.
    face_element("Fluent.Danger.face", states(face, (ui.control, stroke), [
        ("pressed", (ui.control_active, stroke)),
        ("active", (ui.danger_bg, stroke)),
    ], neutral_disabled))
    face_element("Fluent.Accent.face", states(face, (ui.accent,), [
        ("pressed", (ui.accent_active,)),
        ("active", (ui.accent_hover,)),
    ], [("disabled", (mix(base, overlay, 0.16),))]))
    # Subtle controls draw nothing at rest; hover and press are translucent
    # overlays, composited over whatever surface the style sits on.
    subtle_hover = _rgba(overlay, 0.05 if light else 0.08)
    subtle_pressed = _rgba(overlay, 0.03 if light else 0.05)
    face_element("Fluent.Subtle.face", states(face, (_CLEAR,), [
        ("pressed", (subtle_pressed,)),
        ("active", (subtle_hover,)),
    ], [("disabled", (_CLEAR,))]))
    # Toolbar buttons never take keyboard focus (see button()), so their
    # faces reserve no focus margin: nine of them share the editor's width.

    def flat_face(fill):
        return artist.face(radius, fill)[0]

    face_element("Fluent.Toolbar.face", states(flat_face, (_CLEAR,), [
        ("pressed", (subtle_pressed,)),
        ("active", (subtle_hover,)),
    ], [("disabled", (_CLEAR,))], focusable=False), margin=0)
    # The current page keeps the selection fill under hover and focus.
    face_element("Fluent.Nav.face", states(face, (_CLEAR,), [
        ("pressed", (subtle_pressed,)),
        ("selected", (ui.select_bg,)),
        ("active", (subtle_hover,)),
    ]))
    pill_width, pill_height = px(3), px(16)
    pill = artist.pill(pill_width, pill_height, ui.accent_border)
    blank_pill = artist.blank(pill_width, pill_height)
    elements["Fluent.Nav.pill"] = ([("selected", pill)], blank_pill)
    style.element_create(
        "Fluent.Nav.pill", "image", blank_pill, ("selected", pill), sticky="",
    )

    def button_layout(face_name, with_pill=False):
        label = [("Button.padding", {"sticky": "nsew", "children": [
            ("Button.label", {"sticky": "nsew"})]})]
        if with_pill:
            label.insert(0, ("Fluent.Nav.pill", {"side": "left", "sticky": ""}))
        return [(face_name, {"sticky": "nsew", "children": label})]

    # One line of body text between these paddings fills the Compact face.
    label_height = tkfont.Font(root=artist.master, font=font).metrics("linespace")
    slack = max(0, ui.control_height - label_height)
    top, bottom = slack // 2, slack - slack // 2
    for style_name, face_name in (
        ("TButton", "Fluent.Button.face"),
        ("Danger.TButton", "Fluent.Danger.face"),
        ("Accent.TButton", "Fluent.Accent.face"),
        ("Subtle.TButton", "Fluent.Subtle.face"),
        ("Toolbar.TButton", "Fluent.Toolbar.face"),
    ):
        style.layout(style_name, button_layout(face_name))
    style.layout("Nav.TButton", button_layout("Fluent.Nav.face", with_pill=True))
    style.configure(
        "TButton", padding=(px(12), top, px(12), bottom), anchor="center",
        foreground=text, font=font, focuscolor=ring,
    )
    style.map("TButton", foreground=[("disabled", muted), ("pressed", muted)])
    style.configure("Danger.TButton", foreground=ui.danger)
    style.map("Danger.TButton", foreground=[("disabled", muted)])
    style.configure("Accent.TButton", foreground=ui.text_on_accent)
    style.map("Accent.TButton", foreground=[("disabled", ui.card if light else muted)])
    style.configure("Subtle.TButton", padding=(px(8), top, px(8), bottom))
    style.configure("Toolbar.TButton", padding=(px(6), top, px(6), bottom))
    style.configure(
        "Nav.TButton", anchor="w", padding=(px(9), top, px(12), bottom),
    )
    style.map(
        "Nav.TButton",
        font=[("selected", ui.font(ui_theme.BODY_FONT_SIZE, "bold"))],
        foreground=[("disabled", muted)],
    )

    # -- Text fields --------------------------------------------------------
    # Fields reserve the focus margin too, so they line up with the buttons
    # and drop-downs stacked around them; their focus is the underline.
    field = ui.field
    field_hover = mix(field, overlay, 0.03)
    field_disabled = mix(base, overlay, 0.03)
    face_element("Fluent.Field.face", states(face, (field, stroke), [
        ("focus", (field, stroke, ui.accent_border, 2)),
        ("hover", (field_hover, stroke)),
    ], [
        ("disabled", (field_disabled, stroke)),
        ("readonly", (field_disabled, stroke)),
    ], focusable=False))
    style.layout("TEntry", [("Fluent.Field.face", {"sticky": "nsew", "children": [
        ("Entry.padding", {"sticky": "nsew", "children": [
            ("Entry.textarea", {"sticky": "nsew"})]})]})])
    # Light Windows keeps the user's own selection color (see entry_colors).
    native_selection = light and ui.system == "windows"
    selection = (
        {"selectbackground": "SystemHighlight", "selectforeground": "SystemHighlightText"}
        if native_selection
        else {"selectbackground": ui.select_bg, "selectforeground": ui.select_fg}
    )
    style.configure(
        "TEntry", padding=(px(10), top, px(6), bottom), foreground=text,
        insertcolor=text, insertwidth=px(1), **selection,
    )
    # Containers for tk.Text/Listbox borrow the field face; their focus state
    # is set by hand (see text_area).
    style.layout("Field.TFrame", [("Fluent.Field.face", {"sticky": "nsew"})])

    # -- Combobox (always read-only here: a button with a chevron) ----------
    # It takes focus on every click, unlike a button, so the ring also shows
    # after pointer use; keyboard users need it either way.
    face_element("Fluent.Combo.face", neutral)
    arrow_width, arrow_height = px(30), px(16)
    center_x, center_y = arrow_width / 2 - px(2), arrow_height / 2
    half = px(4)
    chevron = ((center_x - half, center_y - half / 2), (center_x, center_y + half / 2),
               (center_x + half, center_y - half / 2))
    style.element_create(
        "Fluent.Combo.arrow", "image",
        artist.polyline(arrow_width, arrow_height, chevron, muted, px(1) * 1.2),
        ("disabled", artist.polyline(arrow_width, arrow_height, chevron,
                                     mix(muted, base, 0.5), px(1) * 1.2)),
        sticky="",
    )
    style.layout("TCombobox", [("Fluent.Combo.face", {"sticky": "nsew", "children": [
        ("Fluent.Combo.arrow", {"side": "right", "sticky": ""}),
        ("Combobox.padding", {"expand": "1", "sticky": "nsew", "children": [
            ("Combobox.textarea", {"sticky": "nsew"})]})]})])
    style.configure(
        "TCombobox", padding=(px(11), top, px(0), bottom), foreground=text,
        arrowsize=px(12), **selection,
    )
    # A read-only combobox highlights its text on focus; keep it plain.
    style.map(
        "TCombobox",
        foreground=[("disabled", muted)],
        selectbackground=[("readonly", ui.control)],
        selectforeground=[("readonly", text)],
        fieldbackground=[("readonly", ui.control)],
    )

    # -- Checkbox and switch ------------------------------------------------
    # Checked is the copper fill with a copper-mark edge, which keeps the
    # control's boundary at 3:1 where raw copper is too light (light mode).
    box, label_gap = px(20), px(8)
    unchecked = _rgba(overlay, 0.02 if light else 0.1)
    unchecked_hover = _rgba(overlay, 0.06 if light else 0.14)
    check = ui.text_on_accent
    edge = ui.accent_border
    off_stroke = ui.stroke_strong
    indicator_disabled = mix(base, overlay, 0.2)

    def checkbox(fill, outline=None, mark=None, focus=None):
        return artist.checkbox(box, label_gap, fill, outline, mark, focus=focus)

    indicators = {
        "Fluent.Check.indicator": states(checkbox, (unchecked, off_stroke), [
            ("pressed selected", (ui.accent_active, edge, check)),
            ("active selected", (ui.accent_hover, edge, check)),
            ("selected", (ui.accent, edge, check)),
            ("pressed", (unchecked_hover, off_stroke)),
            ("active", (unchecked_hover, off_stroke)),
        ], [
            ("selected disabled", (indicator_disabled, None, base)),
            ("disabled", (_CLEAR, indicator_disabled)),
        ]),
    }
    track, height = px(40), px(20)
    knob, knob_hover = px(12), px(14)
    off_knob = mix(text, base, 0.35)

    def switch(fill, knob_color, knob_size, on, outline=None, focus=None):
        return artist.switch(track, height, label_gap, fill, knob_color, knob_size, on,
                             outline, focus=focus)

    indicators["Fluent.Switch.indicator"] = states(
        switch, (unchecked, off_knob, knob, False, off_stroke), [
            ("active selected", (ui.accent_hover, check, knob_hover, True, edge)),
            ("selected", (ui.accent, check, knob, True, edge)),
            ("active", (unchecked_hover, off_knob, knob_hover, False, off_stroke)),
        ], [
            ("selected disabled", (indicator_disabled, base, knob, True)),
            ("disabled", (_CLEAR, indicator_disabled, knob, False, indicator_disabled)),
        ])
    for name, (specs, default) in indicators.items():
        elements[name] = (specs, default)
        style.element_create(name, "image", default, *specs, sticky="")
    # The indicator carries the focus ring, so the label draws no focus
    # rectangle of its own.
    for style_name, indicator in (
        ("TCheckbutton", "Fluent.Check.indicator"),
        ("Switch.TCheckbutton", "Fluent.Switch.indicator"),
    ):
        style.layout(style_name, [("Checkbutton.padding", {"sticky": "nsew", "children": [
            (indicator, {"side": "left", "sticky": ""}),
            ("Checkbutton.label", {"side": "left", "sticky": "w"})]})])
    indicator_height = box + 2 * margin
    style.configure(
        "TCheckbutton", foreground=text, font=font,
        padding=(0, max(0, (ui.control_height - indicator_height) // 2)),
    )
    style.map("TCheckbutton", foreground=[("disabled", muted)])

    # -- Scrollbars: a slim pill that widens under the pointer ---------------
    bar = px(12)
    # Rounded ends stay out of the tiled middle (see _Artist.slice_size).
    end = px(6)
    thumb_length = 2 * end + _SLICE_MIDDLE
    for orient in ("Vertical", "Horizontal"):
        vertical = orient == "Vertical"
        size = (bar, thumb_length) if vertical else (thumb_length, bar)

        def thumb(width, color, vertical=vertical, size=size):
            image = _Artist.canvas(*size)
            draw = ImageDraw.Draw(image)
            inset = (bar - width) / 2
            box = ((inset, px(2), inset + width, size[1] - px(2)) if vertical
                   else (px(2), inset, size[0] - px(2), inset + width))
            _Artist.rounded(draw, box, width / 2, color)
            return artist.finish(image, *size)

        border = (0, end) if vertical else (end, 0)
        minimum = ({"width": bar, "height": 2 * end} if vertical
                   else {"width": 2 * end, "height": bar})
        style.element_create(
            f"Fluent.{orient}.thumb", "image",
            thumb(px(3), ui.scrollbar_thumb),
            ("pressed", thumb(px(6), mix(ui.scrollbar_thumb, text, 0.3))),
            ("active", thumb(px(6), ui.scrollbar_thumb)),
            border=border, sticky="nsew", **minimum,
        )
        style.element_create(
            f"Fluent.{orient}.trough", "image", artist.blank(*size),
            border=border, sticky="nsew", **minimum,
        )
        style.layout(f"{orient}.TScrollbar", [(f"Fluent.{orient}.trough", {
            "sticky": "nsew", "children": [(f"Fluent.{orient}.thumb", {
                "expand": "1", "sticky": "nsew"})]})])

    # -- Cards ---------------------------------------------------------------
    card_image, card_border = artist.face(px(8), ui.card, ui.card_border)
    style.element_create(
        "Fluent.Card.face", "image", card_image,
        border=card_border, sticky="nsew", padding=0,
        width=2 * card_border, height=2 * card_border,
    )
    style.layout("Card.TFrame", [("Fluent.Card.face", {"sticky": "nsew"})])

    # -- Lists ---------------------------------------------------------------
    heading_width, heading_height = _SLICE_MIDDLE, px(24)
    heading_image = artist.canvas(heading_width, heading_height)
    ImageDraw.Draw(heading_image).rectangle(
        (0, (heading_height - px(1)) * _SS, heading_width * _SS - 1, heading_height * _SS - 1),
        fill=ui.divider)
    style.element_create(
        "Fluent.Heading.cell", "image",
        artist.finish(heading_image, heading_width, heading_height),
        border=(0, 0, 0, px(1)), sticky="nsew", width=0, height=px(1),
    )
    style.layout("Treeview.Heading", [("Fluent.Heading.cell", {"sticky": "nsew", "children": [
        ("Treeheading.padding", {"sticky": "nsew", "children": [
            ("Treeheading.image", {"side": "right", "sticky": ""}),
            ("Treeheading.text", {"sticky": "we"})]})]})])
    # Rows follow the density. Clam's own default is a fixed pixel count the
    # text outgrows at high DPI; a platform font taller than the row (Linux
    # uses its own default size) still gets its line plus breathing room.
    style.configure(
        "Treeview", background=ui.card, fieldbackground=ui.card, foreground=text,
        bordercolor=ui.card, lightcolor=ui.card, darkcolor=ui.card, borderwidth=0,
        rowheight=max(ui.tree_row_height, label_height + px(8)),
    )
    style.map(
        "Treeview",
        background=[("selected", ui.select_bg)],
        foreground=[("selected", ui.select_fg)],
    )
    style.configure(
        "Treeview.Heading", background=ui.card, foreground=muted,
        font=ui.font(9, "bold"), padding=(px(8), px(6)),
    )
    style.map("Treeview.Heading", background=[("active", ui.card)])

    # -- Page container -----------------------------------------------------
    style.configure(
        "TNotebook", background=ui.surface, borderwidth=0,
        bordercolor=ui.surface, lightcolor=ui.surface, darkcolor=ui.surface,
    )
    style.configure("TFrame", background=ui.surface)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _surface_style(parent, base, ui=None):
    """``base`` restyled onto ``parent``'s surface; see the module docstring."""
    state = _state(parent, ui)
    if state is None:
        return base
    color = surface_of(parent)
    name = f"Bg{color[1:]}.{base}"
    if name not in state.surface_styles:
        ttk.Style(parent).configure(name, background=color)
        state.surface_styles.add(name)
    return name


def face_gap(widget, visible, ui=None):
    """Padding that leaves ``visible`` px between two adjacent controls in ``widget``.

    Every Fluent face reserves its focus margin on each side (see
    :class:`_Artist`), so two controls packed flush already show two margins
    of surface between their faces; only the rest is padding. Where the theme
    is not installed (macOS), the padding is ``visible`` itself.
    """
    state = _state(widget, ui)
    if state is None:
        return visible
    return max(0, visible - 2 * state.artist.margin)


def has_icons(widget, ui=None):
    """True where :func:`button` icons render; an icon-only button needs a
    text fallback everywhere else."""
    return _state(widget, ui) is not None and _icon_font(1) is not None


def icon_image(widget, name, color, *, gap=0, leading=False, ui=None):
    """A Fluent icon glyph as a PhotoImage in ``color``, or None without the font.

    ``gap`` pads it after the glyph, or before it when ``leading``.
    """
    state = _state(widget, ui)
    if state is None:
        return None
    color = resolve_color(widget, color)
    key = (name, color, gap, leading)
    if key not in state.icons:
        artist = state.artist
        state.icons[key] = _render_icon(
            artist, ICONS[name], color, artist.px(16), artist.px(gap) if gap else 0, leading)
    return state.icons[key]


def _icon_option(widget, icon, variant, with_text, ui, trailing=False):
    """``-image`` spec for a button icon, or None."""
    color = {
        "accent": ui.text_on_accent,
        "danger": ui.danger,
    }.get(variant, ui.text)
    gap = 8 if with_text else 0
    normal = icon_image(widget, icon, color, gap=gap, leading=trailing, ui=ui)
    if normal is None:
        return None
    disabled = icon_image(widget, icon, ui.text_muted, gap=gap, leading=trailing, ui=ui)
    return (normal, "disabled", disabled)


def button(parent, text="", command=None, *, variant="standard", icon=None,
           width=None, ui=None, **options):
    """A push button in one of :data:`VARIANTS`.

    ``width`` is a minimum in characters; buttons otherwise size to their
    content, as Windows 11 buttons do. ``icon`` names an :data:`ICONS`
    glyph shown before the text where the icon font exists.
    """
    ui = ui or ui_theme.theme()
    if variant not in VARIANTS:
        raise ValueError(f"unknown button variant: {variant!r}")
    if not uses_fluent(ui):
        anchor = "w" if variant == "nav" else None
        return tk.Button(
            parent, text=text, command=command,
            **({"anchor": anchor} if anchor else {}), **options,
        )
    style = _surface_style(parent, _BUTTON_STYLES[variant], ui)
    widget = ttk.Button(parent, text=text, command=command, style=style, **options)
    if width:
        widget.configure(width=-width)
    if icon:
        set_icon(widget, icon, variant=variant, ui=ui)
    if variant == "toolbar":
        widget.configure(takefocus=0)
    return widget


def set_icon(widget, icon, *, variant="standard", trailing=False, ui=None):
    """Show ``icon`` on a :func:`button`, before its text or, when ``trailing``,
    after it (a drop-down chevron). Returns whether it is shown: never without
    Fluent or the icon font."""
    ui = ui or ui_theme.theme()
    if not isinstance(widget, ttk.Button):
        return False
    with_text = bool(str(widget.cget("text")))
    image = _icon_option(widget, icon, variant, with_text, ui, trailing)
    if image is None:
        return False
    compound = ("right" if trailing else "left") if with_text else "image"
    widget.configure(image=image, compound=compound)
    return True


def nav_item(parent, text, command, *, icon=None, ui=None):
    """A section-navigation entry, packed into ``parent``. Returns its button.

    Fluent draws the selection pill inside the button; macOS keeps its
    native button with the copper-mark (``accent_border``) bar beside it.
    """
    ui = ui or ui_theme.theme()
    if uses_fluent(ui):
        widget = button(parent, text=text, command=command, variant="nav", icon=icon, ui=ui)
        widget.pack(fill=tk.X, pady=1)
        return widget
    background = parent.cget("background")
    item = tk.Frame(parent, bg=background)
    item.pack(fill=tk.X, pady=1)
    marker = tk.Frame(item, bg=background, width=3)
    marker.pack(side=tk.LEFT, fill=tk.Y)
    widget = tk.Button(item, text=text, command=command, anchor="w", font=ui.font())
    widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
    widget.marker = marker
    return widget


def set_selected(widget, selected, ui=None):
    """Mark a :func:`nav_item` as the current section."""
    ui = ui or ui_theme.theme()
    if isinstance(widget, ttk.Button):
        widget.state(["selected" if selected else "!selected"])
        return
    widget.configure(font=ui.font(ui_theme.BODY_FONT_SIZE, "bold" if selected else None))
    marker = getattr(widget, "marker", None)
    if marker is not None:
        marker.configure(bg=ui.accent_border if selected else marker.master.cget("background"))


def entry(parent, *, font=None, ui=None, **options):
    """A single-line text field."""
    ui = ui or ui_theme.theme()
    font = font or ui.font()
    if not uses_fluent(ui):
        return tk.Entry(
            parent, font=font, **ui.entry_colors(), **ui.field_chrome(), **options,
        )
    return ttk.Entry(
        parent, font=font, style=_surface_style(parent, "TEntry", ui), **options,
    )


def combobox(parent, *, ui=None, **options):
    """A read-only drop-down list."""
    ui = ui or ui_theme.theme()
    options.setdefault("state", "readonly")
    if not uses_fluent(ui):
        return ttk.Combobox(parent, **options)
    return ttk.Combobox(
        parent, style=_surface_style(parent, "TCombobox", ui), font=ui.font(), **options,
    )


def checkbox(parent, text="", *, variable=None, command=None, ui=None, **options):
    """A check box for a choice that is saved with its form."""
    return _check(parent, "TCheckbutton", text, variable, command, ui, options)


def switch(parent, text="", *, variable=None, command=None, ui=None, **options):
    """A toggle switch for an on/off setting that applies immediately."""
    return _check(parent, "Switch.TCheckbutton", text, variable, command, ui, options)


def _check(parent, base, text, variable, command, ui, options):
    ui = ui or ui_theme.theme()
    if not uses_fluent(ui):
        return tk.Checkbutton(
            parent, text=text, variable=variable, command=command,
            font=ui.font(), anchor="w", **options,
        )
    return ttk.Checkbutton(
        parent, text=text, variable=variable, command=command,
        style=_surface_style(parent, base, ui), **options,
    )


def scrollbar(parent, *, orient=tk.VERTICAL, ui=None, **options):
    ui = ui or ui_theme.theme()
    if not uses_fluent(ui):
        return ttk.Scrollbar(parent, orient=orient, **options)
    base = "Vertical.TScrollbar" if orient == tk.VERTICAL else "Horizontal.TScrollbar"
    return ttk.Scrollbar(
        parent, orient=orient, style=_surface_style(parent, base, ui), **options,
    )


def card(parent, *, padding=16, ui=None):
    """A settings/pane card. Children sit on ``ui.card``."""
    ui = ui or ui_theme.theme()
    if isinstance(padding, int):
        padding = (padding, padding)
    if not uses_fluent(ui):
        return tk.Frame(
            parent, bg=ui.card, padx=padding[0], pady=padding[1],
            highlightbackground=ui.border, highlightthickness=1, bd=0,
        )
    frame = ttk.Frame(
        parent, style=_surface_style(parent, "Card.TFrame", ui), padding=padding,
    )
    frame.surface_color = ui.card
    return frame


def field_frame(parent, *, ui=None):
    """A bordered container for a ``tk.Listbox`` (plus its scrollbar).

    Its children sit on ``ui.field`` and draw no border of their own (see
    :func:`listbox_colors`); :func:`track_focus` gives it the focus underline.
    """
    ui = ui or ui_theme.theme()
    if not uses_fluent(ui):
        return tk.Frame(
            parent, bg=ui.card, highlightbackground=ui.border, highlightthickness=1,
        )
    # A frame's padding must be a widget option: its layout has no padding
    # element, so a style padding would let the child cover the border. It
    # clears the face's focus margin as well (see _Artist).
    artist = _state(parent, ui).artist
    inset = artist.margin + artist.px(4)
    frame = ttk.Frame(
        parent, style=_surface_style(parent, "Field.TFrame", ui),
        padding=(inset, inset, inset, inset),
    )
    frame.surface_color = ui.field
    return frame


def list_frame(parent, *, ui=None):
    """A grid container for a Treeview plus scrollbar, on ``parent``'s surface.

    Windows 11 lists sit directly on their card; macOS keeps the one-pixel
    frame it always had.
    """
    ui = ui or ui_theme.theme()
    if not uses_fluent(ui):
        return tk.Frame(
            parent, bg=ui.card, highlightbackground=ui.border, highlightthickness=1,
        )
    return tk.Frame(parent, bg=surface_of(parent), bd=0, highlightthickness=0)


def track_focus(frame, widget):
    """Mirror ``widget``'s keyboard focus onto a :func:`field_frame`."""
    if not isinstance(frame, ttk.Frame):
        return
    widget.bind("<FocusIn>", lambda _event: frame.state(["focus"]), add="+")
    widget.bind("<FocusOut>", lambda _event: frame.state(["!focus"]), add="+")


def listbox_colors(ui=None):
    """Colors for a ``tk.Listbox`` inside :func:`field_frame`.

    Selection matches the lists' Treeview rows rather than the saturated
    system highlight. The caller still passes ``relief="flat"`` and
    ``borderwidth=0``: the frame draws the only border.
    """
    ui = ui or ui_theme.theme()
    if not uses_fluent(ui):
        return ui.listbox_colors()
    return {
        **ui.listbox_colors(), "bg": ui.field, "fg": ui.text, "highlightthickness": 0,
        "selectbackground": ui.select_bg, "selectforeground": ui.select_fg,
    }


def text_area(parent, *, scroll=False, ui=None, **options):
    """A multi-line text field: ``(container, tk.Text)``. Place the container.

    ``scroll`` adds a vertical scrollbar inside the field's border.
    """
    ui = ui or ui_theme.theme()
    options.setdefault("font", ui.font())
    if not uses_fluent(ui):
        # The Text keeps its own one-pixel field border, as it always had.
        container = tk.Frame(parent, bg=surface_of(parent))
        text = tk.Text(container, **ui.text_colors(), **ui.field_chrome(), **options)
    else:
        container = field_frame(parent, ui=ui)
        colors = {
            **ui.text_colors(), "bg": ui.field, "highlightthickness": 0,
            "relief": "flat", "borderwidth": 0,
        }
        colors.setdefault("fg", ui.text)
        colors.setdefault("insertbackground", ui.text)
        text = tk.Text(container, **colors, **options)
        track_focus(container, text)
    if scroll:
        bar = scrollbar(container, command=text.yview, ui=ui)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
    text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    return container, text


def menu(parent, *, ui=None):
    """A pop-up menu in the palette of ``parent``'s window.

    Windows draws Tk menus itself and honors their colors, so a menu left
    uncolored opened light over the dark manager. macOS keeps its native
    menu, which follows the system appearance.
    """
    ui = ui or ui_theme.theme()
    if not uses_fluent(ui):
        return tk.Menu(parent, tearoff=False)
    return tk.Menu(
        parent, tearoff=False, font=ui.font(), bg=ui.card, fg=ui.text,
        activebackground=ui.select_bg, activeforeground=ui.select_fg,
        disabledforeground=ui.text_muted, relief=tk.FLAT, borderwidth=1,
        activeborderwidth=0,
    )


# ---------------------------------------------------------------------------
# Dialog kit
# ---------------------------------------------------------------------------
# Every prompt the GUI shows is an owned, themed Toplevel built here, so it
# follows the palette, the interface language and the window it belongs to.
# The native message boxes did none of that: Win32 drew them light, with
# buttons in the system language, over whichever window was active.
# The prompts take the cached theme, the one their window was built with,
# rather than probing the appearance again: the ttk theme belongs to the
# shared interpreter, so a prompt built from another palette would repaint
# every open window's controls with it.

# confirm() answers; Cancelar, Escape and closing the window answer None.
PRIMARY = "primary"
EXTRA = "extra"

_TONE_ICONS = {"danger": "error", "warning": "warning", "info": "info"}
# Footer buttons share a minimum width, in characters, so short outcome
# labels do not shrink to slivers beside Cancelar.
_FOOTER_BUTTON_WIDTH = 10


def _is_disabled(widget):
    return str(widget.cget("state")) == tk.DISABLED


def dialog_footer(parent, primary, secondary, *, extra=None, variant="accent",
                  extra_variant="standard", ui=None):
    """A dialog's action row: ``primary``, then ``extra``, then Cancelar, right-aligned.

    ``primary`` and ``extra`` are ``(label, command)``; ``secondary`` is the
    command of the safe choice, Cancelar, or None for a dialog with nothing to
    cancel. ``variant`` styles the primary (``"danger"`` for a destructive
    one) and ``extra_variant`` the extra.

    Enter runs the focused footer button, as Windows does, and otherwise the
    primary unless a multi-line text field has focus; a disabled target does
    nothing. Escape runs ``secondary`` (the primary when there is none).
    Returns the frame, with its buttons in ``frame.buttons`` under
    ``"primary"``, ``"extra"`` and ``"cancel"``.
    """
    ui = ui or ui_theme.theme()
    frame = tk.Frame(parent, bg=surface_of(parent))
    label, command = primary
    buttons = {"primary": button(
        frame, text=label, command=command, variant=variant,
        width=_FOOTER_BUTTON_WIDTH, ui=ui)}
    if extra is not None:
        buttons["extra"] = button(
            frame, text=extra[0], command=extra[1], variant=extra_variant,
            width=_FOOTER_BUTTON_WIDTH, ui=ui)
    if secondary is not None:
        buttons["cancel"] = button(
            frame, text=_("Cancelar"), command=secondary,
            width=_FOOTER_BUTTON_WIDTH, ui=ui)
    gap = face_gap(frame, ui.space_sm, ui)
    for widget in reversed(tuple(buttons.values())):
        widget.pack(side=tk.RIGHT, padx=(gap, 0))
    frame.buttons = buttons

    def on_return(event):
        widget = event.widget
        if isinstance(widget, tk.Text):
            return None
        target = widget if widget in buttons.values() else buttons["primary"]
        if not _is_disabled(target):
            target.invoke()
        return "break"

    def on_escape(_event):
        (secondary or command)()
        return "break"

    window = parent.winfo_toplevel()
    window.bind("<Return>", on_return)
    window.bind("<KP_Enter>", on_return)
    window.bind("<Escape>", on_escape)
    return frame


def _require_owner(parent):
    # A prompt without an owner belongs to the hidden shared root: it is not
    # modal to the window the person acted in and can open behind it.
    if parent is None:
        raise TypeError("a prompt needs the window it belongs to")


def _prompt(parent, title, ui):
    """A withdrawn prompt window owned by ``parent``'s window: ``(window, body)``."""
    window = tk.Toplevel(parent.winfo_toplevel())
    window.withdraw()
    window.title(title)
    window.resizable(False, False)
    window.configure(bg=ui.surface)
    ui_theme.prepare_window(window, ui)
    # The body sits on the dialog surface itself, with no card inside.
    body = tk.Frame(window, bg=ui.surface, padx=ui.space_xl, pady=ui.space_lg)
    body.pack(fill=tk.BOTH, expand=True)
    return window, body


def _heading(body, title, ui, tone=None):
    glyph = None
    if tone is not None:
        glyph = icon_image(body, _TONE_ICONS[tone], getattr(ui, tone), gap=8, ui=ui)
    tk.Label(
        body, text=title, image=glyph or "", compound=tk.LEFT, anchor="w",
        font=ui.subtitle_font(), bg=ui.surface, fg=ui.text,
    ).pack(fill=tk.X, pady=(0, ui.space_sm))


def _message(body, text, ui):
    label = tk.Label(
        body, text=text, anchor="w", justify=tk.LEFT, wraplength=ui.px(440),
        font=ui.font(), bg=ui.surface, fg=ui.text,
    )
    label.pack(fill=tk.X)
    return label


def _run_prompt(window, focus):
    """Show ``window`` modal over its owner until it is destroyed.

    Focus starts on ``focus`` and goes back to the control that had it, so a
    keyboard user carries on where the prompt interrupted. The grab follows
    the manager's other dialogs: the window it belongs to cannot be used, or
    asked a second question, while this one is open. A grab that another
    dialog held is handed back to it afterwards.
    """
    owner = window.master
    # Both lookups fail on a window Tk made itself, such as a combobox's
    # drop-down list; there is then nothing to give back.
    try:
        opener = owner.focus_get()
    except (KeyError, tk.TclError):
        opener = None
    try:
        previous_grab = window.grab_current()
    except (KeyError, tk.TclError):
        previous_grab = None
    viewable = bool(owner.winfo_viewable())
    # A transient of a window that is not viewable stays hidden with it.
    if viewable:
        window.transient(owner)
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    if viewable:
        x = owner.winfo_rootx() + (owner.winfo_width() - width) // 2
        y = owner.winfo_rooty() + (owner.winfo_height() - height) // 3
    else:
        x = (window.winfo_screenwidth() - width) // 2
        y = (window.winfo_screenheight() - height) // 3
    window.geometry(f"+{max(0, x)}+{max(0, y)}")
    window.deiconify()
    window.wait_visibility()
    window.grab_set()
    focus.focus_force()
    window.wait_window()
    if previous_grab is not None and previous_grab.winfo_exists():
        previous_grab.grab_set()
    if opener is not None and opener.winfo_exists():
        opener.focus_set()


def confirm(parent, title, body, primary_label, danger=False, typed_word=None, extra=None,
            *, extra_danger=False, ui=None):
    """Ask before an action. Returns :data:`PRIMARY`, :data:`EXTRA` or None.

    None means Cancelar, Escape or the window's close box. Every choice is
    labeled by its outcome. ``extra`` labels a third choice placed between
    the primary and Cancelar (Descartar beside Salvar; ``extra_danger`` draws
    it as destructive). ``danger`` draws the primary as destructive and
    starts focus on Cancelar, so Enter alone never destroys anything.
    ``typed_word`` keeps the primary disabled until that word is typed
    exactly, for irreversible work on a collection; focus then starts in its
    field.
    """
    _require_owner(parent)
    ui = ui or ui_theme.theme()
    window, frame = _prompt(parent, title, ui)
    answer = {"value": None}

    def choose(value):
        answer["value"] = value
        window.destroy()

    _heading(frame, title, ui)
    _message(frame, body, ui)
    word_field = None
    if typed_word:
        tk.Label(
            frame, text=_("Para confirmar, digite {word}").format(word=typed_word),
            anchor="w", font=ui.font(), bg=ui.surface, fg=ui.text,
        ).pack(fill=tk.X, pady=(ui.space_md, ui.space_xs))
        typed = tk.StringVar(window)
        word_field = entry(frame, textvariable=typed, ui=ui)
        word_field.pack(fill=tk.X)
    footer = dialog_footer(
        frame, (primary_label, lambda: choose(PRIMARY)), lambda: choose(None),
        extra=(extra, lambda: choose(EXTRA)) if extra else None,
        variant="danger" if danger else "accent",
        extra_variant="danger" if extra_danger else "standard", ui=ui,
    )
    footer.pack(fill=tk.X, pady=(ui.space_lg, 0))
    window.protocol("WM_DELETE_WINDOW", lambda: choose(None))
    if word_field is not None:
        primary = footer.buttons["primary"]

        def match(*_args):
            primary.configure(
                state=tk.NORMAL if typed.get().strip() == typed_word else tk.DISABLED)

        typed.trace_add("write", match)
        match()
        focus = word_field
    else:
        focus = footer.buttons["cancel" if danger else "primary"]
    _run_prompt(window, focus)
    return answer["value"]


def ask_text(parent, title, label, initial="", validate=None, *, primary_label, ui=None):
    """Ask for one line of text. Returns it without surrounding spaces, or None.

    None means Cancelar, Escape or the window's close box. ``validate(value)``
    answers an error message, which shows under the field while the dialog
    stays open, or None to accept the value.
    """
    _require_owner(parent)
    ui = ui or ui_theme.theme()
    window, frame = _prompt(parent, title, ui)
    answer = {"value": None}
    _heading(frame, title, ui)
    _message(frame, label, ui)
    value = tk.StringVar(window, initial)
    field = entry(frame, textvariable=value, width=40, ui=ui)
    field.pack(fill=tk.X, pady=(ui.space_xs, 0))
    # Present while empty, so an error does not resize the window.
    error = tk.Label(
        frame, text="", anchor="w", justify=tk.LEFT, wraplength=ui.px(440),
        font=ui.caption_font(), bg=ui.surface, fg=ui.danger,
    )
    error.pack(fill=tk.X, pady=(ui.space_xs, 0))

    def submit():
        text = value.get().strip()
        problem = validate(text) if validate is not None else None
        if problem:
            error.configure(text=problem)
            field.focus_set()
            field.select_range(0, tk.END)
            return
        answer["value"] = text
        window.destroy()

    footer = dialog_footer(frame, (primary_label, submit), window.destroy, ui=ui)
    footer.pack(fill=tk.X, pady=(ui.space_md, 0))
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    field.select_range(0, tk.END)
    field.icursor(tk.END)
    _run_prompt(window, field)
    return answer["value"]


def alert(parent, title, body, *, tone="warning", ui=None):
    """Tell the person something that leaves no choice: one Fechar button.

    ``tone`` is ``"danger"`` for a failure, ``"warning"`` for a refusal and
    ``"info"`` otherwise. It sets the icon beside the title; the title and
    the body carry the meaning.
    """
    if tone not in _TONE_ICONS:
        raise ValueError(f"unknown alert tone: {tone!r}")
    _require_owner(parent)
    ui = ui or ui_theme.theme()
    window, frame = _prompt(parent, title, ui)
    _heading(frame, title, ui, tone)
    _message(frame, body, ui)
    footer = dialog_footer(frame, (_("Fechar"), window.destroy), None, variant="standard", ui=ui)
    footer.pack(fill=tk.X, pady=(ui.space_lg, 0))
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    _run_prompt(window, footer.buttons["primary"])


class ReceiptLine:
    """The status line under an editor: a hint at rest, then the last receipt.

    A receipt may carry one action, such as Desfazer, which stays for
    ``seconds``; the receipt itself stays until the next one. The row keeps
    the action's height throughout, so a receipt never moves the editor
    above it.
    """

    def __init__(self, parent, hint, *, ui=None):
        self.ui = ui or ui_theme.theme()
        background = surface_of(parent)
        self.frame = tk.Frame(parent, bg=background)
        self.label = tk.Label(
            self.frame, text=hint, anchor="w", font=self.ui.caption_font(),
            bg=background, fg=self.ui.text_muted,
        )
        self.label.pack(side=tk.LEFT)
        self.action = button(self.frame, variant="subtle", ui=self.ui)
        self.frame.configure(height=self.action.winfo_reqheight())
        self.frame.pack_propagate(False)
        self._timer = None
        self.frame.bind("<Destroy>", self._on_destroy, add="+")

    def show(self, text, action_label=None, action=None, *, seconds=10):
        """Replace the line with ``text``, plus ``action`` while it lasts."""
        self._cancel_timer()
        self.label.configure(text=text, fg=self.ui.text)
        if action is None:
            self.action.pack_forget()
            return
        self.action.configure(text=action_label, command=lambda: self._act(action))
        self.action.pack(side=tk.LEFT, padx=(self.ui.space_sm, 0))
        self._timer = self.frame.after(round(seconds * 1000), self._expire)

    def _act(self, action):
        self._cancel_timer()
        self._expire()
        action()

    def _expire(self):
        self._timer = None
        self.action.pack_forget()

    def _cancel_timer(self):
        if self._timer is not None:
            self.frame.after_cancel(self._timer)
            self._timer = None

    def _on_destroy(self, event):
        if event.widget is self.frame:
            self._cancel_timer()
