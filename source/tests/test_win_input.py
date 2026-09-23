import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import runtime_support
import win_input
from runtime_support import TextInserter


class EventShapeTests(unittest.TestCase):
    def test_backspaces_are_press_release_pairs(self):
        self.assertEqual(
            [(win_input.VK_BACK, True), (win_input.VK_BACK, False)] * 3,
            win_input.backspace_events(3),
        )

    def test_paste_chord_holds_ctrl_around_v_only(self):
        self.assertEqual(
            [
                (win_input.VK_CONTROL, True),
                (0x56, True),
                (0x56, False),
                (win_input.VK_CONTROL, False),
            ],
            win_input.paste_chord_events(0x56),
        )

    def test_batch_keyboard_sends_each_injection_as_one_batch(self):
        with mock.patch.object(win_input, "send_key_events", return_value=True) as send, \
                mock.patch.object(win_input, "paste_vk", return_value=0x56):
            keyboard = win_input.BatchKeyboard()
            self.assertTrue(keyboard.erase(4))
            self.assertTrue(keyboard.paste())

        self.assertEqual(2, send.call_count)
        self.assertEqual(win_input.backspace_events(4), send.call_args_list[0].args[0])
        self.assertEqual(win_input.paste_chord_events(0x56), send.call_args_list[1].args[0])


class ListenerFilterTests(unittest.TestCase):
    """Only our tagged events are hidden; everyone else's still reach on_press."""

    def test_own_event_is_hidden_from_the_listener(self):
        data = SimpleNamespace(dwExtraInfo=win_input.INJECTION_TAG)
        self.assertFalse(win_input.listener_event_filter(0x100, data))

    def test_physical_and_foreign_injected_events_pass(self):
        for extra in (None, 0, 1, win_input.INJECTION_TAG + 1):
            with self.subTest(extra=extra):
                data = SimpleNamespace(dwExtraInfo=extra)
                self.assertTrue(win_input.listener_event_filter(0x100, data))


@unittest.skipUnless(win_input.IS_WINDOWS, "SendInput structures are Windows-only")
class SendInputStructureTests(unittest.TestCase):
    def test_input_size_matches_the_win32_abi(self):
        import ctypes

        # SendInput rejects the whole batch when cbSize is wrong.
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(expected, ctypes.sizeof(win_input._INPUT))

    def test_events_are_tagged_and_submitted_in_one_call(self):
        captured = {}

        def fake_send(count, inputs, size):
            captured["count"] = count
            captured["events"] = [
                (inputs[i].value.ki.wVk, inputs[i].value.ki.dwFlags, inputs[i].value.ki.dwExtraInfo)
                for i in range(count)
            ]
            return count

        with mock.patch.object(win_input._USER32, "SendInput", side_effect=fake_send) as send:
            self.assertTrue(win_input.send_key_events(win_input.backspace_events(2)))

        send.assert_called_once()
        self.assertEqual(4, captured["count"])
        self.assertEqual(
            [
                (win_input.VK_BACK, 0, win_input.INJECTION_TAG),
                (win_input.VK_BACK, 2, win_input.INJECTION_TAG),
            ] * 2,
            captured["events"],
        )

    def test_partial_insert_reports_failure(self):
        with mock.patch.object(win_input._USER32, "SendInput", return_value=0):
            self.assertFalse(win_input.send_key_events(win_input.backspace_events(1)))


class PasteChordTests(unittest.TestCase):
    def test_batch_paste_bypasses_pynput(self):
        keyboard = mock.Mock()
        batch = mock.Mock()
        batch.paste.return_value = True
        inserter = TextInserter(keyboard, batch_keyboard=batch)

        inserter._send_paste_shortcut()

        batch.paste.assert_called_once_with()
        self.assertEqual([], keyboard.mock_calls)

    def test_blocked_batch_paste_is_logged(self):
        batch = mock.Mock()
        batch.paste.return_value = False
        logger = mock.Mock()
        inserter = TextInserter(mock.Mock(), logger=logger, batch_keyboard=batch)

        inserter._send_paste_shortcut()

        logger.warning.assert_called_once()


class BusyClipboardRestoreTests(unittest.TestCase):
    """A target still reading the clipboard must not strand the snippet on it."""

    def _insert(self, clipboard, snippet="olá", logger=None):
        inserter = TextInserter(mock.Mock(), logger=logger or mock.Mock(), restore_delay=0.0)
        with mock.patch.object(runtime_support, "Clipboard", clipboard), \
                mock.patch.object(runtime_support.time, "sleep"), \
                mock.patch.object(inserter, "_send_paste_shortcut"):
            self.assertTrue(inserter.insert_text(snippet))
        return inserter

    def test_restore_waits_out_a_busy_clipboard(self):
        clipboard = mock.Mock()
        clipboard.read_text.side_effect = [
            (True, "orig"),   # snapshot
            (False, None),    # target app still has it open
            (False, None),
            (True, "olá"),    # released: it has read the payload
        ]
        clipboard.set_content.return_value = True

        self._insert(clipboard)

        self.assertEqual(mock.call("orig"), clipboard.set_content.call_args_list[-1])
        self.assertEqual(2, clipboard.set_content.call_count)

    def test_clipboard_that_stays_busy_is_logged_not_overwritten(self):
        clipboard = mock.Mock()
        clipboard.read_text.side_effect = (
            [(True, "orig")] + [(False, None)] * TextInserter.RESTORE_READ_ATTEMPTS
        )
        clipboard.set_content.return_value = True
        logger = mock.Mock()

        self._insert(clipboard, logger=logger)

        self.assertEqual(1, clipboard.set_content.call_count)  # paste only
        logger.warning.assert_called_once()

    def test_busy_snapshot_is_logged(self):
        clipboard = mock.Mock()
        clipboard.read_text.return_value = (False, None)
        clipboard.set_content.return_value = True
        logger = mock.Mock()

        self._insert(clipboard, logger=logger)

        logger.warning.assert_called_once()
        self.assertIn("não pôde ser salvo", logger.warning.call_args.args[0])

    def test_failed_restore_write_is_logged(self):
        clipboard = mock.Mock()
        clipboard.read_text.side_effect = [(True, "orig"), (True, "olá")]
        clipboard.set_content.side_effect = [True, False]
        logger = mock.Mock()

        self._insert(clipboard, logger=logger)

        logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
