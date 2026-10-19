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


# Teô Personal DS 2.7.1 Windows-family roles (Ink & Copper) are pinned here so
# a later palette change requires an explicit review. Surfaces and neutrals
# come from native/windows/tokens.css, the copper and state pairs from
# native/foundations.css and tokens.css; control_active is a Tk adaptation
# recorded in DESIGN.md.
FLUENT_WINDOWS_COLORS = {
    "surface": "#E9E8E7",
    "surface_alt": "#E9E8E7",
    "surface_alt_active": "#E8E6E3",
    "card": "#F6F5F4",
    "field": "#FFFFFF",
    "control": "#FFFFFF",
    "control_hover": "#E8E6E3",
    "control_active": "#DEDCD8",
    "control_stroke": "#7B8088",
    "control_stroke_bottom": "#7B8088",
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
    "text_native": "#202630",
}

WDS_DARK_COLORS = {
    "surface": "#292929",
    "surface_alt": "#292929",
    "surface_alt_active": "#484848",
    "card": "#232323",
    "field": "#1C1C1E",
    "control": "#1C1C1E",
    "control_hover": "#484848",
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

# Win DS 1.0 blues and selections the 2.7.1 adoption removed.
RETIRED_BLUES = {"#005FB8", "#60CDFF", "#153F54", "#DCEEFF", "#75D5FF", "#1A6FBF"}


class WindowsPaletteTests(unittest.TestCase):
    """Windows must keep the intentional DS 2.7.1 palette stable."""

    def test_every_fluent_token_keeps_its_declared_literal(self):
        for old_test, args, pinned in (
            ("test_every_fluent_token_keeps_its_declared_literal",
             ("windows",), FLUENT_WINDOWS_COLORS),
            ("test_dark_semantic_roles_match_the_adopted_design_system",
             ("dark", "windows"), WDS_DARK_COLORS),
        ):
            with self.subTest(old_test):
                colors = ui_theme.palette(*args)
                # Every token is pinned, so a new one needs a reviewed value.
                self.assertEqual(set(pinned), set(colors))
                for token, expected in pinned.items():
                    self.assertEqual(colors[token], expected, token)

    def test_no_windows_palette_keeps_a_retired_blue(self):
        for args in (("windows",), ("windows", "windows"), ("dark", "windows")):
            with self.subTest(args=args):
                self.assertFalse(RETIRED_BLUES & set(ui_theme.palette(*args).values()))

    def test_overlays_darken_light_and_lighten_dark(self):
        self.assertEqual(ui_theme.build_theme("windows", system="windows").overlay, "#000000")
        self.assertEqual(ui_theme.build_theme("dark", system="windows").overlay, "#FFFFFF")

    WINDOWS_11_FAMILIES = frozenset({
        "Arial", "Segoe UI", "Segoe UI Semibold",
        "Segoe UI Variable Text", "Segoe UI Variable Text Semibold",
        "Segoe UI Variable Display", "Segoe UI Variable Display Semib",
    })

    def test_windows_11_fonts_use_the_variable_optical_sizes(self):
        # Regression: "Segoe UI Variable" is not a Tk family and silently
        # rendered the whole GUI in Arial.
        theme = ui_theme.build_theme(
            "windows", system="windows", font_families=self.WINDOWS_11_FAMILIES)
        # Negative Tk sizes are pixels: the DS 14 px body is not a point size.
        self.assertEqual(theme.font(), ("Segoe UI Variable Text", -14))
        self.assertEqual(theme.font(12, "bold"), ("Segoe UI Variable Text Semibold", -18))
        self.assertEqual(theme.font(16), ("Segoe UI Variable Display", -28))
        self.assertEqual(theme.font(16, "bold"), ("Segoe UI Variable Display Semib", -28))
        self.assertEqual(theme.emoji_font(12), ("Segoe UI Emoji", -18))
        self.assertEqual(theme.mono_font(10, "bold"), ("Consolas", -14, "bold"))
        self.assertEqual(theme.symbol_family, "Segoe UI Symbol")
        with self.subTest("test_type_ramp_follows_the_ds_windows_roles"):
            self.assertEqual(theme.caption_font(), ("Segoe UI Variable Text", -12))
            self.assertEqual(theme.subtitle_font(), ("Segoe UI Variable Text Semibold", -18))
            self.assertEqual(theme.title_font(), ("Segoe UI Variable Display Semib", -28))
            # The brand label's 14 is a title too, in the display optical size.
            self.assertEqual(theme.font(14, "bold"), ("Segoe UI Variable Display Semib", -28))

    def test_pixel_roles_scale_with_the_display(self):
        theme = ui_theme.build_theme(
            "windows", system="windows", font_families=self.WINDOWS_11_FAMILIES, scale=1.5)
        self.assertEqual(theme.font(), ("Segoe UI Variable Text", -21))
        self.assertEqual(theme.caption_font(), ("Segoe UI Variable Text", -18))
        self.assertEqual(theme.title_font(), ("Segoe UI Variable Display Semib", -42))
        self.assertEqual((theme.control_height, theme.tree_row_height), (48, 48))

    def test_a_size_outside_the_ramp_fails_loudly(self):
        theme = ui_theme.build_theme("windows", system="windows")
        for size in (8, 11, 13):
            with self.subTest(size=size), self.assertRaises(ValueError):
                theme.font(size)

    def test_mono_prefers_cascadia_where_installed(self):
        for available, expected in (
            ({"Cascadia Mono", "Cascadia Code", "Consolas"}, "Cascadia Mono"),
            ({"Cascadia Code", "Consolas"}, "Cascadia Code"),
            ({"Consolas"}, "Consolas"),
            (None, "Consolas"),
        ):
            with self.subTest(available=available):
                theme = ui_theme.build_theme(
                    "windows", system="windows", font_families=available)
                self.assertEqual(theme.mono_family, expected)
        # The platform monospace stays elsewhere, whatever is installed.
        self.assertEqual(
            ui_theme.mono_family("darwin", {"Cascadia Mono"}), "Menlo")

    def test_every_windows_family_is_one_tk_can_resolve(self):
        for families in (self.WINDOWS_11_FAMILIES, None):
            faces = ui_theme.windows_font_families(families)
            for face in faces.values():
                self.assertNotEqual(face, "Segoe UI Variable")
                if families is not None:
                    self.assertIn(face, families)

    def test_windows_10_falls_back_to_the_static_segoe_faces(self):
        for families in ({"Arial", "Segoe UI", "Segoe UI Semibold"}, None):
            theme = ui_theme.build_theme("windows", system="windows", font_families=families)
            self.assertEqual(theme.font(), ("Segoe UI", -14))
            self.assertEqual(theme.font(12, "bold"), ("Segoe UI Semibold", -18))
            self.assertEqual(theme.font(16), ("Segoe UI", -28))

    def test_other_platforms_keep_bold_as_a_weight(self):
        # Linux keeps its platform point scale, like macOS (see DESIGN.md).
        theme = ui_theme.build_theme("windows", system="linux")
        self.assertEqual(theme.font(12, "bold"), ("TkDefaultFont", 12, "bold"))
        self.assertEqual(theme.font(16, "bold"), ("TkDefaultFont", 16, "bold"))

    def test_windows_ignores_a_system_default_size(self):
        # Windows is the reference scale; probing must not shift it.
        theme = ui_theme.build_theme(
            "windows", system="windows", default_size=13,
            font_families=self.WINDOWS_11_FAMILIES)
        self.assertEqual(theme.size_delta, 0)
        self.assertEqual(theme.font(9), ("Segoe UI Variable Text", -12))


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
        self.assertEqual(shared, {"accent", "accent_hover", "accent_active", "text_on_accent"})

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


class AppearanceDetectionTests(unittest.TestCase):

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

        for old_test, apps_use_light, expected in (
            ("test_windows_never_probes", True, "windows"),
            ("test_windows_follows_the_apps_theme_switch", False, "dark"),
            ("test_an_unreadable_windows_switch_keeps_the_light_palette", None, "windows"),
        ):
            with self.subTest(old_test), mock.patch.object(
                ui_theme, "_windows_apps_use_light_theme", return_value=apps_use_light
            ):
                self.assertEqual(ui_theme._probe_kind(Exploding(), "windows"), expected)


class ThemeCacheTests(unittest.TestCase):

    def setUp(self):
        ui_theme.reset()
        self.addCleanup(ui_theme.reset)

    def test_bind_replaces_the_cached_theme(self):
        first = ui_theme.bind(None, system="windows")
        self.assertIs(ui_theme.theme(), first)
        second = ui_theme.bind(None, system="darwin")
        self.assertIsNot(second, first)
        self.assertIs(ui_theme.theme(), second)

    def test_widgetless_bind_never_claims_dark(self):
        # With the System choice and no widget to probe, guessing dark and
        # being wrong is the unreadable case; light is the historical answer.
        for old_test, resolve, allowed in (
            ("test_widgetless_bind_never_claims_dark",
             lambda: ui_theme.bind(None, system="darwin"), ("light",)),
            ("test_theme_resolves_without_a_widget", ui_theme.theme, ("windows", "light")),
        ):
            with self.subTest(old_test):
                ui_theme.reset()
                ui_theme.set_preference("system")
                self.assertIn(resolve().kind, allowed)

    def test_the_default_appearance_is_dark_on_windows(self):
        # DS 2.7.1 Windows family: Dark by default, Light and System explicit.
        for host, expected in (("windows", "dark"), ("linux", "dark"), ("darwin", "system")):
            with self.subTest(host=host), \
                    mock.patch.object(ui_theme, "current_os", return_value=host):
                ui_theme.reset()
                self.assertEqual(ui_theme.preference(), expected)
        with mock.patch.object(ui_theme, "current_os", return_value="windows"):
            ui_theme.reset()
            self.assertTrue(ui_theme.theme().is_dark)
            self.assertTrue(ui_theme.bind(None, system="windows").is_dark)

    def test_macos_keeps_following_the_system_by_default(self):
        # Aqua draws its controls in the OS appearance whatever the app picks,
        # so a fixed Dark default would put light bezels on a dark window.
        self.assertEqual(ui_theme.default_preference("darwin"), "system")
        theme = ui_theme.build_theme("light", system="darwin", preference=None)
        self.assertEqual(theme.preference, "system")
        self.assertEqual(theme.surface, "systemWindowBackgroundColor")


class WidgetOptionTests(unittest.TestCase):

    def test_widget_helpers_are_inert_off_macos(self):
        # Win32's own defaults for these widgets are already correct; pinning
        # them would swap the user's selection color for the app's blue.
        for system in ("windows", "linux"):
            theme = ui_theme.build_theme("windows", system=system)
            self.assertEqual(theme.entry_colors(), {})
            self.assertEqual(theme.text_colors(), {})
            self.assertEqual(theme.listbox_colors(), {})

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
            ui_theme.build_theme("windows", system="linux").text_native, "#202630"
        )

    def test_manager_window_size_fits_each_platform(self):
        with self.subTest("test_windows_keeps_its_window_size"):
            theme = ui_theme.build_theme("windows", system="windows")
            self.assertEqual(theme.manager_window_size, ("1280x800", 1180, 760))
            self.assertFalse(theme.stacked_toolbar_status)
        with self.subTest("test_linux_minimum_leaves_room_for_x11_font_metrics"):
            theme = ui_theme.build_theme("windows", system="linux")
            _geometry, min_width, min_height = theme.manager_window_size
            self.assertEqual((1100, 780), (min_width, min_height))
        with self.subTest("test_macos_widens_the_window_for_its_native_buttons"):
            # Aqua's bezel has a minimum width, so the editor pane needs more room.
            theme = ui_theme.build_theme("dark", system="darwin")
            geometry, min_width, _ = theme.manager_window_size
            self.assertEqual(geometry, "1300x760")
            self.assertGreater(min_width, 820)
            self.assertTrue(theme.stacked_toolbar_status)
        # The default must not start below the minimum.
        for kind, system in (("windows", "windows"), ("windows", "linux"), ("dark", "darwin")):
            with self.subTest("default fits the minimum", system=system):
                geometry, _min_width, min_height = ui_theme.build_theme(
                    kind, system=system).manager_window_size
                self.assertGreaterEqual(int(geometry.split("x")[1]), min_height)

    def test_fluent_spacing_and_tree_density_are_stable(self):
        theme = ui_theme.build_theme("windows", system="windows")
        self.assertEqual(
            (theme.space_xs, theme.space_sm, theme.space_md,
             theme.space_lg, theme.space_xl),
            (4, 8, 12, 16, 24),
        )
        # DS 2.7.1 Windows Compact: 32 px controls and rows.
        self.assertEqual(theme.density, "compact")
        self.assertEqual((theme.control_height, theme.tree_row_height), (32, 32))
        self.assertEqual(ui_theme.DENSITY_METRICS, {
            "compact": (32, 32), "comfortable": (40, 44), "touch": (44, 48),
        })
        with self.subTest("macOS keeps its Aqua row height"):
            self.assertEqual(ui_theme.build_theme("dark", system="darwin").tree_row_height, 44)
        with self.subTest("an unknown density fails loudly"), self.assertRaises(ValueError):
            ui_theme.Theme("dark", "windows", "Segoe UI", None, None, None, 0, {},
                           density="cozy")

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

    def test_toolbar_frame_uses_the_editor_card_surface(self):
        for old_test, kind, system in (
            ("test_toolbar_frame_uses_the_editor_card_surface", "windows", "windows"),
            ("test_toolbar_frame_uses_the_editor_card_surface", "windows", "linux"),
            ("test_toolbar_frame_keeps_the_card_surface_on_macos", "dark", "darwin"),
        ):
            with self.subTest(old_test, system=system):
                theme = ui_theme.build_theme(kind, system=system)
                self.assertEqual(theme.toolbar_frame_colors(), {"bg": theme.card})

    def test_status_label_uses_the_body_face_and_muted_grey(self):
        for old_test, kind, system in (
            ("test_status_label_uses_the_body_face_and_muted_grey", "windows", "windows"),
            ("test_status_label_uses_the_body_face_and_muted_grey", "windows", "linux"),
            ("test_status_label_uses_the_body_face_and_muted_grey_on_macos", "dark", "darwin"),
        ):
            with self.subTest(old_test, system=system):
                options = ui_theme.build_theme(kind, system=system).status_label_options()
                theme = ui_theme.build_theme(kind, system=system)
                self.assertEqual(options["font"], theme.caption_font())
                self.assertEqual(options["fg"], theme.text_muted)


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
        # The old bare try/except left whatever theme was already active when
        # the preferred one did not exist.
        style = self.FakeStyle(("clam", "default"))
        self.assertEqual(ui_theme.apply_ttk_theme(style, "darwin"), "clam")
        self.assertEqual(style.used, ["clam"])

    def test_never_raises_when_ttk_misbehaves(self):
        class Broken:
            def theme_names(self):
                raise RuntimeError("no ttk")

        self.assertIsNone(ui_theme.apply_ttk_theme(Broken(), "windows"))


class GuiSourceTests(unittest.TestCase):
    """The GUI must go through the seam; a literal here is the bug returning."""

    SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    SOURCE = os.path.join(SOURCE_DIR, "sniptype.pyw")
    # Every module that builds or draws GUI; ui_theme alone owns literals.
    UI_MODULES = (
        "sniptype.pyw", "ui_widgets.py", "gui_support.py", "form_dialog.py",
        "form_editor_dialog.py", "group_dialog.py", "hotkey_dialog.py",
        "preview_dialog.py",
    )

    def _source(self, name="sniptype.pyw"):
        with open(os.path.join(self.SOURCE_DIR, name), encoding="utf-8") as handle:
            return handle.read()

    def test_no_hardcoded_colors_left_in_the_gui(self):
        import re
        for name in self.UI_MODULES:
            with self.subTest(name):
                self.assertEqual(re.findall(r'"#[0-9A-Fa-f]{3,8}"', self._source(name)), [])

    def test_no_windows_only_font_families_left_in_the_gui(self):
        import re
        for name in self.UI_MODULES:
            with self.subTest(name):
                leaked = re.findall(
                    r'"(Segoe[^"]*|Consolas|Cascadia[^"]*|Arial|Helvetica)"',
                    self._source(name))
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

    def test_no_text_below_the_caption_size(self):
        # 8 pt captions were hard to read; the type ramp starts at Caption.
        import re
        for name in ("sniptype.pyw", "form_dialog.py", "form_editor_dialog.py",
                     "group_dialog.py", "hotkey_dialog.py", "preview_dialog.py"):
            sizes = re.findall(r"font\((\d+)", self._source(name))
            small = [size for size in sizes if int(size) < ui_theme.CAPTION_FONT_SIZE]
            self.assertEqual(small, [], name)



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

    def test_palette_pairs_meet_their_wcag_floor(self):
        floors = (
            ("test_body_and_muted_text_are_readable_on_every_surface", "text",
             ("surface", "surface_alt", "card", "field", "control", "select_bg"), 7),
            ("test_body_and_muted_text_are_readable_on_every_surface", "text_muted",
             ("surface", "surface_alt", "card", "field", "select_bg"), 4.5),
            ("test_accent_buttons_keep_their_labels_readable", "text_on_accent",
             ("accent", "accent_hover", "accent_active"), 4.5),
            # Delete buttons carry the danger color as text, not as a fill, and
            # hover on the danger tint (the dark neutral hover is 4.0:1).
            ("test_destructive_labels_are_readable_on_a_neutral_button", "danger",
             ("control", "danger_bg", "control_active", "card", "surface"), 4.5),
            ("test_selected_rows_stay_readable", "select_fg", ("select_bg",), 4.5),
            ("test_written_states_are_readable_where_they_appear", "warning",
             ("surface", "card"), 4.5),
            ("test_written_states_are_readable_where_they_appear", "link",
             ("surface", "card"), 4.5),
            # WCAG 1.4.11: the field underline and the checkbox/switch outline
            # are what identify those controls.
            ("test_input_boundaries_meet_the_non_text_contrast_floor", "stroke_strong",
             ("field", "card"), 3),
            # Regression: neutral buttons once had a ~1.04:1 fill and no
            # outline, so Novo/Editar/Duplicar read as plain text. The 1px
            # field border is what separates them now.
            ("test_neutral_buttons_stand_out_from_what_they_sit_on", "field_border",
             ("surface", "card", "field"), 3),
            # The copper mark (nav pill, checked edge, field focus, selection).
            ("test_copper_marks_meet_the_non_text_contrast_floor", "accent_border",
             ("surface", "card", "field", "select_bg"), 3),
            ("test_the_focus_ring_stands_out_from_every_surface", "focus_ring",
             ("surface", "card", "field"), 3),
        )
        for name, colors in self._palettes().items():
            for old_test, foreground, backgrounds, floor in floors:
                for background in backgrounds:
                    with self.subTest(old_test, palette=name, background=background):
                        self.assertGreaterEqual(
                            _contrast(colors[foreground], colors[background]), floor)

    def test_the_macos_navigation_mark_meets_the_non_text_contrast_floor(self):
        # The bar beside the current page sits on the sidebar (surface_alt),
        # in the Aqua palettes and in the fixed choices alike.
        for kind in ("light", "dark"):
            for preference in ("system", kind):
                theme = ui_theme.build_theme(kind, system="darwin", preference=preference)
                with self.subTest(kind=kind, preference=preference):
                    self.assertGreaterEqual(
                        _contrast(theme.accent_border, theme.surface_alt), 3)

    def test_each_state_reads_on_its_own_tint(self):
        for name, colors in self._palettes().items():
            for state in ("danger", "warning", "success", "info"):
                with self.subTest(palette=name, state=state):
                    self.assertGreaterEqual(
                        _contrast(colors[state], colors[f"{state}_bg"]), 4.5)

    def test_the_dark_palette_defines_every_light_token(self):
        self.assertEqual(
            set(ui_theme.palette("dark", "windows")), set(ui_theme.palette("windows", "linux")))


class AppearancePreferenceTests(unittest.TestCase):

    def setUp(self):
        ui_theme.reset()
        self.addCleanup(ui_theme.reset)

    def test_unknown_values_fall_back_to_the_platform_default(self):
        for value in (None, "", "Dark", 1, "auto"):
            with self.subTest(value=value):
                self.assertEqual(ui_theme.normalize_preference(value, "windows"), "dark")
                self.assertEqual(ui_theme.normalize_preference(value, "linux"), "dark")
                self.assertEqual(ui_theme.normalize_preference(value, "darwin"), "system")
        self.assertEqual(ui_theme.set_preference("bogus"), ui_theme.default_preference())
        # Explicit choices stay respected.
        for value in ui_theme.APPEARANCE_CHOICES:
            for system in ("windows", "darwin"):
                self.assertEqual(ui_theme.normalize_preference(value, system), value)

    def test_labels_cover_every_choice(self):
        self.assertEqual(set(ui_theme.APPEARANCE_LABELS), set(ui_theme.APPEARANCE_CHOICES))
        self.assertEqual(set(ui_theme.APPEARANCE_STATUS), set(ui_theme.APPEARANCE_CHOICES))

    def test_a_fixed_choice_overrides_the_windows_switch(self):
        with mock.patch.object(ui_theme, "_windows_apps_use_light_theme", return_value=False), \
                mock.patch.object(ui_theme, "_probe_default_size", return_value=None), \
                mock.patch.object(ui_theme, "display_scale", return_value=1.0):
            ui_theme.set_preference("light")
            self.assertFalse(ui_theme.bind(object(), system="windows").is_dark)
        with mock.patch.object(ui_theme, "_windows_apps_use_light_theme", return_value=True), \
                mock.patch.object(ui_theme, "_probe_default_size", return_value=None), \
                mock.patch.object(ui_theme, "display_scale", return_value=1.0):
            ui_theme.set_preference("dark")
            self.assertTrue(ui_theme.bind(object(), system="windows").is_dark)
            with self.subTest("test_every_later_bind_keeps_the_choice"):
                # Dialogs re-bind against their own parent; they must not snap
                # back to the system appearance.
                self.assertTrue(ui_theme.bind(None, system="windows").is_dark)
                self.assertTrue(ui_theme.theme().is_dark)

    def test_system_choice_follows_the_windows_switch(self):
        ui_theme.set_preference("system")
        for apps_use_light, dark in ((False, True), (True, False)):
            with mock.patch.object(ui_theme, "_windows_apps_use_light_theme",
                                   return_value=apps_use_light), \
                    mock.patch.object(ui_theme, "_probe_default_size", return_value=None), \
                    mock.patch.object(ui_theme, "display_scale", return_value=1.0):
                theme = ui_theme.bind(object(), system="windows")
            self.assertEqual(theme.is_dark, dark)
            self.assertEqual(theme.preference, "system")

    def test_bind_scales_the_type_roles_to_the_widget(self):
        with mock.patch.object(ui_theme, "_probe_default_size", return_value=None), \
                mock.patch.object(ui_theme, "display_scale", return_value=2.0):
            theme = ui_theme.bind(object(), system="windows")
        self.assertEqual(theme.font()[1], -28)
        self.assertEqual(theme.tree_row_height, 64)

    def test_display_scale_reads_tk_scaling(self):
        widget = mock.Mock()
        widget.tk.call.return_value = 4 / 3
        self.assertAlmostEqual(ui_theme.display_scale(widget), 1.0)
        widget.tk.call.assert_called_once_with("tk", "scaling")

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

    def test_window_chrome_is_a_no_op_off_windows(self):
        mac = ui_theme.build_theme("light", system="darwin")
        self.assertFalse(ui_theme.apply_window_chrome(object(), mac))

if __name__ == "__main__":
    unittest.main()
