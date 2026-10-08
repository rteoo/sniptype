"""An expansion result is pasted only into the context it was typed in.

Every match resolves on its own worker, so a slow result (network callable,
form) can finish after the user kept typing, switched windows, or typed a
second trigger. Pasting it then lands the text in the wrong place or out of
typed order; it must go to the clipboard with a notification instead. A fast
expansion survives ordinary subsequent typing, but a mouse click, a window
change, or a newer trigger cancels its automatic insertion.

Most workers are driven by calling the queued ``_run_expansion`` directly in
a chosen order; one event-barrier regression uses a real worker thread. No
test sends real keys or accesses the OS clipboard.
"""

import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runtime_support
from app_module import sniptype as tx  # .pyw is not importable off Windows
from pynput.keyboard import Key, KeyCode
from test_hotpath import FakeClipboard, make_app
from whatsapp_runtime_support import ACTION_COMPLETED


class _GuardFixture(unittest.TestCase):
    """A real app and real TextInserter over an in-memory clipboard."""

    def setUp(self):
        test_tmp = os.path.join(os.path.dirname(__file__), "tmp")
        os.makedirs(test_tmp, exist_ok=True)
        self.tmp = tempfile.mkdtemp(dir=test_tmp)
        self.addCleanup(shutil.rmtree, self.tmp)
        self.addCleanup(logging.shutdown)
        self.app = make_app(
            self.tmp,
            {"xfast": "SECOND", "xform": "Olá %%nome%%"},
            stub_inserter=False,
        )
        self.app.mouse_monitor = mock.Mock(generation=0)
        self.app.snippets["xfirst"] = "FIRST"
        # A slow-route callable, like the BCB and stock providers.
        self.app.snippets["xslow"] = lambda: "FIRST"
        self.app.slow_snippets = {"xslow"}
        self.app.refresh_runtime_indexes()
        inserter = self.app.text_inserter
        inserter.settle_delay = 0
        inserter.restore_delay = 0
        inserter.notify = mock.Mock()
        self.clipboard = FakeClipboard("ORIGINAL")
        self.pasted = []
        # Record what the paste chord would have pasted; nothing is injected.
        # True: the chord was accepted (False would mean Windows rejected it).
        inserter._send_paste_shortcut = (
            lambda: self.pasted.append(self.clipboard.value) or True
        )
        for patcher in (
            mock.patch.object(runtime_support, "Clipboard", self.clipboard),
            mock.patch.object(tx.time, "sleep"),
            mock.patch.object(
                tx.platform_support, "foreground_window_handle", return_value=100
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _type(self, text):
        for char in text:
            self.app.on_press(KeyCode.from_char(char))

    def _run_worker(self, index):
        """Run the ``index``-th queued expansion worker on this thread."""
        call = self.app.task_runner.start.call_args_list[index]
        kwargs = {
            key: value for key, value in call.kwargs.items()
            if key not in ("name", "daemon")
        }
        return call.args[0](*call.args[1:], **kwargs)

    def _assert_on_clipboard_with_notice(self, payload):
        self.assertEqual(payload, self.clipboard.value)
        self.app.text_inserter.notify.assert_called_once()
        self.assertEqual(
            "paste-stale",
            self.app.text_inserter.notify.call_args.kwargs.get("key"),
        )

    def _assert_stale_fallback(self, payload):
        self.assertEqual([], self.pasted)
        self._assert_on_clipboard_with_notice(payload)


class ExpansionTargetGuardTests(_GuardFixture):
    def test_the_app_inserter_is_wired_to_the_guard(self):
        self.assertEqual(
            self.app._expansion_target_is_current,
            self.app.text_inserter.still_current,
        )

    def test_unchanged_context_pastes_and_restores_the_clipboard(self):
        self._type("xfast")
        self._run_worker(0)

        self.assertEqual(["SECOND"], self.pasted)
        self.assertEqual("ORIGINAL", self.clipboard.value)
        self.app.text_inserter.notify.assert_not_called()

    def test_typing_during_resolution_goes_to_clipboard_not_the_editor(self):
        self._type("xslow")
        self._type("ab")  # the user keeps typing before the worker inserts
        self._run_worker(0)

        self._assert_stale_fallback("FIRST")

    def test_window_change_during_resolution_goes_to_clipboard(self):
        self._type("xslow")
        with mock.patch.object(
            tx.platform_support, "foreground_window_handle", return_value=200
        ):
            self._run_worker(0)

        self._assert_stale_fallback("FIRST")

    def test_unreadable_foreground_falls_back_to_the_keystroke_check(self):
        # macOS/Linux (and a failed Win32 read) have no window handle: the
        # input generation alone decides.
        with mock.patch.object(
            tx.platform_support, "foreground_window_handle", return_value=None
        ):
            self._type("xslow")
            self._type("ab")
            self._run_worker(0)

        self._assert_stale_fallback("FIRST")

    def test_fast_expansion_survives_the_next_keystroke(self):
        self._type("xfast")
        self._type("a")  # a fast typist continues before the paste
        self._run_worker(0)

        self.assertEqual(["SECOND"], self.pasted)
        self.app.text_inserter.notify.assert_not_called()

    def test_fast_expansion_still_refuses_another_window(self):
        self._type("xfast")
        with mock.patch.object(
            tx.platform_support, "foreground_window_handle", return_value=200
        ):
            self._run_worker(0)

        self._assert_stale_fallback("SECOND")

    def test_click_in_the_same_window_cancels_a_pending_fast_expansion(self):
        self._type("xfast")
        self.app.mouse_monitor.generation += 1
        self._run_worker(0)

        self._assert_stale_fallback("SECOND")

    def test_click_in_the_same_window_cancels_a_pending_slow_expansion(self):
        self._type("xslow")
        self.app.mouse_monitor.generation += 1
        self._run_worker(0)

        self._assert_stale_fallback("FIRST")

    def test_mouse_observer_failure_leaves_the_pending_result_for_manual_paste(self):
        self._type("xfast")
        monitor = tx.MouseActivityMonitor()
        monitor._error = RuntimeError("observer unavailable")
        self.app.mouse_monitor = monitor
        self._run_worker(0)

        self._assert_stale_fallback("SECOND")

    def test_window_change_during_erasure_cannot_retarget_the_worker(self):
        window = [100]
        with mock.patch.object(
            tx.platform_support, "foreground_window_handle", side_effect=lambda: window[0],
        ), mock.patch.object(
            self.app, "_erase_chars", side_effect=lambda _count: window.__setitem__(0, 200) or True,
        ):
            self._type("xfast")
            self._run_worker(0)

        self._assert_stale_fallback("SECOND")

    def test_overlapping_fast_results_never_paste_in_reverse_order(self):
        self._type("xfirst")
        self._type("xfast")
        self._run_worker(1)
        self._run_worker(0)

        self.assertEqual(["SECOND"], self.pasted)
        self._assert_on_clipboard_with_notice("FIRST")

    def test_newer_fast_trigger_cancels_older_result_even_if_it_finishes_first(self):
        self._type("xfirst")
        self._type("xfast")
        self._run_worker(0)
        self._run_worker(1)

        self.assertEqual(["SECOND"], self.pasted)
        self._assert_on_clipboard_with_notice("FIRST")

    def test_completed_fast_results_still_paste_in_order(self):
        self._type("xfirst")
        self._run_worker(0)
        self._type("xfast")
        self._run_worker(1)

        self.assertEqual(["FIRST", "SECOND"], self.pasted)
        self.app.text_inserter.notify.assert_not_called()

    def test_fast_worker_that_finishes_after_a_newer_thread_cannot_paste(self):
        entered = threading.Event()
        finish = threading.Event()

        def first_provider():
            entered.set()
            if not finish.wait(3):
                raise RuntimeError("test did not release the first worker")
            return "FIRST"

        # A callable on the fast route lets this test hold resolution without
        # changing the paste path. The OS clipboard and keyboard remain mocked.
        self.app.snippets["xfirst"] = first_provider
        self.app.refresh_runtime_indexes()
        self._type("xfirst")
        self.assertIs(False, self.app.task_runner.start.call_args.args[3])
        thread = threading.Thread(target=self._run_worker, args=(0,), daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(3), "first worker did not start")
            self._type("xfast")
            self._run_worker(1)
        finally:
            finish.set()
            thread.join(3)
        self.assertFalse(thread.is_alive(), "expansion worker did not exit")
        self.assertEqual(["SECOND"], self.pasted)
        self._assert_on_clipboard_with_notice("FIRST")

    def test_overlapping_slow_and_fast_never_insert_out_of_typed_order(self):
        self._type("xslow")
        self._type("xfast")

        # The second trigger finishes first, then the first one.
        self._run_worker(1)
        self._run_worker(0)

        self.assertEqual(["SECOND"], self.pasted)
        self._assert_on_clipboard_with_notice("FIRST")

    def test_overlap_in_typed_order_still_leaves_the_stale_first_on_clipboard(self):
        self._type("xslow")
        self._type("xfast")

        self._run_worker(0)
        self._run_worker(1)

        # FIRST was overtaken by the user's typing; only SECOND may land, and
        # SECOND's paste restores FIRST as the clipboard it found.
        self.assertEqual(["SECOND"], self.pasted)
        self.assertEqual("FIRST", self.clipboard.value)

    def test_stale_terminator_is_not_reemitted(self):
        self.app.terminator_mode = True
        self._type("xslow ")
        self._type("a")
        self.app.keyboard_controller.type.reset_mock()
        self._run_worker(0)

        self._assert_stale_fallback("FIRST")
        self.app.keyboard_controller.type.assert_not_called()

    def test_click_after_a_successful_paste_does_not_receive_its_terminator(self):
        self.app.terminator_mode = True
        self._type("xfast ")

        def paste_then_click():
            self.pasted.append(self.clipboard.value)
            self.app.mouse_monitor.generation += 1
            return True

        self.app.text_inserter._send_paste_shortcut = paste_then_click
        self._run_worker(0)

        self.assertEqual(["SECOND"], self.pasted)
        self.app.keyboard_controller.type.assert_not_called()

    def test_self_injected_events_do_not_mark_the_expansion_stale(self):
        # macOS and the paced Windows erase deliver our own synthesized
        # backspaces (and the re-emitted terminator) to the listener after
        # dispatch; pynput flags them as injected.
        self._type("xslow")
        for _ in range(len("xslow")):
            self.app.on_press(Key.backspace, True)
        self._run_worker(0)

        self.assertEqual(["FIRST"], self.pasted)

    def test_typed_fallback_never_types_into_a_stale_target(self):
        self._type("xslow")
        self._type("a")
        with mock.patch.object(self.clipboard, "set_content", return_value=False):
            self._run_worker(0)

        self.assertEqual([], self.pasted)
        self.app.keyboard_controller.type.assert_not_called()
        self.app.text_inserter.notify.assert_called_once()

    def test_action_only_expansion_is_unaffected_by_later_typing(self):
        self.app.snippets["xact"] = lambda: ACTION_COMPLETED
        self.app.refresh_runtime_indexes()
        self._type("xact")
        self._type("ab")
        self._run_worker(0)

        self.assertEqual([], self.pasted)
        self.assertEqual("ORIGINAL", self.clipboard.value)
        self.app.text_inserter.notify.assert_not_called()


class FormDialogTargetGuardTests(_GuardFixture):
    """Keystrokes typed into Sniptype's own form dialog are not staleness."""

    def setUp(self):
        super().setUp()
        # The Windows branch captures and restores the exact HWND; neither
        # call reaches Win32 here.
        for patcher in (
            mock.patch.object(tx.platform_support, "IS_WINDOWS", True),
            mock.patch.object(
                tx.platform_support, "capture_text_target", return_value=("hwnd", 100)
            ),
            mock.patch.object(
                tx.platform_support, "restore_text_target", return_value=True
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app.gui = mock.Mock()
        self.app.gui.call.side_effect = lambda callback: callback(object())

    def _fake_dialog(self, after_close=None):
        """Replace the Tk form with one that 'types' its answer into the hook."""
        def show(field_names, compiled_form=None):
            def build(_root):
                self.app.mouse_monitor.generation += 1
                self._type("Ada\t")
                self.app.on_press(Key.enter)
                return {name: "Ada" for name in field_names}

            result = self.app._run_modal_dialog(build, None, "campos")
            if after_close is not None:
                after_close()
            return result

        return mock.patch.object(self.app, "_show_form_dialog", side_effect=show)

    def test_dialog_keystrokes_do_not_mark_the_form_expansion_stale(self):
        self._type("xform")
        with self._fake_dialog():
            self._run_worker(0)

        self.assertEqual(["Olá Ada"], self.pasted)
        self.app.text_inserter.notify.assert_not_called()

    def test_typing_after_the_dialog_closes_still_marks_it_stale(self):
        self._type("xform")
        with self._fake_dialog(after_close=lambda: self._type("z")):
            self._run_worker(0)

        self._assert_stale_fallback("Olá Ada")

    def test_click_after_the_dialog_closes_still_marks_it_stale(self):
        def click():
            self.app.mouse_monitor.generation += 1

        self._type("xform")
        with self._fake_dialog(after_close=click):
            self._run_worker(0)

        self._assert_stale_fallback("Olá Ada")

    def test_dialog_rebaseline_cannot_revive_an_overtaken_worker(self):
        self._type("xform")
        with self._fake_dialog(after_close=lambda: self._type("xfast")):
            self._run_worker(0)
        self._run_worker(1)

        self.assertEqual(["SECOND"], self.pasted)
        self._assert_on_clipboard_with_notice("Olá Ada")

    def test_fast_provider_dialog_can_accept_clicks_without_enabling_key_checks(self):
        def show(_root):
            self.app.mouse_monitor.generation += 1
            self._type("Ada")
            return "FIRST"

        self.app.snippets["xdialog"] = lambda: self.app._run_modal_dialog(show, None, "test")
        self.app.refresh_runtime_indexes()
        self._type("xdialog")
        self._run_worker(0)

        self.assertEqual(["FIRST"], self.pasted)
        self.app.text_inserter.notify.assert_not_called()

    def test_focus_left_on_another_window_after_the_dialog_is_stale(self):
        self._type("xform")
        # Handle 100 was captured at dispatch; the insert sees 300.
        with self._fake_dialog(), mock.patch.object(
            tx.platform_support, "foreground_window_handle", return_value=300
        ):
            self._run_worker(0)

        self._assert_stale_fallback("Olá Ada")


if __name__ == "__main__":
    unittest.main()
