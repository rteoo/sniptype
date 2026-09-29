"""Numpad keys must feed trigger detection like the characters they type.

On Windows pynput translates a key through its scan code, and with NumLock on
the numpad digits share their scan codes with the navigation keys, so they
arrive as ``KeyCode(vk=0x60..0x69, char=None)`` and used to be dropped. The
numpad '/' shares scan 0x35 with another key once the extended flag is lost
(';' on ABNT2), and VK_DECIMAL arrives without a char. These tests drive the
real ``on_press`` with the key objects pynput produces for those keys.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import win_input
from app_module import sniptype as tx  # .pyw is not importable off Windows
from pynput.keyboard import KeyCode
from test_hotpath import make_app

VK_NUMPAD9 = 0x69


def numpad_digit(digit):
    return KeyCode.from_vk(win_input.VK_NUMPAD0 + digit)


# What pynput delivers for the numpad '/' on a pt-BR ABNT2 layout.
NUMPAD_DIVIDE = KeyCode(vk=win_input.VK_DIVIDE, char=";")
NUMPAD_DECIMAL = KeyCode.from_vk(win_input.VK_DECIMAL)


class NumpadTableTests(unittest.TestCase):
    def test_digits_and_divide_map_to_their_characters(self):
        for digit in range(10):
            self.assertEqual(str(digit), win_input.NUMPAD_CHARS[win_input.VK_NUMPAD0 + digit])
        self.assertEqual("/", win_input.NUMPAD_CHARS[win_input.VK_DIVIDE])

    def test_non_numpad_keys_keep_pynputs_char_without_user32_reads(self):
        cases = (
            ("non_numpad_keys", ((0x39, "9"), (0x41, "a"), (0x0D, None), (None, "x"))),
            # VK_MULTIPLY, VK_ADD, VK_SUBTRACT arrive as '*', '+', '-'.
            ("operators_pynput_already_translates_are_left_alone",
             ((0x6A, "*"), (0x6B, "+"), (0x6D, "-"))),
        )
        for label, keys in cases:
            with self.subTest(label), \
                    mock.patch.object(win_input, "ctrl_or_alt_held") as held, \
                    mock.patch.object(win_input, "layout_decimal_char") as decimal:
                for vk, char in keys:
                    self.assertEqual(char, win_input.typed_char(vk, char))
                held.assert_not_called()
                decimal.assert_not_called()

    def test_numpad_keys_override_pynputs_char(self):
        with mock.patch.object(win_input, "ctrl_or_alt_held", return_value=False), \
                mock.patch.object(win_input, "layout_decimal_char", return_value=","):
            self.assertEqual("9", win_input.typed_char(VK_NUMPAD9, None))
            self.assertEqual("/", win_input.typed_char(win_input.VK_DIVIDE, ";"))
            with self.subTest("decimal_uses_the_active_layout"):
                self.assertEqual(",", win_input.typed_char(win_input.VK_DECIMAL, None))

    def test_ctrl_or_alt_means_the_key_types_no_character(self):
        # Alt+numpad digits compose an Alt code; Ctrl+digit types nothing.
        # pynput's own char must not leak through either (';' for '/').
        with mock.patch.object(win_input, "ctrl_or_alt_held", return_value=True), \
                mock.patch.object(win_input, "layout_decimal_char", return_value=","):
            self.assertIsNone(win_input.typed_char(VK_NUMPAD9, None))
            self.assertIsNone(win_input.typed_char(win_input.VK_DIVIDE, ";"))
            self.assertIsNone(win_input.typed_char(win_input.VK_DECIMAL, None))


class LayoutDecimalTests(unittest.TestCase):
    """``layout_decimal_char`` with the user32 calls faked."""

    def _user32(self, mapped):
        user32 = mock.Mock()
        user32.GetForegroundWindow.return_value = 0x1234
        user32.GetWindowThreadProcessId.return_value = 77
        user32.GetKeyboardLayout.return_value = 0x04160416
        user32.MapVirtualKeyExW.return_value = mapped
        return user32

    def test_reads_the_foreground_threads_layout(self):
        for label, char in (
            ("reads_the_foreground_threads_layout", ","),
            ("us_layout_types_a_period", "."),
        ):
            with self.subTest(label):
                user32 = self._user32(ord(char))
                with mock.patch.object(win_input, "_USER32", user32, create=True):
                    self.assertEqual(char, win_input.layout_decimal_char())
                user32.GetWindowThreadProcessId.assert_called_once_with(0x1234, None)
                user32.GetKeyboardLayout.assert_called_once_with(77)
                user32.MapVirtualKeyExW.assert_called_once_with(
                    win_input.VK_DECIMAL, win_input.MAPVK_VK_TO_CHAR, 0x04160416
                )

    def test_unmapped_or_dead_decimal_types_nothing(self):
        for mapped in (0, 0x80000000 | ord(",")):
            with mock.patch.object(win_input, "_USER32", self._user32(mapped), create=True):
                self.assertIsNone(win_input.layout_decimal_char())

    @unittest.skipUnless(sys.platform == "win32", "real user32 reads are Windows-only")
    def test_real_user32_bindings_return_one_character(self):
        # Read-only calls: foreground window, its layout, a VK-to-char lookup.
        char = win_input.layout_decimal_char()
        self.assertIsInstance(char, str)
        self.assertEqual(1, len(char))
        self.assertIsInstance(win_input.ctrl_or_alt_held(), bool)


class OnPressNumpadTests(unittest.TestCase):
    """Drive the real ``on_press`` as the Windows listener would."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.app = make_app(
            self.tmp,
            {"x9": "nine", "x/": "slash", "x,5": "comma", "x.5": "dot"},
        )
        for patcher in (
            mock.patch.object(tx, "IS_WINDOWS", True),
            mock.patch.object(win_input, "ctrl_or_alt_held", return_value=False),
            mock.patch.object(win_input, "layout_decimal_char", return_value=","),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _dispatched(self):
        return [c.args[1] for c in self.app.task_runner.start.call_args_list]

    def test_numpad_digits_build_the_same_buffer_as_top_row_digits(self):
        self.app.on_press(KeyCode.from_char("a"))
        for digit in (1, 2, 3):
            self.app.on_press(numpad_digit(digit))
        numpad_buffer = self.app.typed_text

        self.app.typed_text = ""
        for char in "a123":
            self.app.on_press(KeyCode.from_char(char))
        self.assertEqual(self.app.typed_text, numpad_buffer)
        self.assertEqual("a123", numpad_buffer)

    def test_numpad_digit_fires_a_trigger_like_the_top_row_digit(self):
        self.app.on_press(KeyCode.from_char("x"))
        self.app.on_press(KeyCode.from_char("9"))
        top_row = self.app.task_runner.start.call_args

        self.app.task_runner.reset_mock()
        self.app.on_press(KeyCode.from_char("x"))
        self.app.on_press(KeyCode.from_vk(VK_NUMPAD9))
        self.assertEqual(top_row, self.app.task_runner.start.call_args)
        self.assertEqual(["x9"], self._dispatched())

    def test_numpad_divide_types_a_slash_not_the_shared_scan_code_char(self):
        self.app.on_press(KeyCode.from_char("x"))
        self.app.on_press(NUMPAD_DIVIDE)
        self.assertEqual(["x/"], self._dispatched())

    def test_numpad_decimal_follows_the_layout(self):
        for key in (KeyCode.from_char("x"), NUMPAD_DECIMAL, numpad_digit(5)):
            self.app.on_press(key)
        self.assertEqual(["x,5"], self._dispatched())

        self.app.task_runner.reset_mock()
        with mock.patch.object(win_input, "layout_decimal_char", return_value="."):
            for key in (KeyCode.from_char("x"), NUMPAD_DECIMAL, numpad_digit(5)):
                self.app.on_press(key)
        self.assertEqual(["x.5"], self._dispatched())

    def test_alt_code_digits_do_not_enter_the_buffer(self):
        self.app.on_press(KeyCode.from_char("x"))
        with mock.patch.object(win_input, "ctrl_or_alt_held", return_value=True):
            self.app.on_press(numpad_digit(9))
            self.app.on_press(NUMPAD_DIVIDE)
        self.assertEqual("x", self.app.typed_text)
        self.app.task_runner.start.assert_not_called()

    def test_other_platforms_ignore_the_windows_vk_table(self):
        # macOS key code 0x69 is F13 and arrives without a char; darwin and
        # xorg already deliver keypad digits as characters.
        with mock.patch.object(tx, "IS_WINDOWS", False):
            self.app.on_press(KeyCode.from_char("x"))
            self.app.on_press(KeyCode.from_vk(VK_NUMPAD9))
            self.assertEqual("x", self.app.typed_text)
            self.app.on_press(KeyCode.from_char("9"))
        self.assertEqual(["x9"], self._dispatched())


if __name__ == "__main__":
    unittest.main()
