"""The trigger buffer must describe the text right before the caret.

Every test drives the real ``Sniptype.on_press`` with real pynput key objects;
erase and the expansion worker are mocks, and the foreground window is always
patched so no test reads or depends on the desktop it runs on.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import platform_support
from pynput.keyboard import Key, KeyCode
from test_hotpath import make_app


class BufferInvalidationTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = make_app(self.tmp, {"xhi": "hello"})
        self.app._erase_chars = mock.Mock()
        self.window = 0x1001
        # create=True lets the listener tests run (and fail on their
        # assertions) against a build that predates the helper.
        patcher = mock.patch.object(
            platform_support,
            "foreground_window_handle",
            side_effect=lambda: self.window,
            create=True,
        )
        self.foreground = patcher.start()
        self.addCleanup(patcher.stop)

    def press(self, *keys):
        for key in keys:
            if isinstance(key, str):
                key = KeyCode.from_char(key)
            self.app.on_press(key)

    def assert_expanded(self):
        self.app._erase_chars.assert_called_once_with(3)
        self.app.task_runner.start.assert_called_once()
        self.assertEqual("xhi", self.app.task_runner.start.call_args.args[1])

    def assert_not_expanded(self):
        self.app._erase_chars.assert_not_called()
        self.app.task_runner.start.assert_not_called()


class NavigationKeyTests(BufferInvalidationTestCase):
    RESET_KEYS = (
        Key.left,
        Key.right,
        Key.up,
        Key.down,
        Key.home,
        Key.end,
        Key.page_up,
        Key.page_down,
        Key.tab,
        Key.esc,
    )

    def test_baseline_trigger_still_expands(self):
        self.press("x", "h", "i")
        self.assert_expanded()

    def test_caret_moving_keys_do_not_join_fragments(self):
        for key in self.RESET_KEYS:
            with self.subTest(key=key):
                self.app._erase_chars.reset_mock()
                self.app.task_runner.reset_mock()
                self.app.typed_text = ""
                self.press("x", key, "h", "i")
                self.assert_not_expanded()
                self.assertEqual("hi", self.app.typed_text)

    def test_insert_and_menu_reset_where_the_platform_has_them(self):
        # Shift+Insert pastes and the context menu can paste/undo: both change
        # the text before the caret without a character reaching the buffer.
        keys = [getattr(Key, name) for name in ("insert", "menu") if hasattr(Key, name)]
        if not keys:
            self.skipTest("this pynput backend has neither Key.insert nor Key.menu")
        for key in keys:
            with self.subTest(key=key):
                self.app._erase_chars.reset_mock()
                self.app.task_runner.reset_mock()
                self.app.typed_text = ""
                self.press("x", key, "h", "i")
                self.assert_not_expanded()

    def test_trigger_typed_after_navigation_expands(self):
        self.press("q", Key.left, "x", "h", "i")
        self.assert_expanded()

    def test_delete_keeps_the_buffer(self):
        # Delete removes text after the caret; what precedes it is unchanged.
        self.press("x", "h", Key.delete, "i")
        self.assert_expanded()

    def test_modifiers_keep_the_buffer(self):
        self.press("x", Key.shift, "h", Key.shift_r, "i")
        self.assert_expanded()


class ForegroundWindowTests(BufferInvalidationTestCase):
    def test_window_switch_between_keystrokes_resets_the_buffer(self):
        self.press("x")
        self.window = 0x2002
        self.press("h", "i")
        self.assert_not_expanded()
        self.assertEqual("hi", self.app.typed_text)

    def test_switching_back_does_not_revive_the_old_fragment(self):
        self.press("x")
        self.window = 0x2002
        self.press("h")
        self.window = 0x1001
        self.press("i")
        self.assert_not_expanded()

    def test_same_window_expands(self):
        self.press("x", "h", "i")
        self.assert_expanded()

    def test_unknown_window_everywhere_keeps_legacy_behavior(self):
        # Off Windows (or when the query fails) the handle is None for every
        # key, so detection is exactly what it was before the check existed.
        self.window = None
        self.press("x", "h", "i")
        self.assert_expanded()

    def test_trigger_completed_in_new_window_expands(self):
        self.press("x", "h")
        self.window = 0x2002
        self.press("x", "h", "i")
        self.assert_expanded()


class ForegroundWindowHandleTests(unittest.TestCase):
    def test_off_windows_returns_none_without_native_calls(self):
        with mock.patch.object(platform_support, "IS_WINDOWS", False), \
                mock.patch.object(platform_support, "_win32_user32") as user32:
            self.assertIsNone(platform_support.foreground_window_handle())
        user32.assert_not_called()

    def test_windows_returns_the_foreground_hwnd(self):
        user32 = mock.Mock()
        user32.GetForegroundWindow.return_value = 0x3003
        with mock.patch.object(platform_support, "IS_WINDOWS", True), \
                mock.patch.object(platform_support, "_win32_user32", return_value=user32):
            self.assertEqual(0x3003, platform_support.foreground_window_handle())

    def test_windows_without_foreground_window_returns_none(self):
        user32 = mock.Mock()
        user32.GetForegroundWindow.return_value = 0
        with mock.patch.object(platform_support, "IS_WINDOWS", True), \
                mock.patch.object(platform_support, "_win32_user32", return_value=user32):
            self.assertIsNone(platform_support.foreground_window_handle())

    def test_windows_query_failure_returns_none(self):
        with mock.patch.object(platform_support, "IS_WINDOWS", True), \
                mock.patch.object(platform_support, "_win32_user32", side_effect=OSError("no user32")):
            self.assertIsNone(platform_support.foreground_window_handle())


if __name__ == "__main__":
    unittest.main()
