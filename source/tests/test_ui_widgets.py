"""Fluent ttk layer: drawn control images and the widget factories.

No Tk root here (see AGENTS.md on throwaway interpreters): the images are
checked as the Pillow images they are before Tk sees them, and the macOS
factory path with the classic widget classes mocked. The themed widgets
themselves are exercised on the shared root by test_manager_gui_smoke.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import ui_theme
import ui_widgets


def _artist(scale=1.0):
    """An artist whose "photos" are the Pillow images, for inspection."""
    artist = ui_widgets._Artist(master=None, scale=scale)
    artist.photo = lambda image: image
    return artist


def _hex(pixel):
    return "#" + "".join(f"{channel:02X}" for channel in pixel[:3])


class ColorTests(unittest.TestCase):

    def test_mix_moves_linearly_between_two_colors(self):
        self.assertEqual(ui_widgets.mix("#000000", "#FFFFFF", 0), "#000000")
        self.assertEqual(ui_widgets.mix("#000000", "#FFFFFF", 1), "#FFFFFF")
        self.assertEqual(ui_widgets.mix("#000000", "#FFFFFF", 0.5), "#808080")

    def test_each_palette_gets_its_own_theme(self):
        # Elements cannot be redefined, so a palette switch must select a
        # different theme rather than reconfigure the current one.
        light = ui_theme.build_theme("windows", system="windows")
        dark = ui_theme.build_theme("dark", system="windows")
        self.assertNotEqual(ui_widgets.theme_name(light), ui_widgets.theme_name(dark))


class DrawnImageTests(unittest.TestCase):

    def test_control_face_is_rounded_filled_and_elevated(self):
        artist = _artist()
        image, border = artist.face(4, "#FBFBFB", "#E5E5E5", "#C4C4C4")
        side = image.width
        self.assertEqual((side, side), image.size)
        # The corner is outside the rounded shape.
        self.assertLess(image.getpixel((0, 0))[3], 64)
        self.assertEqual(_hex(image.getpixel((side // 2, side // 2))), "#FBFBFB")
        self.assertEqual(_hex(image.getpixel((side // 2, 0))), "#E5E5E5")
        # The bottom edge carries the darker elevation stroke.
        self.assertEqual(_hex(image.getpixel((side // 2, side - 1))), "#C4C4C4")
        # The nine-slice border keeps the whole corner out of the stretch.
        self.assertGreater(border, 4)

    def test_focused_field_has_a_thick_accent_underline(self):
        artist = _artist()
        image, _border = artist.face(4, "#FFFFFF", "#E5E5E5", "#005FB8", bottom_width=2)
        middle = image.width // 2
        self.assertEqual(_hex(image.getpixel((middle, image.height - 1))), "#005FB8")
        self.assertEqual(_hex(image.getpixel((middle, image.height - 2))), "#005FB8")
        self.assertEqual(_hex(image.getpixel((middle, image.height - 3))), "#FFFFFF")

    def test_focus_ring_replaces_the_stroke(self):
        artist = _artist()
        image, _border = artist.face(4, "#FBFBFB", focus="#005FB8")
        middle = image.width // 2
        self.assertEqual(_hex(image.getpixel((middle, 0))), "#005FB8")
        self.assertEqual(_hex(image.getpixel((middle, 1))), "#005FB8")
        self.assertEqual(_hex(image.getpixel((middle, 2))), "#FBFBFB")

    def test_images_scale_with_the_display(self):
        _small, small_border = _artist(1.0).face(4, "#FBFBFB", "#E5E5E5")
        _large, large_border = _artist(2.0).face(8, "#FBFBFB", "#E5E5E5")
        self.assertEqual(large_border, 2 * small_border)
        self.assertEqual(_artist(1.5).px(16), 24)

    def test_checked_box_is_an_accent_square_with_a_mark(self):
        image = _artist().checkbox(20, 8, "#005FB8", check="#FFFFFF")
        self.assertEqual((28, 20), image.size)
        self.assertEqual(_hex(image.getpixel((3, 3))), "#005FB8")
        # The gap after the box is transparent, spacing it from the label.
        self.assertEqual(image.getpixel((24, 10))[3], 0)
        mark = [image.getpixel((x, y)) for x in range(4, 16) for y in range(6, 15)]
        self.assertTrue(any(_hex(pixel) == "#FFFFFF" for pixel in mark))

    def test_switch_knob_sits_on_the_side_of_its_state(self):
        artist = _artist()
        on = artist.switch(40, 20, 8, "#005FB8", "#FFFFFF", 12, True)
        off = artist.switch(40, 20, 8, "#FFFFFF", "#5C5C5C", 12, False, "#8A8A8A")
        self.assertEqual(_hex(on.getpixel((30, 10))), "#FFFFFF")
        self.assertEqual(_hex(on.getpixel((10, 10))), "#005FB8")
        self.assertEqual(_hex(off.getpixel((10, 10))), "#5C5C5C")
        self.assertEqual(_hex(off.getpixel((30, 10))), "#FFFFFF")


class FactoryTests(unittest.TestCase):

    def setUp(self):
        self.mac = ui_theme.build_theme("light", system="darwin")
        self.windows = ui_theme.build_theme("windows", system="windows")

    def test_only_macos_keeps_the_classic_widgets(self):
        self.assertFalse(ui_widgets.uses_fluent(self.mac))
        self.assertTrue(ui_widgets.uses_fluent(self.windows))
        self.assertTrue(ui_widgets.uses_fluent(ui_theme.build_theme("windows", system="linux")))

    def test_unknown_button_variant_fails_loudly(self):
        with self.assertRaises(ValueError):
            ui_widgets.button(object(), text="x", variant="primary", ui=self.windows)

    def test_macos_never_paints_a_natively_drawn_control(self):
        # Aqua ignores -background on buttons and checkboxes but honours
        # -foreground, so any color the app supplies can only turn the label
        # invisible against the bezel Aqua draws anyway (macOS 15 / Tk 9.0).
        painted = {
            "bg", "fg", "background", "foreground", "activebackground",
            "activeforeground", "selectcolor", "disabledforeground",
        }
        parent = object()
        with mock.patch.object(ui_widgets.tk, "Button") as button, \
                mock.patch.object(ui_widgets.tk, "Checkbutton") as check, \
                mock.patch.object(ui_widgets.tk, "Frame"):
            for variant in ui_widgets.VARIANTS:
                ui_widgets.button(parent, text="x", variant=variant, icon="save",
                                  width=10, ui=self.mac)
            ui_widgets.nav_item(mock.Mock(), "x", None, icon="document", ui=self.mac)
            ui_widgets.checkbox(parent, text="x", ui=self.mac)
            ui_widgets.switch(parent, text="x", ui=self.mac)
        for factory in (button, check):
            self.assertTrue(factory.call_args_list)
            for call in factory.call_args_list:
                self.assertFalse(painted & set(call.kwargs), call)

    def test_icons_need_an_installed_theme(self):
        self.assertFalse(ui_widgets.has_icons(mock.Mock(**{"tk.interpaddr.return_value": 1}),
                                              self.windows))

    def test_every_icon_name_is_a_single_private_use_glyph(self):
        for name, glyph in ui_widgets.ICONS.items():
            self.assertEqual(len(glyph), 1, name)
            self.assertTrue(0xE000 <= ord(glyph) <= 0xF8FF, name)


if __name__ == "__main__":
    unittest.main()
