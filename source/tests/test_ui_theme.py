"""Per-OS palette/font resolution for the manager GUI.

The load-bearing guarantee is the first test class: on Windows every token must
resolve to the deliberate Fluent palette, while the macOS safety seam remains
platform-native.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import ui_theme


# Windows Design System 1.0.0 roles are pinned here so a later palette change
# requires an explicit review. ``control`` is the documented SnipType neutral
# button adaptation, kept distinct from the design system's hover fill.
FLUENT_WINDOWS_COLORS = {
    "surface": "#F3F3F3",
    "surface_alt": "#FFFFFF",
    "surface_alt_active": "#DEDEDE",
    "surface_hover": "#EAEAEA",
    "card": "#FFFFFF",
    "field": "#FFFFFF",
    "field_hover": "#EAEAEA",
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
    "text_native": "#1A1A1A",
    "tab_unselected_fg": "#5C5C5C",
}

WDS_DARK_COLORS = {
    "surface": "#202020",
    "card": "#2B2B2B",
    "text": "#F5F5F5",
    "text_muted": "#C4C4C4",
    "border": "#494949",
    "control_border": "#A0A0A0",
    "accent": "#60CDFF",
    "text_on_accent": "#003047",
    "select_bg": "#153F54",
    "focus_ring": "#75D5FF",
    "warning": "#FFD479",
    "danger": "#FFB4B8",
}


class WindowsPaletteTests(unittest.TestCase):
    """Windows must keep the intentional Fluent palette stable."""

    def test_every_fluent_token_keeps_its_declared_literal(self):
        colors = ui_theme.palette("windows")
        for token, expected in FLUENT_WINDOWS_COLORS.items():
            self.assertEqual(colors[token], expected, token)

    def test_dark_semantic_roles_match_the_adopted_design_system(self):
        colors = ui_theme.palette("dark", "windows")
        for token, expected in WDS_DARK_COLORS.items():
            self.assertEqual(colors[token], expected, token)

    def test_windows_fonts_use_the_design_system_family(self):
        theme = ui_theme.build_theme("windows", system="windows")
        self.assertEqual(theme.font(), ("Segoe UI Variable", 10))
        self.assertEqual(theme.font(12, "bold"), ("Segoe UI Variable", 12, "bold"))
        self.assertEqual(theme.emoji_font(12), ("Segoe UI Emoji", 12))
        self.assertEqual(theme.mono_font(10, "bold"), ("Consolas", 10, "bold"))
        self.assertEqual(theme.symbol_family, "Segoe UI Symbol")

    def test_windows_ignores_a_system_default_size(self):
        # Windows is the reference scale; probing must not shift it.
        theme = ui_theme.build_theme("windows", system="windows", default_size=13)
        self.assertEqual(theme.size_delta, 0)
        self.assertEqual(theme.font(9), ("Segoe UI Variable", 9))

    def test_windows_prefers_vista(self):
        self.assertEqual(ui_theme.ttk_theme_preference("windows")[0], "vista")


class MacPaletteTests(unittest.TestCase):

    def test_backgrounds_and_text_use_aqua_dynamic_colors(self):
        # Only these follow a live appearance switch; hardcoding them is the
        # bug this module exists to fix.
        for kind in ("light", "dark"):
            colors = ui_theme.palette(kind)
            self.assertEqual(colors["surface"], "systemWindowBackgroundColor")
            self.assertEqual(colors["card"], "systemTextBackgroundColor")
            self.assertEqual(colors["field"], "systemTextBackgroundColor")
            self.assertEqual(colors["text"], "systemTextColor")
            self.assertEqual(colors["text_strong"], "systemTextColor")

    def test_alpha_carrying_system_colors_are_never_used(self):
        # Tk drops the alpha channel and hands back pure white, which is
        # invisible on the dark surface -- these must stay fixed grays.
        broken = {
            "systemSecondaryLabelColor",
            "systemSeparatorColor",
            "systemPlaceholderTextColor",
            "systemDisabledControlTextColor",
        }
        for kind in ("light", "dark"):
            for token, value in ui_theme.palette(kind).items():
                self.assertNotIn(value, broken, f"{kind}/{token}")

    def test_dark_mode_replaces_the_light_greys_and_dim_accents(self):
        light = ui_theme.palette("light")
        dark = ui_theme.palette("dark")
        for token in ("surface_alt", "border", "divider", "text_muted",
                      "link", "warning", "success"):
            self.assertNotEqual(dark[token], light[token], token)

    def test_no_literal_color_leaks_from_the_windows_palette_into_dark(self):
        windows = set(ui_theme.palette("windows").values())
        dark = ui_theme.palette("dark")
        # The brand accent is deliberately shared; everything else must differ.
        shared = {token for token, value in dark.items() if value in windows}
        self.assertEqual(shared, {"accent", "accent_active", "text_on_accent"})

    def test_mac_fonts_use_the_system_families(self):
        theme = ui_theme.build_theme("dark", system="darwin")
        self.assertEqual(theme.family, ".AppleSystemUIFont")
        self.assertEqual(theme.emoji_family, "Apple Color Emoji")
        self.assertEqual(theme.mono_family, "Menlo")
        self.assertNotIn("Segoe", theme.symbol_family)

    def test_mac_sizes_shift_onto_the_platform_scale(self):
        # The body role must land on the platform's own default size rather
        # than below every native control.
        theme = ui_theme.build_theme("light", system="darwin", default_size=13)
        self.assertEqual(theme.size_delta, 3)
        self.assertEqual(theme.font(10), (".AppleSystemUIFont", 13))
        self.assertEqual(theme.font(12, "bold"), (".AppleSystemUIFont", 15, "bold"))

    def test_an_unreadable_default_size_leaves_the_scale_alone(self):
        for probe in (None, 0):
            theme = ui_theme.build_theme("light", system="darwin", default_size=probe)
            self.assertEqual(theme.size_delta, 0)

    def test_mac_prefers_aqua(self):
        self.assertEqual(ui_theme.ttk_theme_preference("darwin")[0], "aqua")


class AppearanceDetectionTests(unittest.TestCase):

    def test_luminance_classification(self):
        self.assertEqual(ui_theme.appearance_kind(0.0), "dark")
        self.assertEqual(ui_theme.appearance_kind(0.12), "dark")
        self.assertEqual(ui_theme.appearance_kind(0.93), "light")
        self.assertEqual(ui_theme.appearance_kind(1.0), "light")

    def test_probe_failure_falls_back_to_light(self):
        class Broken:
            def winfo_rgb(self, _name):
                raise RuntimeError("no such color")

        self.assertEqual(ui_theme._probe_kind(Broken(), "darwin"), "light")

    def test_probe_reads_the_window_background(self):
        class Fake:
            def __init__(self, rgb):
                self.rgb = rgb
                self.asked = None

            def winfo_rgb(self, name):
                self.asked = name
                return self.rgb

        dark = Fake((7710, 7710, 7710))
        self.assertEqual(ui_theme._probe_kind(dark, "darwin"), "dark")
        self.assertEqual(dark.asked, "systemWindowBackgroundColor")
        self.assertEqual(
            ui_theme._probe_kind(Fake((60652, 60652, 60652)), "darwin"), "light"
        )

    def test_windows_never_probes(self):
        class Exploding:
            def winfo_rgb(self, _name):
                raise AssertionError("Windows must not query Aqua colors")

        with mock.patch.object(ui_theme, "_windows_apps_use_light_theme", return_value=True):
            self.assertEqual(ui_theme._probe_kind(Exploding(), "windows"), "windows")

    def test_windows_follows_the_apps_theme_switch(self):
        with mock.patch.object(ui_theme, "_windows_apps_use_light_theme", return_value=False):
            self.assertEqual(ui_theme._probe_kind(object(), "windows"), "dark")

    def test_an_unreadable_windows_switch_keeps_the_light_palette(self):
        with mock.patch.object(ui_theme, "_windows_apps_use_light_theme", return_value=None):
            self.assertEqual(ui_theme._probe_kind(object(), "windows"), "windows")


class ThemeCacheTests(unittest.TestCase):

    def setUp(self):
        ui_theme.reset()
        self.addCleanup(ui_theme.reset)

    def test_theme_resolves_without_a_widget(self):
        theme = ui_theme.theme()
        self.assertIn(theme.kind, ("windows", "light"))

    def test_bind_replaces_the_cached_theme(self):
        first = ui_theme.bind(None, system="windows")
        self.assertIs(ui_theme.theme(), first)
        second = ui_theme.bind(None, system="darwin")
        self.assertIsNot(second, first)
        self.assertIs(ui_theme.theme(), second)

    def test_widgetless_bind_never_claims_dark(self):
        # Guessing dark and being wrong is the unreadable case; light is the
        # historical behavior.
        self.assertEqual(ui_theme.bind(None, system="darwin").kind, "light")


class WidgetOptionTests(unittest.TestCase):

    def test_widget_helpers_are_inert_off_macos(self):
        # Win32's own defaults for these widgets are already correct; pinning
        # them would swap the user's selection color for the app's blue.
        for system in ("windows", "linux"):
            theme = ui_theme.build_theme("windows", system=system)
            self.assertEqual(theme.entry_colors(), {})
            self.assertEqual(theme.text_colors(), {})
            self.assertEqual(theme.listbox_colors(), {})
            self.assertEqual(theme.checkbutton_colors("#FFFFFF")["bg"], "#FFFFFF")
            self.assertEqual(theme.button_colors()["bg"], "#E6E6E6")

    def test_added_foregrounds_resolve_to_each_platform_default(self):
        # `text_native` is for widgets the pre-change GUI left uncolored, so it
        # has to *be* the platform default rather than the app's near-black.
        self.assertEqual(
            ui_theme.build_theme("windows", system="windows").text_native,
            "SystemButtonText",
        )
        self.assertEqual(
            ui_theme.build_theme("dark", system="darwin").text_native,
            "systemTextColor",
        )
        # X11 has neither name.
        self.assertEqual(
            ui_theme.build_theme("windows", system="linux").text_native, "#1A1A1A"
        )

    def test_windows_keeps_its_button_widths_and_window_size(self):
        theme = ui_theme.build_theme("windows", system="windows")
        self.assertEqual(theme.button_width(12), 12)
        self.assertEqual(theme.manager_window_size, ("1280x800", 1180, 760))
        self.assertFalse(theme.stacked_toolbar_status)

    def test_linux_minimum_leaves_room_for_x11_font_metrics(self):
        theme = ui_theme.build_theme("windows", system="linux")
        geometry, min_width, min_height = theme.manager_window_size
        self.assertEqual((1100, 780), (min_width, min_height))
        # The default must not start below the minimum.
        self.assertGreaterEqual(int(geometry.split("x")[1]), min_height)

    def test_fluent_spacing_and_tree_density_are_stable(self):
        theme = ui_theme.build_theme("windows", system="windows")
        self.assertEqual(
            (theme.space_xs, theme.space_sm, theme.space_md,
             theme.space_lg, theme.space_xl),
            (4, 8, 12, 16, 24),
        )
        self.assertEqual(theme.tree_row_height, 44)

    def test_macos_sizes_buttons_to_their_text_and_widens_the_window(self):
        # Aqua's bezel has a minimum width the flat Win32 button does not, so
        # the tuned character widths overflow their pane and clip the last
        # button in the row.
        theme = ui_theme.build_theme("dark", system="darwin")
        self.assertEqual(theme.button_width(12), 0)
        geometry, min_width, _ = theme.manager_window_size
        self.assertEqual(geometry, "1300x760")
        self.assertGreater(min_width, 820)
        self.assertTrue(theme.stacked_toolbar_status)

    def test_macos_never_paints_a_natively_drawn_control(self):
        # Aqua ignores -background on buttons and checkboxes but honours
        # -foreground, so any color the app supplies can only turn the title
        # invisible against the bezel Aqua draws anyway (macOS 15 / Tk 9.0).
        theme = ui_theme.build_theme("dark", system="darwin")
        self.assertEqual(theme.button_colors(), {})
        self.assertEqual(theme.button_colors(accent=True), {})
        self.assertEqual(theme.checkbutton_colors("#222"), {})
        self.assertEqual(theme.toolbar_button_colors("#222"), {})
        self.assertEqual(theme.glyph_button_colors("#222"), {})

    def test_entry_colors_pin_every_channel_aqua_would_theme(self):
        theme = ui_theme.build_theme("dark", system="darwin")
        colors = theme.entry_colors()
        for option in ("bg", "fg", "insertbackground", "selectbackground",
                       "selectforeground"):
            self.assertIn(option, colors)
        self.assertEqual(colors["bg"], theme.field)
        self.assertEqual(colors["fg"], theme.text)

    def test_text_colors_drop_the_options_tk_text_rejects(self):
        colors = ui_theme.build_theme("dark", system="darwin").text_colors()
        self.assertNotIn("disabledbackground", colors)
        self.assertNotIn("disabledforeground", colors)
        self.assertIn("inactiveselectbackground", colors)

    def test_button_colors_always_pair_a_foreground_with_a_background(self):
        for kind in ("windows", "light", "dark"):
            theme = ui_theme.build_theme(kind, system="windows")
            for accent in (False, True):
                colors = theme.button_colors(accent=accent)
                self.assertEqual(
                    set(colors),
                    {"bg", "fg", "activebackground", "activeforeground"},
                )

    def test_fluent_button_chrome_has_consistent_geometry_and_focus(self):
        theme = ui_theme.build_theme("windows", system="windows")
        self.assertEqual(
            theme.button_chrome(),
            {
                "relief": "flat", "bd": 0, "padx": 16, "pady": 9,
                "highlightthickness": 1, "highlightbackground": theme.control_border,
                "highlightcolor": theme.focus_ring, "cursor": "hand2",
            },
        )
        compact = theme.button_chrome(compact=True)
        self.assertEqual(compact["padx"], 12)
        self.assertEqual(compact["pady"], 6)

    def test_danger_button_uses_distinct_semantic_tokens(self):
        theme = ui_theme.build_theme("windows", system="windows")
        colors = theme.button_colors(danger=True)
        self.assertEqual(colors["bg"], theme.danger)
        self.assertEqual(colors["activebackground"], theme.danger_active)
        self.assertEqual(colors["fg"], theme.text_on_accent)

    def test_toolbar_buttons_use_the_editor_surface_and_hover_token(self):
        colors = ui_theme.build_theme("windows", system="windows").toolbar_button_colors("#FFFFFF")
        self.assertEqual(colors["bg"], "#FFFFFF")
        self.assertEqual(colors["activebackground"], "#EAEAEA")

    def test_accent_button_uses_the_fluent_windows_tokens(self):
        colors = ui_theme.build_theme("windows", system="windows").button_colors(accent=True)
        self.assertEqual(colors["bg"], "#005FB8")
        self.assertEqual(colors["fg"], "#FFFFFF")
        self.assertEqual(colors["activebackground"], "#004A91")

    def test_toolbar_frame_uses_the_editor_card_surface(self):
        for system in ("windows", "linux"):
            theme = ui_theme.build_theme("windows", system=system)
            self.assertEqual(theme.toolbar_frame_colors(), {"bg": theme.card})

    def test_toolbar_frame_keeps_the_card_surface_on_macos(self):
        theme = ui_theme.build_theme("dark", system="darwin")
        self.assertEqual(theme.toolbar_frame_colors(), {"bg": theme.card})

    def test_status_label_uses_the_body_face_and_muted_grey(self):
        for system in ("windows", "linux"):
            options = ui_theme.build_theme("windows", system=system).status_label_options()
            theme = ui_theme.build_theme("windows", system=system)
            self.assertEqual(options["font"], theme.font(8))
            self.assertEqual(options["fg"], theme.text_muted)

    def test_status_label_uses_the_body_face_and_muted_grey_on_macos(self):
        theme = ui_theme.build_theme("dark", system="darwin")
        options = theme.status_label_options()
        self.assertEqual(options["font"], theme.font(8))
        self.assertEqual(options["fg"], theme.text_muted)

    def test_unselected_tab_foreground_uses_the_fluent_neutral(self):
        for system in ("windows", "linux"):
            self.assertEqual(
                ui_theme.build_theme("windows", system=system).tab_unselected_fg,
                "#5C5C5C",
            )

    def test_unselected_tab_foreground_follows_the_appearance_on_macos(self):
        # The selected tab keeps `text`; the unselected one tracks the system
        # text color exactly as PR56 shipped it (via text_strong).
        for kind in ("light", "dark"):
            theme = ui_theme.build_theme(kind, system="darwin")
            self.assertEqual(theme.tab_unselected_fg, "systemTextColor")
            self.assertEqual(theme.tab_unselected_fg, theme.text_strong)


class TtkThemeSelectionTests(unittest.TestCase):

    class FakeStyle:
        def __init__(self, available, current="default"):
            self.available = available
            self.current = current
            self.used = []

        def theme_names(self):
            return self.available

        def theme_use(self, name=None):
            if name is None:
                return self.current
            if name not in self.available:
                raise RuntimeError("no such theme")
            self.used.append(name)
            self.current = name
            return name

    def test_picks_the_first_available_preference(self):
        style = self.FakeStyle(("aqua", "clam", "default"))
        self.assertEqual(ui_theme.apply_ttk_theme(style, "darwin"), "aqua")
        self.assertEqual(style.used, ["aqua"])

    def test_skips_a_theme_this_platform_lacks(self):
        # This is the actual bug: "vista" does not exist off Windows, and the
        # old bare try/except left whatever theme was already active.
        style = self.FakeStyle(("aqua", "clam", "default"))
        self.assertEqual(ui_theme.apply_ttk_theme(style, "windows"), "default")
        self.assertEqual(style.used, ["default"])

    def test_never_raises_when_ttk_misbehaves(self):
        class Broken:
            def theme_names(self):
                raise RuntimeError("no ttk")

        self.assertIsNone(ui_theme.apply_ttk_theme(Broken(), "windows"))


class GuiSourceTests(unittest.TestCase):
    """The GUI must go through the seam; a literal here is the bug returning."""

    SOURCE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "sniptype.pyw"
    )

    def _source(self):
        with open(self.SOURCE, encoding="utf-8") as handle:
            return handle.read()

    def test_no_hardcoded_colors_left_in_the_gui(self):
        import re
        self.assertEqual(re.findall(r'"#[0-9A-Fa-f]{3,8}"', self._source()), [])

    def test_no_windows_only_font_families_left_in_the_gui(self):
        import re
        leaked = re.findall(r'"(Segoe[^"]*|Consolas|Arial|Helvetica)"', self._source())
        self.assertEqual(leaked, [])

    def test_buttons_and_checkboxes_never_take_a_color_directly(self):
        """Aqua draws these itself; their colors must come from the seam.

        A literal ``fg=`` here is invisible on macOS rather than merely
        off-palette: Aqua keeps its own light bezel whatever ``bg`` says, and
        then honours the foreground, so the label vanishes into the bezel.
        """
        import ast
        color_options = {
            "bg", "fg", "background", "foreground", "activebackground",
            "activeforeground", "selectcolor", "disabledforeground",
        }
        offenders = []
        for node in ast.walk(ast.parse(self._source())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute)
                    and func.attr in ("Button", "Checkbutton")):
                continue
            for keyword in node.keywords:
                if keyword.arg in color_options:
                    offenders.append((node.lineno, func.attr, keyword.arg))
        self.assertEqual(offenders, [])

    def test_the_windows_only_ttk_theme_is_no_longer_forced(self):
        self.assertNotIn('theme_use("vista")', self._source())



def _contrast(first, second):
    """WCAG contrast ratio between two ``#RRGGBB`` colors."""
    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class ContrastTests(unittest.TestCase):
    """Legibility floors for the two opaque palettes (WCAG 2.x ratios)."""

    def _palettes(self):
        return {
            "light": ui_theme.palette("windows", "linux"),
            "dark": ui_theme.palette("dark", "windows"),
        }

    def test_body_and_muted_text_are_readable_on_every_surface(self):
        for name, colors in self._palettes().items():
            for surface in ("surface", "surface_alt", "card", "field", "control"):
                self.assertGreaterEqual(
                    _contrast(colors["text"], colors[surface]), 7, (name, surface))
            for surface in ("surface", "card"):
                self.assertGreaterEqual(
                    _contrast(colors["text_muted"], colors[surface]), 4.5, (name, surface))

    def test_tinted_buttons_keep_their_labels_readable(self):
        for name, colors in self._palettes().items():
            for fill in ("accent", "accent_active", "danger", "danger_active"):
                self.assertGreaterEqual(
                    _contrast(colors["text_on_accent"], colors[fill]), 4.5, (name, fill))

    def test_selected_rows_stay_readable(self):
        for name, colors in self._palettes().items():
            self.assertGreaterEqual(
                _contrast(colors["select_fg"], colors["select_bg"]), 4.5, name)

    def test_neutral_buttons_stand_out_from_what_they_sit_on(self):
        # Regression: the fill used to be #FAFAFA, ~1.04:1 against the white
        # cards, so Novo/Editar/Duplicar read as plain text.
        for name, colors in self._palettes().items():
            for surface in ("card", "surface"):
                self.assertGreaterEqual(
                    _contrast(colors["control"], colors[surface]), 1.1, (name, surface))

    def test_the_dark_palette_defines_every_light_token(self):
        self.assertEqual(
            set(ui_theme.palette("dark", "windows")), set(ui_theme.palette("windows", "linux")))


class AppearancePreferenceTests(unittest.TestCase):

    def setUp(self):
        ui_theme.reset()
        self.addCleanup(ui_theme.reset)

    def test_unknown_values_fall_back_to_the_system(self):
        for value in (None, "", "Dark", 1, "auto"):
            self.assertEqual(ui_theme.normalize_preference(value), "system")
        self.assertEqual(ui_theme.set_preference("bogus"), "system")

    def test_labels_cover_every_choice(self):
        self.assertEqual(set(ui_theme.APPEARANCE_LABELS), set(ui_theme.APPEARANCE_CHOICES))
        self.assertEqual(set(ui_theme.APPEARANCE_STATUS), set(ui_theme.APPEARANCE_CHOICES))

    def test_a_fixed_choice_overrides_the_windows_switch(self):
        with mock.patch.object(ui_theme, "_windows_apps_use_light_theme", return_value=False), \
                mock.patch.object(ui_theme, "_probe_default_size", return_value=None):
            ui_theme.set_preference("light")
            self.assertFalse(ui_theme.bind(object(), system="windows").is_dark)
        with mock.patch.object(ui_theme, "_windows_apps_use_light_theme", return_value=True), \
                mock.patch.object(ui_theme, "_probe_default_size", return_value=None):
            ui_theme.set_preference("dark")
            self.assertTrue(ui_theme.bind(object(), system="windows").is_dark)

    def test_system_choice_follows_the_windows_switch(self):
        with mock.patch.object(ui_theme, "_windows_apps_use_light_theme", return_value=False), \
                mock.patch.object(ui_theme, "_probe_default_size", return_value=None):
            theme = ui_theme.bind(object(), system="windows")
        self.assertTrue(theme.is_dark)
        self.assertEqual(theme.preference, "system")

    def test_every_later_bind_keeps_the_choice(self):
        # Dialogs re-bind against their own parent; they must not snap back
        # to the system appearance.
        ui_theme.set_preference("dark")
        self.assertTrue(ui_theme.bind(None, system="windows").is_dark)
        self.assertTrue(ui_theme.theme().is_dark)

    def test_a_fixed_choice_on_macos_uses_the_opaque_palette(self):
        # Aqua's dynamic names would follow the OS and override the user.
        theme = ui_theme.build_theme("dark", system="darwin", preference="dark")
        self.assertEqual(theme.surface, ui_theme.palette("dark", "windows")["surface"])
        self.assertEqual(theme.text_native, "systemTextColor")
        system = ui_theme.build_theme("dark", system="darwin", preference="system")
        self.assertEqual(system.surface, "systemWindowBackgroundColor")


class DarkWidgetOptionTests(unittest.TestCase):

    def setUp(self):
        self.dark = ui_theme.build_theme("dark", system="windows")

    def test_classic_fields_are_painted_in_dark(self):
        entry = self.dark.entry_colors()
        self.assertEqual(entry["bg"], self.dark.field)
        self.assertEqual(entry["fg"], self.dark.text)
        self.assertEqual(entry["readonlybackground"], self.dark.surface_alt)
        self.assertNotIn("readonlybackground", self.dark.text_colors())
        self.assertEqual(self.dark.listbox_colors()["bg"], self.dark.field)

    def test_field_colors_never_collide_with_field_chrome(self):
        # form_editor_dialog splats both into one tk.Listbox call; a shared
        # key is a TypeError at runtime.
        for kind in ("windows", "dark"):
            theme = ui_theme.build_theme(kind, system="windows")
            self.assertFalse(set(theme.listbox_colors()) & set(theme.field_chrome()))
            self.assertFalse(set(theme.entry_colors()) & set(theme.field_chrome()))

    def test_dark_checkboxes_keep_a_visible_mark(self):
        colors = self.dark.checkbutton_colors(self.dark.card)
        self.assertEqual(colors["selectcolor"], self.dark.field)
        light = ui_theme.build_theme("windows", system="windows")
        self.assertNotIn("selectcolor", light.checkbutton_colors("#FFFFFF"))

    def test_dark_selects_clam_off_macos_only(self):
        self.assertEqual(ui_theme.ttk_theme_preference("windows", dark=True)[0], "clam")
        self.assertEqual(ui_theme.ttk_theme_preference("linux", dark=True)[0], "clam")
        self.assertEqual(ui_theme.ttk_theme_preference("darwin", dark=True)[0], "aqua")

    def test_apply_ttk_theme_uses_the_resolved_appearance(self):
        style = TtkThemeSelectionTests.FakeStyle(("vista", "clam", "default"))
        self.assertEqual(ui_theme.apply_ttk_theme(style, "windows", resolved=self.dark), "clam")

    def test_nav_buttons_mark_the_selected_section_with_the_accent(self):
        self.assertEqual(self.dark.nav_button_colors("#000000", selected=True)["fg"], self.dark.accent)
        self.assertEqual(self.dark.nav_button_colors("#000000")["fg"], self.dark.text_native)
        self.assertEqual(ui_theme.build_theme("dark", system="darwin").nav_button_colors("#000"), {})

    def test_window_chrome_is_a_no_op_off_windows(self):
        mac = ui_theme.build_theme("light", system="darwin")
        self.assertFalse(ui_theme.apply_window_chrome(object(), mac))

if __name__ == "__main__":
    unittest.main()
