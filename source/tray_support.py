"""The tray icon for each expansion state, derived from the shipped icon.

The tray is where a person sees SnipType all day, so it tells the same story
as the manager's sidebar: the shipped icon while expansion is on, and the
same icon with a badge in its corner while it is paused or the capture has
failed. The badge is drawn at runtime with Pillow, so no packaged asset
changes, and it differs by shape (pause bars, an alert mark) as well as by
color. Colors come from ``ui_theme.tray_badge_colors``.
"""

from PIL import Image, ImageDraw

import ui_theme
from health_support import (
    EXPANSION_DOWN,
    EXPANSION_OK,
    EXPANSION_PAUSED,
    expansion_label,
)

# Supersampling factor for the badge's anti-aliased edges.
_SS = 4
# Badge geometry, as fractions of the icon's side: the circle's center and
# radius, and the ring that separates it from the tile.
_CENTER = 0.69
_RADIUS = 0.265
_RING = 0.04


def tooltip(base, state):
    """The tray tooltip: the plain name while expansion is on, else the state."""
    if state == EXPANSION_OK:
        return base
    return f"{base} · {expansion_label(state)}"


def _ellipse(draw, center_x, center_y, radius, fill):
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        fill=fill,
    )


def _pause_bars(draw, size, fill):
    """Two rounded bars: the pause glyph."""
    height = 0.30 * size
    width = 0.085 * size
    gap = 0.075 * size
    top = _CENTER * size - height / 2
    for left in (_CENTER * size - gap / 2 - width, _CENTER * size + gap / 2):
        draw.rounded_rectangle(
            (left, top, left + width, top + height), radius=width / 2, fill=fill)


def _alert_mark(draw, size, fill):
    """A stem and a dot: the exclamation mark."""
    width = 0.095 * size
    center_x = _CENTER * size
    stem_top = _CENTER * size - 0.19 * size
    stem_bottom = _CENTER * size + 0.045 * size
    draw.rounded_rectangle(
        (center_x - width / 2, stem_top, center_x + width / 2, stem_bottom),
        radius=width / 2, fill=fill)
    _ellipse(draw, center_x, _CENTER * size + 0.145 * size, 0.06 * size, fill)


def state_icon(base, state):
    """``base`` for the state: untouched while expansion is on, else badged.

    ``base`` is the shipped icon image; it is never modified.
    """
    image = base.convert("RGBA")
    if state == EXPANSION_OK:
        return image
    fill, glyph, ring = ui_theme.tray_badge_colors(state)
    size = image.width * _SS
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    _ellipse(draw, _CENTER * size, _CENTER * size, (_RADIUS + _RING) * size, ring)
    _ellipse(draw, _CENTER * size, _CENTER * size, _RADIUS * size, fill)
    if state == EXPANSION_PAUSED:
        _pause_bars(draw, size, glyph)
    elif state == EXPANSION_DOWN:
        _alert_mark(draw, size, glyph)
    else:
        raise ValueError(f"no tray icon for state {state!r}")
    layer = layer.resize(image.size, Image.LANCZOS)
    return Image.alpha_composite(image, layer)


__all__ = ["state_icon", "tooltip"]
