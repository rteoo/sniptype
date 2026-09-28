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

# Supersampling factor for anti-aliased edges.
_SS = 4
# Side of the tiled middle of every nine-slice image, in pixels.
_SLICE_MIDDLE = 128

# Segoe Fluent Icons (Windows 11), then Segoe MDL2 Assets (Windows 10); both
# carry every codepoint below. Elsewhere there is no icon font and controls
# show their text alone.
_ICON_FONT_FILES = ("SegoeIcons.ttf", "segmdl2.ttf")

ICONS = {
    "add": "\ue710",
    "bell": "\uea8f",
    "bold": "\ue8dd",
    "clear_format": "\uea99",
    "code": "\ue943",
    "copy": "\ue8c8",
    "delete": "\ue74d",
    "down": "\ue74b",
    "document": "\ue8a5",
    "edit": "\ue70f",
    "export": "\ue898",
    "favorite": "\ue734",
    "folder": "\ue838",
    "form": "\ue9d5",
    "history": "\ue81c",
    "import": "\ue896",
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

class _Artist:
    """Draws the theme's images at one display scale and keeps them alive."""

    def __init__(self, master, scale):
        self.master = master
        self.scale = scale
        self.images = []

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

    def slice_size(self, radius):
        """Nine-slice border and image side for a shape of ``radius``.

        ttk *tiles* the middle of an image element rather than stretching
        it, and every tile of an image with alpha is a separate blended draw
        (a read-back of the window on Windows). The middle is therefore wide:
        a 2px one turned a card into tens of thousands of draws and one
        manager layout pass into ~30 seconds.
        """
        border = radius + self.px(2)
        return border, 2 * border + _SLICE_MIDDLE

    def face(self, radius, fill, stroke=None, bottom=None, bottom_width=None,
             focus=None):
        """A rounded control face; returns ``(image, slice border)``.

        ``stroke`` outlines it; ``bottom`` recolors the bottom edge (the
        elevation shadow of a button, the underline of a text field), which
        ``bottom_width`` thickens. ``focus`` swaps the stroke for a 2px ring.
        """
        border, side = self.slice_size(radius)
        image = self.canvas(side, side)
        draw = ImageDraw.Draw(image)
        line = self.px(1)
        if focus is not None:
            ring = self.px(2)
            self.rounded(draw, (0, 0, side, side), radius, focus)
            self.rounded(draw, (ring, ring, side - ring, side - ring), radius - ring, fill)
            return self.finish(image, side, side), border
        if stroke is None:
            self.rounded(draw, (0, 0, side, side), radius, fill)
            return self.finish(image, side, side), border
        edge = self.px(bottom_width) if bottom_width else line
        self.rounded(draw, (0, 0, side, side), radius, bottom or stroke)
        self.rounded(draw, (0, 0, side, side - edge), radius, stroke)
        self.rounded(draw, (line, line, side - line, side - edge), radius - line, fill)
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

    def checkbox(self, box, gap, fill, stroke=None, check=None):
        width = box + gap
        image = self.canvas(width, box)
        draw = ImageDraw.Draw(image)
        radius = self.px(4)
        line = self.px(1)
        if stroke is not None:
            self.rounded(draw, (0, 0, box, box), radius, stroke)
            self.rounded(draw, (line, line, box - line, box - line), radius - line, fill)
        else:
            self.rounded(draw, (0, 0, box, box), radius, fill)
        if check is not None:
            unit = box / 20
            draw.line(
                [(x * unit * _SS, y * unit * _SS)
                 for x, y in ((5.5, 10.5), (8.5, 13.5), (14.5, 7.0))],
                fill=check, width=round(1.4 * unit * _SS), joint="curve",
            )
        return self.finish(image, width, box)

    def switch(self, track_width, height, gap, fill, knob, knob_size, on,
               stroke=None):
        width = track_width + gap
        image = self.canvas(width, height)
        draw = ImageDraw.Draw(image)
        radius = height / 2
        line = self.px(1)
        if stroke is not None:
            self.rounded(draw, (0, 0, track_width, height), radius, stroke)
            self.rounded(draw, (line, line, track_width - line, height - line), radius - line, fill)
        else:
            self.rounded(draw, (0, 0, track_width, height), radius, fill)
        center_x = track_width - radius if on else radius
        half = knob_size / 2
        draw.ellipse(
            ((center_x - half) * _SS, (radius - half) * _SS,
             (center_x + half) * _SS, (radius + half) * _SS),
            fill=knob,
        )
        return self.finish(image, width, height)


def _icon_font(size):
    for name in _ICON_FONT_FILES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return None


def _render_icon(artist, glyph, color, size, gap):
    """The glyph in a ``size`` square, plus ``gap`` transparent pixels after it.

    The gap is how an icon keeps its distance from a button's text: ttk's
    compound label has no spacing option.
    """
    font = _icon_font(size)
    if font is None:
        return None
    image = Image.new("RGBA", (size + gap, size), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((size / 2, size / 2), glyph, font=font, fill=color, anchor="mm")
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


def _state(widget, ui=None):
    ui = ui or ui_theme.theme()
    return _themes.get((str(widget.tk.interpaddr()), theme_name(ui)))


def _display_scale(widget):
    # ``tk scaling`` is pixels per point; 96 DPI (100%) is 4/3.
    return float(widget.tk.call("tk", "scaling")) * 72 / 96


def install(window, ui=None):
    """Create (once) and select this palette's Fluent theme. Returns its name."""
    ui = ui or ui_theme.theme()
    style = ttk.Style(window)
    name = theme_name(ui)
    key = (str(window.tk.interpaddr()), name)
    if name not in style.theme_names():
        style.theme_create(name, parent="clam")
        style.theme_use(name)
        artist = _Artist(window, _display_scale(window))
        _themes[key] = _ThemeState(ui, artist)
        _configure(style, ui, artist)
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


def _configure(style, ui, artist):
    px = artist.px
    light = not ui.is_dark
    base = ui.card
    overlay = "#000000" if light else "#FFFFFF"
    text = ui.text
    muted = ui.text_muted
    font = ui.font()
    radius = px(4)

    style.configure(
        ".",
        background=ui.surface, foreground=text, font=font,
        bordercolor=ui.control_stroke, lightcolor=ui.surface, darkcolor=ui.surface,
        troughcolor=ui.surface, focuscolor=ui.focus_ring,
        selectbackground=ui.select_bg, selectforeground=ui.select_fg,
        insertcolor=text, fieldbackground=ui.field,
    )
    style.map(".", foreground=[("disabled", muted)])

    # -- Buttons ------------------------------------------------------------
    def face_element(name, faces):
        default, border = faces[0]
        specs = [(state, image) for state, (image, _border) in faces[1:]]
        # An image element defaults to its image's size as a minimum; the
        # wide tiling middle must not become the smallest control.
        style.element_create(
            name, "image", default, *specs,
            border=border, sticky="nsew", padding=0,
            width=2 * border, height=2 * border,
        )

    def elevated(fill, hover, pressed, stroke, bottom, disabled_fill):
        return [
            (None, artist.face(radius, fill, stroke, bottom)),
            ("disabled", artist.face(radius, disabled_fill, stroke, stroke)),
            ("pressed", artist.face(radius, pressed, stroke, stroke)),
            ("focus", artist.face(radius, fill, focus=ui.focus_ring)),
            ("active", artist.face(radius, hover, stroke, bottom)),
        ]

    def _pairs(faces):
        return [faces[0][1]] + [(state, pair) for state, pair in faces[1:]]

    disabled_fill = mix(base, overlay, 0.02)
    neutral = elevated(
        ui.control, ui.control_hover, ui.control_active,
        ui.control_stroke, ui.control_stroke_bottom, disabled_fill)
    face_element("Fluent.Button.face", _pairs(neutral))
    accent_bottom = mix(ui.accent, "#000000", 0.3)
    face_element("Fluent.Accent.face", _pairs([
        (None, artist.face(radius, ui.accent, ui.accent, accent_bottom)),
        ("disabled", artist.face(radius, mix(base, overlay, 0.16))),
        ("pressed", artist.face(radius, ui.accent_active)),
        ("focus", artist.face(radius, ui.accent, focus=ui.focus_ring if light else ui.text)),
        ("active", artist.face(radius, ui.accent_hover, ui.accent_hover, accent_bottom)),
    ]))
    # Subtle controls draw nothing at rest; hover and press are translucent
    # overlays, composited over whatever surface the style sits on.
    subtle_hover = _rgba(overlay, 0.05 if light else 0.08)
    subtle_pressed = _rgba(overlay, 0.03 if light else 0.05)
    clear = (0, 0, 0, 0)
    face_element("Fluent.Subtle.face", _pairs([
        (None, artist.face(radius, clear)),
        ("disabled", artist.face(radius, clear)),
        ("pressed", artist.face(radius, subtle_pressed)),
        ("focus", artist.face(radius, clear, focus=ui.focus_ring)),
        ("active", artist.face(radius, subtle_hover)),
    ]))
    face_element("Fluent.Nav.face", _pairs([
        (None, artist.face(radius, clear)),
        ("pressed", artist.face(radius, subtle_pressed)),
        ("selected", artist.face(radius, subtle_hover)),
        ("focus", artist.face(radius, clear, focus=ui.focus_ring)),
        ("active", artist.face(radius, subtle_hover)),
    ]))
    pill_width, pill_height = px(3), px(16)
    style.element_create(
        "Fluent.Nav.pill", "image", artist.blank(pill_width, pill_height),
        ("selected", artist.pill(pill_width, pill_height, ui.accent)),
        sticky="",
    )

    def button_layout(face, pill=False):
        label = [("Button.padding", {"sticky": "nsew", "children": [
            ("Button.label", {"sticky": "nsew"})]})]
        if pill:
            label.insert(0, ("Fluent.Nav.pill", {"side": "left", "sticky": ""}))
        return [(face, {"sticky": "nsew", "children": label})]

    button_padding = (px(11), px(5), px(11), px(6))
    for style_name, face in (
        ("TButton", "Fluent.Button.face"),
        ("Danger.TButton", "Fluent.Button.face"),
        ("Accent.TButton", "Fluent.Accent.face"),
        ("Subtle.TButton", "Fluent.Subtle.face"),
        ("Toolbar.TButton", "Fluent.Subtle.face"),
    ):
        style.layout(style_name, button_layout(face))
    style.layout("Nav.TButton", button_layout("Fluent.Nav.face", pill=True))
    style.configure(
        "TButton", padding=button_padding, anchor="center", foreground=text,
        font=font, focuscolor=ui.focus_ring,
    )
    style.map("TButton", foreground=[("disabled", muted), ("pressed", muted)])
    style.configure("Danger.TButton", foreground=ui.danger)
    style.map("Danger.TButton", foreground=[("disabled", muted)])
    style.configure("Accent.TButton", foreground=ui.text_on_accent)
    style.map("Accent.TButton", foreground=[("disabled", ui.card if light else muted)])
    style.configure("Subtle.TButton", padding=(px(8), px(5), px(8), px(6)))
    style.configure("Toolbar.TButton", padding=(px(6), px(4)))
    style.configure(
        "Nav.TButton", anchor="w", padding=(px(9), px(8), px(12), px(9)),
    )
    style.map(
        "Nav.TButton",
        font=[("selected", ui.font(ui_theme.BODY_FONT_SIZE, "bold"))],
        foreground=[("disabled", muted)],
    )

    # -- Text fields --------------------------------------------------------
    field = ui.field
    field_hover = mix(field, overlay, 0.03)
    field_disabled = mix(base, overlay, 0.03)
    field_faces = [
        (None, artist.face(radius, field, ui.control_stroke, ui.stroke_strong)),
        ("disabled", artist.face(radius, field_disabled, ui.control_stroke)),
        ("readonly", artist.face(radius, field_disabled, ui.control_stroke)),
        ("focus", artist.face(radius, field, ui.control_stroke, ui.accent, bottom_width=2)),
        ("hover", artist.face(radius, field_hover, ui.control_stroke, ui.stroke_strong)),
    ]
    face_element("Fluent.Field.face", _pairs(field_faces))
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
        "TEntry", padding=(px(10), px(6), px(6), px(7)), foreground=text,
        insertcolor=text, insertwidth=px(1), **selection,
    )
    # Containers for tk.Text/Listbox borrow the field face; their focus state
    # is set by hand (see text_area).
    style.layout("Field.TFrame", [("Fluent.Field.face", {"sticky": "nsew"})])

    # -- Combobox (always read-only here: a button with a chevron) ----------
    # No focus ring: a combobox takes focus on every click, unlike a button.
    face_element("Fluent.Combo.face", _pairs(
        [face for face in neutral if face[0] != "focus"]))
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
        "TCombobox", padding=(px(11), px(5), px(0), px(6)), foreground=text,
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
    box, gap = px(20), px(8)
    unchecked = _rgba(overlay, 0.02 if light else 0.1)
    unchecked_hover = _rgba(overlay, 0.06 if light else 0.14)
    check = ui.text_on_accent
    style.element_create(
        "Fluent.Check.indicator", "image",
        artist.checkbox(box, gap, unchecked, ui.stroke_strong),
        ("selected disabled", artist.checkbox(box, gap, mix(base, overlay, 0.2), check=base)),
        ("disabled", artist.checkbox(box, gap, clear, mix(base, overlay, 0.2))),
        ("pressed selected", artist.checkbox(box, gap, ui.accent_active, check=check)),
        ("active selected", artist.checkbox(box, gap, ui.accent_hover, check=check)),
        ("selected", artist.checkbox(box, gap, ui.accent, check=check)),
        ("pressed", artist.checkbox(box, gap, unchecked_hover, ui.stroke_strong)),
        ("active", artist.checkbox(box, gap, unchecked_hover, ui.stroke_strong)),
        sticky="",
    )
    track, height = px(40), px(20)
    knob, knob_hover = px(12), px(14)
    off_knob = mix(text, base, 0.35)
    switch_disabled = mix(base, overlay, 0.2)
    style.element_create(
        "Fluent.Switch.indicator", "image",
        artist.switch(track, height, gap, unchecked, off_knob, knob, False, ui.stroke_strong),
        ("selected disabled", artist.switch(track, height, gap, switch_disabled, base, knob, True)),
        ("disabled", artist.switch(track, height, gap, clear, switch_disabled, knob, False,
                                   switch_disabled)),
        ("active selected", artist.switch(track, height, gap, ui.accent_hover, check,
                                          knob_hover, True)),
        ("selected", artist.switch(track, height, gap, ui.accent, check, knob, True)),
        ("active", artist.switch(track, height, gap, unchecked_hover, off_knob, knob_hover,
                                 False, ui.stroke_strong)),
        sticky="",
    )
    for style_name, indicator in (
        ("TCheckbutton", "Fluent.Check.indicator"),
        ("Switch.TCheckbutton", "Fluent.Switch.indicator"),
    ):
        style.layout(style_name, [("Checkbutton.padding", {"sticky": "nsew", "children": [
            (indicator, {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nsew"})]})]})])
    style.configure(
        "TCheckbutton", padding=(0, px(4)), foreground=text, font=font,
        focuscolor=ui.focus_ring, focusthickness=1,
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
    # Clam's default row height is a fixed pixel count; at high DPI the
    # scaled text outgrows it and the rows overlap.
    linespace = tkfont.Font(root=artist.master, font=font).metrics("linespace")
    style.configure(
        "Treeview", background=ui.card, fieldbackground=ui.card, foreground=text,
        bordercolor=ui.card, lightcolor=ui.card, darkcolor=ui.card, borderwidth=0,
        rowheight=linespace + px(12),
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


def has_icons(widget, ui=None):
    """True where :func:`button` icons render; an icon-only button needs a
    text fallback everywhere else."""
    return _state(widget, ui) is not None and _icon_font(1) is not None


def icon_image(widget, name, color, *, gap=0, ui=None):
    """A Fluent icon glyph as a PhotoImage in ``color``, or None without the font."""
    state = _state(widget, ui)
    if state is None:
        return None
    color = resolve_color(widget, color)
    key = (name, color, gap)
    if key not in state.icons:
        artist = state.artist
        state.icons[key] = _render_icon(
            artist, ICONS[name], color, artist.px(16), artist.px(gap) if gap else 0)
    return state.icons[key]


def _icon_option(widget, icon, variant, with_text, ui):
    """``-image`` spec for a button icon, or None."""
    color = {
        "accent": ui.text_on_accent,
        "danger": ui.danger,
    }.get(variant, ui.text)
    gap = 8 if with_text else 0
    normal = icon_image(widget, icon, color, gap=gap, ui=ui)
    if normal is None:
        return None
    disabled = icon_image(widget, icon, ui.text_muted, gap=gap, ui=ui)
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


def set_icon(widget, icon, *, variant="standard", ui=None):
    """Show ``icon`` on a :func:`button`; a no-op without Fluent or the font."""
    ui = ui or ui_theme.theme()
    if not isinstance(widget, ttk.Button):
        return
    with_text = bool(str(widget.cget("text")))
    image = _icon_option(widget, icon, variant, with_text, ui)
    if image is not None:
        widget.configure(image=image, compound="left" if with_text else "image")


def nav_item(parent, text, command, *, icon=None, ui=None):
    """A section-navigation entry, packed into ``parent``. Returns its button.

    Fluent draws the selection pill inside the button; macOS keeps its
    native button with the accent bar beside it that it always had.
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
        marker.configure(bg=ui.accent if selected else marker.master.cget("background"))


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
    # element, so a style padding would let the child cover the border.
    px = _state(parent, ui).artist.px
    frame = ttk.Frame(
        parent, style=_surface_style(parent, "Field.TFrame", ui),
        padding=(px(4), px(4), px(4), px(4)),
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
