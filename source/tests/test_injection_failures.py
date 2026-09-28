"""Windows can reject injected input; a rejection must stop the expansion.

UIPI blocks ``SendInput`` from a non-elevated Sniptype into an elevated window,
and ``win_input`` reports it as ``False`` from ``erase()``/``paste()``. These
tests drive the real listener and ``TextInserter`` with fake injectors and a
fake clipboard; nothing here sends a real key or touches the system clipboard.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runtime_support
import win_input
from app_module import sniptype as tx  # .pyw is not importable off Windows
from test_hotpath import FakeClipboard, make_app


def fake_batch(erase=True, paste=True):
    batch = mock.Mock()
    batch.erase.return_value = erase
    batch.paste.return_value = paste
    return batch


def build_app(tmp, snippets):
    # The constructor would build a real BatchKeyboard on Windows; keep even
    # that inert object out of the test process.
    with mock.patch.object(tx.win_input, "BatchKeyboard", mock.Mock):
        return make_app(tmp, snippets)


def started_targets(app):
    return [call.args[0] for call in app.task_runner.start.call_args_list]


class RejectedEraseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = build_app(self.tmp, {"xhi": "hello"})
        self.app.erase_key_delay = 0.0
        # Keep a macOS runner's real Secure Keyboard Entry state out of it.
        self.app._secure_input_blocks_expansion = lambda: False
        self.batch = fake_batch(erase=False)
        self.app.batch_keyboard = self.batch

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _type(self, text):
        for char in text:
            self.app._handle_char(char)

    def test_rejected_erase_never_dispatches_the_expansion(self):
        self._type("xhi")

        self.batch.erase.assert_called_once_with(3)
        self.assertNotIn(self.app._run_expansion, started_targets(self.app))
        self.assertEqual("", self.app.typed_text)
        self.batch.paste.assert_not_called()

    def test_rejected_erase_notifies_off_the_listener_with_a_cooldown(self):
        self._type("xhi")

        self.app.task_runner.start.assert_called_once()
        call = self.app.task_runner.start.call_args
        self.assertEqual(self.app.notify_error, call.args[0])
        self.assertIn("administrador", call.args[1])
        self.assertEqual("injection-blocked", call.kwargs["key"])
        self.assertGreaterEqual(call.kwargs["cooldown_seconds"], 30)

    def test_rejected_erase_in_terminator_mode_does_not_reemit_the_terminator(self):
        self.app.terminator_mode = True
        self._type("xhi ")

        self.batch.erase.assert_called_once_with(4)
        self.assertNotIn(self.app._run_expansion, started_targets(self.app))
        self.app.keyboard_controller.type.assert_not_called()

    def test_accepted_erase_still_dispatches(self):
        self.batch.erase.return_value = True
        self._type("xhi")

        self.assertEqual([self.app._run_expansion], started_targets(self.app))


class RejectedPasteTests(unittest.TestCase):
    def _insert(self, snippet, paste_ok):
        clipboard = FakeClipboard(initial="orig")
        keyboard = mock.Mock()
        notify = mock.Mock()
        batch = fake_batch(paste=paste_ok)
        with mock.patch.object(runtime_support, "Clipboard", clipboard), \
                mock.patch.object(runtime_support.time, "sleep"):
            inserter = runtime_support.TextInserter(
                keyboard, logger=mock.Mock(), restore_delay=0.0,
                settle_delay=0.0, notify=notify, batch_keyboard=batch,
            )
            result = inserter.insert_text(snippet)
        return result, clipboard, keyboard, notify, batch

    def test_rejected_paste_reports_failure_and_leaves_payload(self):
        result, clipboard, keyboard, notify, batch = self._insert("bom dia", False)

        self.assertFalse(result)
        # The snapshot is not restored over the only copy of the expansion.
        self.assertEqual(["bom dia"], clipboard.writes)
        self.assertEqual("bom dia", clipboard.value)
        # Typing is blocked the same way; input is never blindly repeated.
        keyboard.type.assert_not_called()
        batch.paste.assert_called_once_with()
        notify.assert_called_once()
        self.assertIn("Ctrl+V", notify.call_args.args[0])
        self.assertEqual("paste-failed", notify.call_args.kwargs["key"])

    def test_rejected_multiline_paste_never_synthesizes_enter(self):
        snippet = "linha um\nlinha dois"
        result, clipboard, keyboard, notify, batch = self._insert(snippet, False)

        self.assertFalse(result)
        self.assertEqual([], keyboard.mock_calls)
        self.assertEqual([snippet], clipboard.writes)
        batch.paste.assert_called_once_with()
        notify.assert_called_once()

    def test_accepted_paste_still_restores_and_stays_quiet(self):
        result, clipboard, keyboard, notify, batch = self._insert("bom dia", True)

        self.assertTrue(result)
        self.assertEqual(["bom dia", "orig"], clipboard.writes)
        keyboard.type.assert_not_called()
        notify.assert_not_called()


class RejectedPasteWorkflowTests(unittest.TestCase):
    """A rejected paste is not a completed expansion."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = build_app(self.tmp, {"xhi": "hello"})
        self.app.workflow_state = mock.Mock()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _expand(self, paste_ok):
        # Real TextInserter, fake injector and clipboard.
        self.app.text_inserter = runtime_support.TextInserter(
            self.app.keyboard_controller, logger=mock.Mock(), restore_delay=0.0,
            settle_delay=0.0, notify=mock.Mock(),
            batch_keyboard=fake_batch(paste=paste_ok),
        )
        clipboard = FakeClipboard(initial="orig")
        with mock.patch.object(runtime_support, "Clipboard", clipboard), \
                mock.patch.object(tx, "Clipboard", clipboard), \
                mock.patch.object(runtime_support.time, "sleep"), \
                mock.patch.object(tx.time, "sleep"):
            self.app._run_expansion("xhi", " ", False)
        return clipboard

    def test_rejected_paste_records_no_success_and_reemits_nothing(self):
        clipboard = self._expand(paste_ok=False)

        self.app.workflow_state.record_success.assert_not_called()
        self.app.keyboard_controller.type.assert_not_called()
        self.assertEqual("hello", clipboard.value)
        self.app.text_inserter.notify.assert_called_once()

    def test_accepted_paste_records_success_and_reemits_the_terminator(self):
        # Control for the test above: the same expansion does record success.
        clipboard = self._expand(paste_ok=True)

        self.app.workflow_state.record_success.assert_called_once()
        self.app.keyboard_controller.type.assert_called_once_with(" ")
        self.assertEqual("orig", clipboard.value)
        self.app.text_inserter.notify.assert_not_called()


@unittest.skipUnless(win_input.IS_WINDOWS, "SendInput bindings are Windows-only")
class PartialInjectionTests(unittest.TestCase):
    """SendInput inserting fewer events than asked is a rejection, not success.

    ``_USER32`` is replaced wholesale, so no real SendInput call is made.
    """

    def test_partial_insert_reports_failure(self):
        user32 = mock.Mock()
        user32.MapVirtualKeyW.return_value = 0
        user32.SendInput.return_value = 3  # of the 6 events of a 3-char erase
        with mock.patch.object(win_input, "_USER32", user32):
            self.assertFalse(win_input.BatchKeyboard().erase(3))
            user32.SendInput.return_value = 6
            self.assertTrue(win_input.BatchKeyboard().erase(3))


if __name__ == "__main__":
    unittest.main()
