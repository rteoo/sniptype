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

    def test_wrapping_uses_the_allocated_cell_and_does_not_oscillate_one_pixel(self):
        label = mock.Mock()
        options = {"padx": 1, "borderwidth": 0, "wraplength": 0}
        label.cget.side_effect = options.__getitem__
        label.configure.side_effect = lambda **changed: options.update(changed)
        for width in (468, 469, 468, 469):
            ui_widgets.fit_label(label, width)
        self.assertEqual(label.configure.call_count, 1)
        self.assertLessEqual(options["wraplength"] + 2, 468)
        ui_widgets.fit_label(label, 247)
        self.assertLessEqual(options["wraplength"] + 2, 247)
        self.assertGreater(options["wraplength"], 230)

    def test_contrast_text_size_dpi_and_palette_have_distinct_image_sets(self):
        variants = [ui_theme.build_theme(kind, "windows", **options) for kind, options in (
            ("windows", {}), ("dark", {}), ("contrast", {}),
            ("contrast", {"text_scale": 2}), ("contrast", {"scale": 1.5}),
            ("contrast", {"contrast_signature": "changed"}),
        )]
        self.assertEqual(len({ui_widgets.theme_name(ui) for ui in variants}), len(variants))

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

    def test_contrast_faces_are_two_pixel_outlines_with_transparent_centers(self):
        artist = _artist()
        artist.contrast = True
        artist.outline = "#FFFFFF"
        face, _ = artist.face(4, "#E6A05A", margin=artist.margin)
        middle, edge = face.width // 2, artist.margin
        self.assertEqual(face.getpixel((middle, middle))[3], 0)
        for offset in (0, 1):
            self.assertEqual(_hex(face.getpixel((middle, edge + offset))), "#FFFFFF")
        self.assertEqual(face.getpixel((middle, edge + 2))[3], 0)
        checked = artist.checkbox(20, 8, "#E6A05A", "#FFFFFF", "#FFFFFF")
        self.assertEqual(checked.getpixel((artist.margin + 3, artist.margin + 3))[3], 0)
        switch = artist.switch(40, 20, 8, "#E6A05A", "#FFFFFF", 12, True, "#FFFFFF")
        self.assertEqual(switch.getpixel((artist.margin + 30, artist.margin + 10))[3], 0)

    def test_contrast_configuration_resolves_system_colors_only_at_draw_boundary(self):
        ui = ui_theme.build_theme("contrast", "windows")
        widget = mock.Mock()
        widget.winfo_rgb.return_value = (65535, 65535, 65535)
        artist = _artist()
        artist.master = widget
        elements = {}
        with mock.patch.object(ui_widgets.tkfont, "Font") as font:
            font.return_value.metrics.return_value = 18
            ui_widgets._configure(mock.Mock(), ui, artist, elements)
        self.assertTrue(elements)
        self.assertEqual(ui.text, "SystemWindowText")
        self.assertTrue(artist.contrast)
        for name in ("Fluent.Button.face", "Fluent.Accent.face", "Fluent.Subtle.face", "Fluent.Nav.face"):
            specs, default = elements[name]
            for image in [default, *(image for _, image in specs)]:
                self.assertEqual(image.getpixel((image.width // 2, image.height // 2))[3], 0, name)

    def test_contrast_style_pairs_remain_readable_when_window_and_button_colors_differ(self):
        # Window and Button system pairs need not coincide in a user's
        # contrast palette. Resolving all system colors to white hid both bugs.
        resolved = {"SystemWindow": "#000000", "SystemWindowText": "#FFFFFF",
                    "SystemButtonFace": "#FFFFFF", "SystemButtonText": "#000000",
                    "SystemHighlight": "#FFFF00", "SystemHighlightText": "#000000",
                    "SystemGrayText": "#808080"}
        ui = ui_theme.build_theme("contrast", "windows")
        style = mock.Mock()
        with mock.patch.object(ui_widgets, "resolve_color", side_effect=lambda _master, color: resolved[color]), \
                mock.patch.object(ui_widgets.tkfont, "Font") as font:
            font.return_value.metrics.return_value = 18
            ui_widgets._configure(style, ui, _artist(), {})
        maps = {call.args[0]: call.kwargs for call in style.map.call_args_list}
        configs = {call.args[0]: call.kwargs for call in style.configure.call_args_list}
        disabled = dict(maps["Accent.TButton"]["foreground"])["disabled"]
        self.assertEqual(disabled, resolved["SystemGrayText"])
        self.assertNotEqual(disabled, resolved["SystemWindow"])
        self.assertEqual(configs["Accent.TButton"]["foreground"], resolved["SystemWindowText"])
        combo = maps["TCombobox"]
        self.assertEqual(dict(combo["fieldbackground"])["readonly"], resolved["SystemWindow"])
        self.assertEqual(dict(combo["selectbackground"])["readonly"], resolved["SystemWindow"])
        self.assertEqual(dict(combo["selectforeground"])["readonly"], resolved["SystemWindowText"])
        self.assertEqual(configs["TCombobox"]["foreground"], resolved["SystemWindowText"])

    def test_regular_disabled_accent_and_readonly_combo_maps_keep_their_palette_contract(self):
        for kind in ("windows", "dark"):
            with self.subTest(kind=kind):
                ui = ui_theme.build_theme(kind, "windows")
                style = mock.Mock()
                with mock.patch.object(ui_widgets.tkfont, "Font") as font:
                    font.return_value.metrics.return_value = 18
                    ui_widgets._configure(style, ui, _artist(), {})
                maps = {call.args[0]: call.kwargs for call in style.map.call_args_list}
                self.assertEqual(dict(maps["Accent.TButton"]["foreground"])["disabled"],
                                 ui.text_muted if ui.is_dark else ui.card)
                self.assertEqual(dict(maps["TCombobox"]["selectbackground"])["readonly"], ui.control)
                self.assertEqual(dict(maps["TCombobox"]["fieldbackground"])["readonly"], ui.control)

    def test_control_face_is_rounded_filled_and_outlined(self):
        artist = _artist()
        image, border = artist.face(4, "#FFFFFF", "#7B8088")
        side = image.width
        self.assertEqual((side, side), image.size)
        # The corner is outside the rounded shape.
        self.assertLess(image.getpixel((0, 0))[3], 64)
        self.assertEqual(_hex(image.getpixel((side // 2, side // 2))), "#FFFFFF")
        # One field-border stroke all round: no darker elevation edge.
        self.assertEqual(_hex(image.getpixel((side // 2, 0))), "#7B8088")
        self.assertEqual(_hex(image.getpixel((side // 2, side - 1))), "#7B8088")
        # The nine-slice border keeps the whole corner out of the stretch.
        self.assertGreater(border, 4)

    def test_focused_field_has_a_thick_copper_underline(self):
        artist = _artist()
        image, _border = artist.face(4, "#FFFFFF", "#7B8088", "#A0520A", bottom_width=2)
        middle = image.width // 2
        self.assertEqual(_hex(image.getpixel((middle, image.height - 1))), "#A0520A")
        self.assertEqual(_hex(image.getpixel((middle, image.height - 2))), "#A0520A")
        self.assertEqual(_hex(image.getpixel((middle, image.height - 3))), "#FFFFFF")

    def test_focus_ring_is_outset_with_a_surface_gap(self):
        # Regression: the dark ring on the copper primary matched it at
        # 1.35:1; the ring now sits outside the face, past a gap that shows
        # the surface (transparent over the style background).
        artist = _artist()
        margin = artist.margin
        self.assertEqual((artist.ring, margin), (2, 3))
        rest, rest_border = artist.face(4, "#E6A05A", margin=margin)
        focused, focus_border = artist.face(4, "#E6A05A", focus="#F0C293", margin=margin)
        self.assertEqual(rest.size, focused.size)
        self.assertEqual(rest_border, focus_border)
        middle = focused.width // 2
        for y in (0, 1):
            self.assertEqual(_hex(focused.getpixel((middle, y))), "#F0C293")
            self.assertEqual(rest.getpixel((middle, y))[3], 0)
        self.assertEqual(focused.getpixel((middle, 2))[3], 0)
        for image in (rest, focused):
            self.assertEqual(_hex(image.getpixel((middle, margin))), "#E6A05A")
            self.assertEqual(_hex(image.getpixel((middle, middle))), "#E6A05A")
        with self.assertRaises(ValueError):
            artist.face(4, "#E6A05A", focus="#F0C293")

    def test_the_focus_margin_scales_with_the_display(self):
        artist = _artist(2.0)
        self.assertEqual((artist.ring, artist.margin), (4, 6))

    def test_images_scale_with_the_display(self):
        _small, small_border = _artist(1.0).face(4, "#FFFFFF", "#7B8088")
        _large, large_border = _artist(2.0).face(8, "#FFFFFF", "#7B8088")
        self.assertEqual(large_border, 2 * small_border)
        self.assertEqual(_artist(1.5).px(16), 24)

    def test_checked_box_is_a_copper_square_with_an_edge_and_a_mark(self):
        artist = _artist()
        margin = artist.margin
        image = artist.checkbox(20, 8, "#E6A05A", "#A0520A", check="#15100A")
        self.assertEqual((20 + 2 * margin + 8, 20 + 2 * margin), image.size)
        # The focus margin stays clear at rest.
        self.assertEqual(image.getpixel((1, 13))[3], 0)
        self.assertEqual(_hex(image.getpixel((margin, margin + 10))), "#A0520A")
        self.assertEqual(_hex(image.getpixel((margin + 3, margin + 3))), "#E6A05A")
        # The gap after the box is transparent, spacing it from the label.
        self.assertEqual(image.getpixel((20 + 2 * margin + 4, 13))[3], 0)
        mark = [image.getpixel((margin + x, margin + y))
                for x in range(4, 16) for y in range(6, 15)]
        self.assertTrue(any(_hex(pixel) == "#15100A" for pixel in mark))

    def test_focused_box_draws_its_ring_in_the_margin(self):
        artist = _artist()
        image = artist.checkbox(20, 8, "#FFFFFF", "#7B8088", focus="#263C56")
        middle = (20 + 2 * artist.margin) // 2
        self.assertEqual(_hex(image.getpixel((middle, 0))), "#263C56")
        self.assertEqual(image.getpixel((middle, 2))[3], 0)
        self.assertEqual(_hex(image.getpixel((middle, artist.margin))), "#7B8088")

    def test_switch_knob_sits_on_the_side_of_its_state(self):
        artist = _artist()
        margin = artist.margin
        on = artist.switch(40, 20, 8, "#E6A05A", "#15100A", 12, True, "#A0520A")
        off = artist.switch(40, 20, 8, "#FFFFFF", "#606060", 12, False, "#7B8088")
        self.assertEqual((40 + 2 * margin + 8, 20 + 2 * margin), on.size)
        self.assertEqual(_hex(on.getpixel((margin + 30, margin + 10))), "#15100A")
        self.assertEqual(_hex(on.getpixel((margin + 10, margin + 10))), "#E6A05A")
        self.assertEqual(_hex(on.getpixel((margin + 20, margin))), "#A0520A")
        self.assertEqual(_hex(off.getpixel((margin + 10, margin + 10))), "#606060")
        self.assertEqual(_hex(off.getpixel((margin + 30, margin + 10))), "#FFFFFF")
        focused = artist.switch(40, 20, 8, "#FFFFFF", "#606060", 12, False, "#7B8088",
                                focus="#263C56")
        self.assertEqual(_hex(focused.getpixel((margin + 20, 0))), "#263C56")
        self.assertEqual(focused.getpixel((margin + 20, 2))[3], 0)


class FactoryTests(unittest.TestCase):

    def test_icon_buttons_and_switches_refuse_missing_visible_labels(self):
        for text in ("", " "):
            with self.subTest(text=text), self.assertRaises(ValueError):
                ui_widgets.button(object(), text=text, icon="more", ui=self.windows)
            with self.subTest(text=text), self.assertRaises(ValueError):
                ui_widgets.switch(object(), text=text, ui=self.windows)

    def test_formatting_toolbar_keeps_text_and_every_switch_call_names_its_label(self):
        import ast
        from pathlib import Path
        source = (Path(__file__).parents[1] / "sniptype.pyw").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "ui_widgets":
                if node.func.attr == "switch":
                    self.assertTrue(any(option.arg == "text" for option in node.keywords), node.lineno)
                if node.func.attr == "button":
                    options = {option.arg: option.value for option in node.keywords}
                    if "icon" in options:
                        self.assertIn("text", options, node.lineno)
                        if isinstance(options["text"], ast.Constant):
                            self.assertTrue(str(options["text"].value).strip(), node.lineno)

    def test_all_production_icon_button_wrappers_keep_nonempty_text_branches(self):
        import ast
        from pathlib import Path
        source = Path(__file__).parents[1]
        for path in [*source.glob("*.py"), *source.glob("*.pyw")]:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in ("button", "_button"):
                    continue
                options = {option.arg: option.value for option in node.keywords}
                if "icon" not in options:
                    continue
                label = options.get("text") if node.func.attr == "button" else (
                    node.args[1] if len(node.args) > 1 else options.get("text"))
                self.assertIsNotNone(label, (path.name, node.lineno))
                for branch in ast.walk(label):
                    if isinstance(branch, ast.Constant) and isinstance(branch.value, str):
                        self.assertTrue(branch.value.strip(), (path.name, node.lineno))

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

    def test_macos_marks_the_current_page_with_the_copper_mark_tone(self):
        # Regression: the bar beside the current page took the raw copper
        # fill, 1.8:1 on the light sidebar; marks use accent_border.
        for kind in ("light", "dark"):
            theme = ui_theme.build_theme(kind, system="darwin")
            with self.subTest(kind=kind), mock.patch.object(ui_widgets.tk, "Button"), \
                    mock.patch.object(ui_widgets.tk, "Frame"):
                widget = ui_widgets.nav_item(mock.Mock(), "x", None, ui=theme)
                widget.marker.master.cget.return_value = theme.surface_alt
                ui_widgets.set_selected(widget, True, theme)
                widget.marker.configure.assert_called_with(bg=theme.accent_border)
                ui_widgets.set_selected(widget, False, theme)
                widget.marker.configure.assert_called_with(bg=theme.surface_alt)

    def test_a_signal_is_a_drawn_dot_without_a_glyph_and_when_no_icon_font_exists(self):
        # The quiet state is an 8 px dot in its own color, drawn rather than
        # typed, and a glyph that cannot be drawn degrades to the same dot
        # (the word beside it carries the meaning).
        import base64
        import io
        from PIL import Image

        widget = mock.Mock()
        widget.winfo_rgb.return_value = (0x16 << 8, 0x64 << 8, 0x3B << 8)
        with mock.patch.object(ui_widgets.tk, "PhotoImage", side_effect=lambda **kw: kw), \
                mock.patch.object(ui_widgets, "icon_image", return_value=None) as icon:
            plain = ui_widgets.signal_image(widget, "#16643B", ui=self.windows)
            no_font = ui_widgets.signal_image(widget, "#16643B", "pause", ui=self.windows)
        icon.assert_called_once()
        for label, photo in (("no glyph", plain), ("no icon font", no_font)):
            with self.subTest(label):
                dot = Image.open(io.BytesIO(base64.b64decode(photo["data"]))).convert("RGBA")
                size = self.windows.px(16)
                self.assertEqual((size, size), dot.size)
                self.assertEqual("#16643B", _hex(dot.getpixel((size // 2, size // 2))))
                self.assertEqual(0, dot.getpixel((0, 0))[3])
                row = [dot.getpixel((x, size // 2))[3] for x in range(size)]
                self.assertEqual(self.windows.px(8), sum(1 for alpha in row if alpha > 127))

    def test_gaps_between_fluent_faces_count_their_focus_margins(self):
        widget = mock.Mock(**{"tk.interpaddr.return_value": "face-gap-test"})
        # No installed theme (macOS, or before install): the padding is the gap.
        self.assertEqual(ui_widgets.face_gap(widget, 16, self.windows), 16)
        key = ("face-gap-test", ui_widgets.theme_name(self.windows))
        for scale, visible, expected in ((1.0, 16, 10), (1.0, 6, 0), (1.0, 4, 0), (2.0, 16, 4)):
            with self.subTest(scale=scale, visible=visible), mock.patch.dict(
                ui_widgets._themes,
                {key: ui_widgets._ThemeState(self.windows, _artist(scale))},
            ):
                self.assertEqual(ui_widgets.face_gap(widget, visible, self.windows), expected)

    def test_icon_fonts_belong_to_the_theme_seam(self):
        self.assertEqual(ui_theme.ICON_FONT_FILES, ("SegoeIcons.ttf", "segmdl2.ttf"))

    def test_icons_need_an_installed_theme(self):
        self.assertFalse(ui_widgets.has_icons(mock.Mock(**{"tk.interpaddr.return_value": 1}),
                                              self.windows))

    def test_every_icon_name_is_a_single_private_use_glyph(self):
        for name, glyph in ui_widgets.ICONS.items():
            self.assertEqual(len(glyph), 1, name)
            self.assertTrue(0xE000 <= ord(glyph) <= 0xF8FF, name)

    def test_a_trailing_icon_keeps_its_gap_before_the_glyph(self):
        # A drop-down chevron follows its text, so the spacing goes before it.
        artist = _artist()
        if ui_widgets._icon_font(16) is None:
            self.skipTest("no icon font on this host")
        before = ui_widgets._render_icon(artist, ui_widgets.ICONS["chevron_down"], "#FFFFFF", 16, 8)
        after = ui_widgets._render_icon(
            artist, ui_widgets.ICONS["chevron_down"], "#FFFFFF", 16, 8, leading=True)
        self.assertEqual((24, 16), before.size)
        self.assertEqual((24, 16), after.size)
        self.assertIsNone(before.crop((16, 0, 24, 16)).getbbox())
        self.assertIsNone(after.crop((0, 0, 8, 16)).getbbox())

    def test_macos_keeps_the_native_menu(self):
        with mock.patch.object(ui_widgets.tk, "Menu") as menu:
            ui_widgets.menu(object(), ui=self.mac)
        self.assertEqual({"tearoff": False}, menu.call_args.kwargs)


class DialogKitContractTests(unittest.TestCase):
    """The Tk-free half of the dialog kit; the dialogs themselves run on the
    shared root in test_manager_gui_smoke."""

    def test_a_prompt_without_its_window_fails_loudly(self):
        # It would belong to the hidden shared root and could open behind
        # the window the person acted in.
        for prompt in (
            lambda: ui_widgets.confirm(None, "t", "b", "Ok"),
            lambda: ui_widgets.ask_text(None, "t", "l", primary_label="Ok"),
            lambda: ui_widgets.alert(None, "t", "b"),
        ):
            with self.assertRaises(TypeError):
                prompt()

    def test_an_alert_tone_outside_the_ladder_fails_loudly(self):
        with self.assertRaises(ValueError):
            ui_widgets.alert(object(), "t", "b", tone="success")


if __name__ == "__main__":
    unittest.main()
