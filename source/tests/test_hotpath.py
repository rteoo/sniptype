import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clipboard_support
import runtime_support
from app_module import sniptype as tx  # .pyw is not importable off Windows
from pynput.keyboard import Key, KeyCode


def make_app(base_dir, snippets, stub_inserter=True):
    """Construct a Sniptype with keyboard/task side effects mocked out.

    ``stub_inserter=False`` keeps the real ``TextInserter`` so its wiring (the
    paste delays) can be inspected; it is never driven in that state.
    """
    with open(os.path.join(base_dir, "snippets.json"), "w", encoding="utf-8") as handle:
        json.dump(snippets, handle)
    previous_home = os.environ.get("SNIPTYPE_HOME")
    os.environ["SNIPTYPE_HOME"] = base_dir
    try:
        with mock.patch.object(tx, "get_runtime_base_dir", return_value=base_dir), \
                mock.patch.object(tx, "get_runtime_resource_dir", return_value=base_dir):
            app = tx.Sniptype()
    finally:
        if previous_home is None:
            os.environ.pop("SNIPTYPE_HOME", None)
        else:
            os.environ["SNIPTYPE_HOME"] = previous_home
    app.keyboard_controller = mock.Mock()
    app.task_runner = mock.Mock()
    if stub_inserter:
        app.text_inserter = mock.Mock()
    return app


class ImmediateModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xhi": "hello"})

    def _type(self, text):
        for char in text:
            self.app._handle_char(char)

    def test_direct_trigger_dispatches_to_worker(self):
        self._type("xhi")
        self.app.task_runner.start.assert_called_once()
        args = self.app.task_runner.start.call_args
        self.assertEqual(args.args[0], self.app._run_expansion)
        self.assertEqual(args.args[1], "xhi")
        self.assertEqual(args.args[2], "")  # no terminator appended
        self.assertEqual(self.app.typed_text, "")

    def test_no_dispatch_without_match(self):
        self._type("zzz")
        self.app.task_runner.start.assert_not_called()


class TerminatorModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xhi": "hello"})
        self.app.terminator_mode = True

    def _type(self, text):
        for char in text:
            self.app._handle_char(char)

    def test_no_expansion_until_terminator(self):
        self._type("xhi")
        self.app.task_runner.start.assert_not_called()

    def test_expands_on_terminator_and_reemits_it(self):
        self._type("xhi ")
        self.app.task_runner.start.assert_called_once()
        args = self.app.task_runner.start.call_args
        self.assertEqual(args.args[1], "xhi")
        self.assertEqual(args.args[2], " ")  # terminator re-typed after expansion


class ListenerResilienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xhi": "hello"})

    def test_raising_callable_does_not_propagate(self):
        def boom():
            raise RuntimeError("callable exploded")

        self.app.snippets["xboom"] = boom
        self.app.refresh_runtime_indexes()
        # Must not raise: the worker guard swallows and logs it.
        self.app._run_expansion("xboom")

    def test_buffer_sized_for_long_composed_dynamic_trigger(self):
        long_item = "a_very_long_mapping_item_name"
        self.app.snippets["_codes"] = {"__prefix__": "cc", "" + long_item: "value"}
        self.app.refresh_runtime_indexes()
        composed_len = len("cc") + len(long_item)
        self.assertGreaterEqual(self.app.max_trigger_length, composed_len + tx.TRIGGER_BUFFER_MARGIN)


class TerminatorReemitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xhi": "hello"})

    def test_terminator_not_reemitted_when_nothing_inserted(self):
        with mock.patch.object(self.app, "expand_snippet", return_value=False):
            self.app._run_expansion("xhi", append_text=" ")
        self.app.keyboard_controller.type.assert_not_called()

    def test_unavailable_clipboard_variable_inserts_nothing_and_notifies(self):
        self.app.snippets["xclip"] = "before %%clipboard-paste%% after"
        self.app.refresh_runtime_indexes()
        self.app.notify_error = mock.Mock()

        with mock.patch.object(tx.Clipboard, "get_text", return_value=None):
            self.app._run_expansion("xclip")

        self.app.text_inserter.insert_text.assert_not_called()
        self.app.notify_error.assert_called_once()
        self.assertIn("transferência", self.app.notify_error.call_args.args[0])

    def test_terminator_reemitted_when_inserted(self):
        with mock.patch.object(self.app, "expand_snippet", return_value=True):
            self.app._run_expansion("xhi", append_text=" ")
        self.app.keyboard_controller.type.assert_called_once_with(" ")

    def test_cancelled_form_dialog_inserts_nothing(self):
        """A cancelled form dialog must leave no text and no terminator."""
        self.app.snippets["xform"] = "Olá %%nome%%"
        self.app.refresh_runtime_indexes()
        with mock.patch.object(self.app, "_show_form_dialog", return_value=None) as dialog:
            self.app._run_expansion("xform", append_text=" ")
        dialog.assert_called_once_with(["nome"])
        self.app.text_inserter.insert_text.assert_not_called()
        self.app.keyboard_controller.type.assert_not_called()


class ModalDialogFocusTests(unittest.TestCase):
    """A dialog-backed expansion must return focus before it sends Cmd+V."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.app = make_app(self.tmp, {"xhi": "hello"})
        root = object()
        self.app.gui = mock.Mock()
        self.app.gui.call.side_effect = lambda callback: callback(root)

    def test_focus_is_restored_after_the_dialog_returns(self):
        events = []
        target = object()

        def build(root):
            events.append(("build", root))
            return "PETR4"

        with mock.patch.object(
            tx.platform_support,
            "capture_frontmost_application",
            side_effect=lambda: events.append(("capture", None)) or target,
        ), mock.patch.object(
            tx.platform_support,
            "restore_application_when_ready",
            side_effect=lambda app, on_active, _on_failed: (
                events.append(("restore", app)),
                on_active(),
                mock.Mock(),
            )[-1],
        ):
            result = self.app._run_modal_dialog(build, None, "ticker")

        self.assertEqual("PETR4", result)
        self.assertEqual(
            [("capture", None), ("build", mock.ANY), ("restore", target)],
            events,
        )

    def test_focus_is_restored_when_the_dialog_raises(self):
        target = object()
        with mock.patch.object(
            tx.platform_support,
            "capture_frontmost_application",
            return_value=target,
        ), mock.patch.object(
            tx.platform_support,
            "restore_application_when_ready",
            side_effect=lambda _app, on_active, _on_failed: (
                on_active(),
                mock.Mock(),
            )[-1],
        ) as restore:
            with self.assertRaisesRegex(RuntimeError, "dialog failed"):
                self.app._run_modal_dialog(
                    lambda _root: (_ for _ in ()).throw(RuntimeError("dialog failed")),
                    None,
                    "ticker",
                )
        self.assertIs(target, restore.call_args.args[0])

    def test_restore_failure_prevents_the_dialog_result_from_returning(self):
        with mock.patch.object(
            tx.platform_support,
            "capture_frontmost_application",
            return_value=object(),
        ), mock.patch.object(
            tx.platform_support,
            "restore_application_when_ready",
            side_effect=lambda _app, _on_active, on_failed: (
                on_failed("focus restore failed"),
                mock.Mock(),
            )[-1],
        ):
            with self.assertRaisesRegex(RuntimeError, "focus restore failed"):
                self.app._run_modal_dialog(
                    lambda _root: "PETR4",
                    None,
                    "ticker",
                )


class ClipboardSerializationTests(unittest.TestCase):
    def test_concurrent_pastes_do_not_interleave(self):
        events = []

        def fake_get_text():
            return "orig"

        def fake_set_content(value):
            events.append(("set", value))
            time.sleep(0.02)
            events.append(("done", value))
            return True

        with mock.patch.object(runtime_support.Clipboard, "get_text", fake_get_text), \
                mock.patch.object(runtime_support.Clipboard, "set_content", fake_set_content):
            inserter = runtime_support.TextInserter(mock.Mock(), restore_delay=0.0)
            threads = [
                threading.Thread(target=inserter.insert_text, args=(f"payload{i}",))
                for i in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        # Each paste's set/done pair must complete before the next paste's set,
        # proving the clipboard critical section is serialized.
        self.assertEqual(len(events), 4)
        for i in range(0, len(events), 2):
            self.assertEqual(events[i][0], "set")
            self.assertEqual(events[i + 1][0], "done")
            self.assertEqual(events[i][1], events[i + 1][1])


class FakeClipboard:
    """In-memory clipboard that mirrors the Windows backend's CRLF storage."""

    def __init__(self, initial=None):
        self.value = initial
        self.writes = []

    def get_text(self):
        return self.value

    def set_content(self, value):
        text = runtime_support.extract_plain_text(value)
        self.writes.append(text)
        self.value = clipboard_support.normalize_clipboard_newlines(text)
        return True


class TypedFallbackSafetyTests(unittest.TestCase):
    """A failed paste must never inject Enter keys."""

    def test_multiline_snippet_is_never_typed(self):
        # pynput types "\n" as a real Enter: in a terminal that executes the
        # line, in a chat app it sends the message. The user's xcattle snippet
        # ("cd ~/Projects/...\nuv run ...") would run a command mid-insert.
        clipboard = FakeClipboard(initial="orig")
        keyboard = mock.Mock()
        notify = mock.Mock()
        snippet = "cd ~/Projects/cattle-auction/\nuv run python main.py"

        with mock.patch.object(runtime_support, "Clipboard", clipboard):
            inserter = runtime_support.TextInserter(keyboard, notify=notify)
            with mock.patch.object(inserter, "_paste_value", return_value=False):
                self.assertFalse(inserter.insert_text(snippet))

        keyboard.type.assert_not_called()
        # Payload left where the user can retrieve it with a manual Ctrl+V.
        self.assertEqual(clipboard.writes[-1], snippet)
        notify.assert_called_once()
        self.assertIn("Ctrl+V", notify.call_args.args[0])

    def test_single_line_snippet_still_falls_back_to_typing(self):
        clipboard = FakeClipboard(initial="orig")
        keyboard = mock.Mock()

        with mock.patch.object(runtime_support, "Clipboard", clipboard):
            inserter = runtime_support.TextInserter(keyboard)
            with mock.patch.object(inserter, "_paste_value", return_value=False):
                self.assertTrue(inserter.insert_text("bom dia"))

        keyboard.type.assert_called_once_with("bom dia")


class ClipboardCoWriterTests(unittest.TestCase):
    def _insert(self, clipboard, snippet):
        logger = mock.Mock()
        with mock.patch.object(runtime_support, "Clipboard", clipboard):
            inserter = runtime_support.TextInserter(
                mock.Mock(), logger=logger, restore_delay=0.0
            )
            with mock.patch.object(inserter, "_send_paste_shortcut"):
                inserter.insert_text(snippet)
        return logger

    def test_third_party_overwrite_is_logged(self):
        """The evidence that distinguishes a co-writer from a slow target."""
        clipboard = FakeClipboard(initial="orig")

        def hostile_set(value):
            # A sync agent wins the clipboard right after our write.
            clipboard.writes.append(runtime_support.extract_plain_text(value))
            clipboard.value = "texto de outra maquina"
            return True

        clipboard.set_content = hostile_set
        logger = self._insert(clipboard, "bom dia")

        warnings = " ".join(str(call.args[0]) for call in logger.warning.call_args_list)
        self.assertIn("sobrescrita por outro programa", warnings)

    def test_normal_paste_logs_no_warning(self):
        logger = self._insert(FakeClipboard(initial="orig"), "bom dia")
        logger.warning.assert_not_called()

    def test_single_line_restores_previous_clipboard(self):
        clipboard = FakeClipboard(initial="orig")
        self._insert(clipboard, "bom dia")
        self.assertEqual(clipboard.value, "orig")

    def test_multiline_does_not_restore(self):
        # Deliberate: multi-line has never restored (the old CRLF comparison
        # skipped it), and enabling it now would expose exactly the snippets
        # under investigation to the restore race.
        clipboard = FakeClipboard(initial="orig")
        self._insert(clipboard, "linha um\nlinha dois")
        self.assertEqual(clipboard.value, "linha um\r\nlinha dois")


class SlowRefRoutingTests(unittest.TestCase):
    """A snippet referencing a slow dynamic trigger must take the async path."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "dynamic_snippets.json"), "w", encoding="utf-8") as handle:
            json.dump({"xdolar": {"provider": "bcb", "method": "dolar",
                                  "category": "economy", "slow": True}}, handle)
        self.app = make_app(self.tmp, {
            "xreport": "Dólar: %%xdolar%%",
            "xplain": "texto simples",
        })

    def test_snippet_referencing_slow_trigger_uses_slow_path(self):
        with mock.patch.object(self.app, "run_slow_snippet", return_value=True) as slow, \
                mock.patch.object(self.app, "expand_snippet", return_value=True) as fast:
            self.app._run_expansion("xreport")
        slow.assert_called_once_with("xreport")
        fast.assert_not_called()

    def test_plain_snippet_still_uses_fast_path(self):
        with mock.patch.object(self.app, "run_slow_snippet", return_value=True) as slow, \
                mock.patch.object(self.app, "expand_snippet", return_value=True) as fast:
            self.app._run_expansion("xplain")
        fast.assert_called_once_with("xplain")
        slow.assert_not_called()


class OnPressSpecialKeyTests(unittest.TestCase):
    """on_press feeds the detection buffer; Enter must reset it and Backspace
    must pop it so the buffer tracks what the user actually typed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xhi": "hello"})

    def _press(self, text):
        for char in text:
            self.app.on_press(KeyCode.from_char(char))

    def test_char_keys_accumulate_in_the_buffer(self):
        self._press("ab")
        self.assertEqual("ab", self.app.typed_text)

    def test_enter_resets_the_buffer(self):
        # KNOWN DEFECT — kept as a failing regression marker (no source fix).
        # on_press (sniptype.pyw:1304) guards with ``hasattr(key, 'char')``,
        # which is False for Key.enter, so the try body short-circuits WITHOUT
        # touching key.char, no AttributeError is raised, and the
        # ``except AttributeError`` block that clears the buffer is dead code.
        # The code's own comment says "Enter always just resets the buffer".
        self._press("ab")
        self.app.on_press(Key.enter)
        self.assertEqual("", self.app.typed_text)

    def test_backspace_pops_the_last_buffered_char(self):
        # KNOWN DEFECT — same root cause as Enter. Backspace never pops the
        # buffer, so detection diverges from the on-screen text after a typo
        # correction (stale chars accumulate → missed or phantom matches).
        self._press("abx")
        self.app.on_press(Key.backspace)
        self.assertEqual("ab", self.app.typed_text)

    def test_unknown_special_key_neither_crashes_nor_changes_buffer(self):
        self._press("ab")
        self.app.on_press(Key.shift)
        self.assertEqual("ab", self.app.typed_text)

    def test_escape_with_voice_off_does_not_dispatch_or_clear_buffer(self):
        self._press("ab")
        self.app.task_runner.reset_mock()
        self.app.on_press(Key.esc)
        self.assertEqual("ab", self.app.typed_text)
        self.app.task_runner.start.assert_not_called()

    def test_escape_does_not_cancel_voice_on_the_expansion_listener(self):
        self._press("ab")
        voice = mock.Mock()
        voice.is_enabled.return_value = True
        self.app.voice = voice
        self.app.task_runner.reset_mock()
        self.app.on_press(Key.esc)
        voice.cancel.assert_not_called()
        self.app.task_runner.start.assert_not_called()
        self.assertEqual("ab", self.app.typed_text)


class VoiceIsolationTests(unittest.TestCase):
    """Voice must stay off the expansion hot path unless the user opts in."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _type(self, app, text):
        for char in text:
            app._handle_char(char)

    def test_voice_stays_disabled_by_default(self):
        app = make_app(self.tmp, {"xhi": "hello"})
        self.assertFalse(bool(app.voice is not None and app.voice.is_enabled()))

    def test_construction_failure_does_not_block_expansion(self):
        with mock.patch.object(tx, "VoiceController", side_effect=RuntimeError("boom")):
            app = make_app(self.tmp, {"xhi": "hello"})
        self.assertIsNone(app.voice)
        self._type(app, "xhi")
        app.task_runner.start.assert_called_once()
        self.assertEqual(app.task_runner.start.call_args.args[1], "xhi")

    def test_escape_with_no_controller_leaves_buffer(self):
        with mock.patch.object(tx, "VoiceController", side_effect=RuntimeError("boom")):
            app = make_app(self.tmp, {"xhi": "hello"})
        for char in "ab":
            app.on_press(KeyCode.from_char(char))
        app.task_runner.reset_mock()
        app.on_press(Key.esc)
        self.assertEqual("ab", app.typed_text)
        app.task_runner.start.assert_not_called()

    def test_form_hooks_are_safe_when_voice_is_missing(self):
        with mock.patch.object(tx, "VoiceController", side_effect=RuntimeError("boom")):
            app = make_app(self.tmp, {"xform": "Olá %%nome%%"})
        self.assertIsNone(app.voice)
        app._register_voice_form_target(lambda text: None)
        app._unregister_voice_form_target()

    def test_form_apply_does_not_touch_tk_when_submit_fails(self):
        app = make_app(self.tmp, {"xform": "Olá %%nome%%"})
        entry = mock.Mock()
        with mock.patch.object(app.gui, "submit", side_effect=RuntimeError("no pump")):
            app._apply_voice_form({"nome": entry}, "João")
        entry.delete.assert_not_called()
        entry.insert.assert_not_called()
        entry.winfo_exists.assert_not_called()

    def test_transient_voice_status_never_rebuilds_the_tray_menu(self):
        app = make_app(self.tmp, {"xhi": "hello"})
        app.voice = mock.Mock()
        app.voice.status_snapshot.return_value = {
            "state": "transcribing",
            "mode": "dictation",
            "partial": "",
        }
        app.gui.submit = mock.Mock()
        app.refresh_tray_menu = mock.Mock()
        app._voice_status_changed()
        app.gui.submit.assert_called_once()
        app.refresh_tray_menu.assert_not_called()

    def test_idle_voice_status_still_refreshes_the_tray_menu(self):
        app = make_app(self.tmp, {"xhi": "hello"})
        app.voice = mock.Mock()
        app.voice.status_snapshot.return_value = {
            "state": "idle",
            "mode": None,
            "partial": "",
        }
        app.gui.submit = mock.Mock()
        app.refresh_tray_menu = mock.Mock()
        app._voice_status_changed()
        app.refresh_tray_menu.assert_called_once_with()

    def test_gui_thread_status_path_refreshes_manager_tab(self):
        app = make_app(self.tmp, {"xhi": "hello"})
        app.voice = mock.Mock()
        app.voice.status_snapshot.return_value = {
            "state": "recording",
            "mode": "dictation",
            "partial": "",
        }
        app.voice_status_indicator = mock.Mock()
        refresher = mock.Mock()
        app._manager_voice_refresher = refresher
        submitted = []
        app.gui.submit = submitted.append
        app.refresh_tray_menu = mock.Mock()

        app._voice_status_changed()

        self.assertEqual(len(submitted), 1)
        app.refresh_tray_menu.assert_not_called()
        submitted[0](mock.Mock())
        refresher.assert_called_once_with()
        app.voice_status_indicator.update.assert_called_once_with(
            "recording", "dictation"
        )

    def test_cancelled_enable_restores_manager_checked_state(self):
        app = make_app(self.tmp, {"xhi": "hello"})
        app.voice = mock.Mock()
        app.voice.is_enabled.return_value = False
        app.voice.model_installed.return_value = False
        app.voice.settings.profile = "balanced"
        refresher = mock.Mock()
        app._manager_voice_refresher = refresher
        entry = {
            "id": "parakeet",
            "size_bytes": 1000,
            "purpose": "test",
            "license_id": "MIT",
            "attribution": "x",
        }

        with mock.patch("voice_catalog.catalog_entry", return_value=entry), \
                mock.patch("voice_catalog.format_size", return_value="1 KB"), \
                mock.patch.object(tx.messagebox, "askyesno", return_value=False):
            app._confirm_and_enable_voice()

        app.voice.enable.assert_not_called()
        refresher.assert_called_once_with()

    def test_denied_microphone_restores_manager_checked_state(self):
        app = make_app(self.tmp, {"xhi": "hello"})
        app.voice = mock.Mock()
        app.notify_error = mock.Mock()
        refresher = mock.Mock()
        app._manager_voice_refresher = refresher

        with mock.patch.object(
            tx.macos_permissions,
            "check_microphone",
            return_value=tx.macos_permissions.DENIED,
        ), mock.patch.object(tx.macos_permissions, "open_settings_pane"):
            app._confirm_and_enable_voice()

        app.voice.enable.assert_not_called()
        refresher.assert_called_once_with()

    def test_missing_voice_leaves_manager_refresher_unset(self):
        with mock.patch.object(tx, "VoiceController", side_effect=RuntimeError("boom")):
            app = make_app(self.tmp, {"xhi": "hello"})
        self.assertIsNone(app.voice)
        self.assertIsNone(app._manager_voice_refresher)
        app._voice_status_changed()

    def test_stale_manager_voice_callback_after_close_is_noop(self):
        app = make_app(self.tmp, {"xhi": "hello"})
        app.voice_status_indicator = mock.Mock()
        app._manager_voice_refresher = None
        app._render_voice_status(
            mock.Mock(), {"state": "idle", "mode": None, "partial": ""}
        )
        app.voice_status_indicator.update.assert_called_once_with("idle", None)

    def test_destroyed_manager_voice_widgets_do_not_raise(self):
        app = make_app(self.tmp, {"xhi": "hello"})
        app.voice_status_indicator = mock.Mock()
        app._manager_voice_refresher = mock.Mock(
            side_effect=RuntimeError("widget destroyed")
        )
        app._render_voice_status(
            mock.Mock(), {"state": "loading", "mode": None, "partial": ""}
        )
        app.voice_status_indicator.update.assert_called_once_with("loading", None)

    def test_disable_runs_on_a_worker_not_the_caller(self):
        app = make_app(self.tmp, {"xhi": "hello"})
        app.voice = mock.Mock()
        app.voice.is_enabled.return_value = True
        app.task_runner = mock.Mock()
        app.refresh_tray_menu = mock.Mock()

        app.toggle_voice()

        app.voice.disable.assert_not_called()
        app.task_runner.start.assert_called_once()
        self.assertEqual(
            app.task_runner.start.call_args.kwargs.get("name"), "voice-disable"
        )
        worker = app.task_runner.start.call_args.args[0]
        worker()
        app.voice.disable.assert_called_once_with()
        app.refresh_tray_menu.assert_called_once_with()


class BufferMarginDispatchTests(unittest.TestCase):
    """The typed-text buffer must be sized so a trigger longer than the default,
    and a composed dynamic trigger, are never truncated out before matching."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _make(self, snippets):
        app = make_app(self.tmp, snippets)
        app._erase_chars = mock.Mock()  # avoid the real per-char erase sleeps
        return app

    def _type(self, app, text):
        for char in text:
            app._handle_char(char)

    def test_long_composed_dynamic_trigger_dispatches_in_full(self):
        long_name = "verylongidentifiername"
        app = self._make({"_custom_codes": {"__prefix__": "cc", long_name: "VALUE"}})
        composed = "cc" + long_name
        self._type(app, "noise" + composed)
        app.task_runner.start.assert_called_once()
        args = app.task_runner.start.call_args
        self.assertEqual(app._run_expansion, args.args[0])
        self.assertEqual(composed, args.args[1])
        app._erase_chars.assert_called_once_with(len(composed))

    def test_direct_trigger_longer_than_default_buffer_still_matches(self):
        long_trigger = "x" + "a" * 40  # 41 chars, exceeds the 20-char fallback
        app = self._make({long_trigger: "big"})
        self._type(app, "prefixpad" + long_trigger)
        app.task_runner.start.assert_called_once()
        self.assertEqual(long_trigger, app.task_runner.start.call_args.args[1])
        app._erase_chars.assert_called_once_with(len(long_trigger))


class TerminatorBufferMarginTests(unittest.TestCase):
    """In terminator mode the terminator pushes one extra char into the buffer;
    the safety margin must keep the trigger body from being truncated."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_full_buffer_trigger_plus_terminator_still_expands(self):
        long_trigger = "x" + "y" * 30
        app = make_app(self.tmp, {long_trigger: "big"})
        app._erase_chars = mock.Mock()
        app.terminator_mode = True

        # Saturate the buffer, then the trigger, then the terminator.
        for char in ("z" * app.max_trigger_length + long_trigger):
            app._handle_char(char)
        app.task_runner.start.assert_not_called()  # no terminator seen yet

        app._handle_char(" ")
        app.task_runner.start.assert_called_once()
        args = app.task_runner.start.call_args
        self.assertEqual(long_trigger, args.args[1])
        self.assertEqual(" ", args.args[2])  # terminator carried through for re-emit


class FormRoutingTests(unittest.TestCase):
    """A snippet carrying a form variable must be classified into form_triggers
    and routed to the slow (dialog) path, never the fast paste path."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xform": "Olá %%nome%%", "xplain": "texto"})

    def test_form_snippet_is_flagged_and_routed_to_slow_path(self):
        self.assertIn("xform", self.app.trigger_index["form_triggers"])
        with mock.patch.object(self.app, "run_slow_snippet", return_value=True) as slow, \
                mock.patch.object(self.app, "expand_snippet", return_value=True) as fast:
            self.app._run_expansion("xform")
        slow.assert_called_once_with("xform")
        fast.assert_not_called()

    def test_plain_snippet_is_not_flagged_and_uses_fast_path(self):
        self.assertNotIn("xplain", self.app.trigger_index["form_triggers"])
        with mock.patch.object(self.app, "run_slow_snippet", return_value=True) as slow, \
                mock.patch.object(self.app, "expand_snippet", return_value=True) as fast:
            self.app._run_expansion("xplain")
        fast.assert_called_once_with("xplain")
        slow.assert_not_called()

    def test_mapping_form_snippet_opens_dialog_and_inserts_resolved_value(self):
        app = make_app(self.tmp, {
            "_prompt_codes": {
                "__prefix__": "prompt",
                "spec": "Write this: %%spec%%",
            },
        })
        self.assertIn("promptspec", app.trigger_index["form_triggers"])

        with mock.patch.object(app, "_show_form_dialog", return_value={"spec": "be concise"}) as dialog, \
                mock.patch.object(tx.time, "sleep"):
            app._run_expansion("promptspec")

        dialog.assert_called_once_with(["spec"])
        app.text_inserter.insert_text.assert_called_once_with("Write this: be concise")


class InsertionTimingWiringTests(unittest.TestCase):
    """settings.json reaches the erase loop and the inserter (issue #27)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _app(self, settings):
        with open(os.path.join(self.tmp, "settings.json"), "w", encoding="utf-8") as handle:
            json.dump(settings, handle)
        return make_app(self.tmp, {"xhi": "hello"}, stub_inserter=False)

    def test_defaults_come_from_the_running_platform(self):
        import platform_support

        defaults = platform_support.default_insertion_timings()
        app = self._app({})
        self.assertEqual(defaults["erase_key_delay"], app.erase_key_delay)
        self.assertEqual(defaults["clipboard_settle_delay"], app.text_inserter.settle_delay)
        self.assertEqual(defaults["paste_restore_delay"], app.text_inserter.restore_delay)

    def test_overrides_reach_both_the_erase_loop_and_the_inserter(self):
        app = self._app({
            "erase_key_delay": 0.02,
            "clipboard_settle_delay": 0.07,
            "paste_restore_delay": 0.2,
        })
        self.assertEqual(0.02, app.erase_key_delay)
        self.assertEqual(0.07, app.text_inserter.settle_delay)
        self.assertEqual(0.2, app.text_inserter.restore_delay)

    def test_a_bad_override_is_logged_and_the_default_survives(self):
        import platform_support

        default = platform_support.default_insertion_timings()["erase_key_delay"]
        logger = mock.Mock()
        with mock.patch.object(tx, "AppLogger", return_value=logger):
            app = self._app({"erase_key_delay": 10})
        self.assertEqual(default, app.erase_key_delay)
        self.assertTrue(
            any("erase_key_delay" in str(call) for call in logger.warning.call_args_list)
        )


class RuntimeSettingWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_malformed_known_settings_reach_runtime_as_safe_defaults(self):
        with open(
            os.path.join(self.tmp, "settings.json"), "w", encoding="utf-8"
        ) as handle:
            json.dump({
                "terminator_mode": "false",
                "bcb_timeout": "3",
                "bcb_cache_seconds": "300",
                "stock_cache_seconds": "600",
            }, handle)
        logger = mock.Mock()

        with mock.patch.object(tx, "AppLogger", return_value=logger):
            app = make_app(self.tmp, {"xhi": "hello"})

        self.assertFalse(app.terminator_mode)
        self.assertEqual(app.bcb.timeout, 3)
        self.assertEqual(app.bcb.cache_seconds, 300)
        self.assertEqual(app.b3_consultor.cache_seconds, 600)
        for key in (
            "terminator_mode",
            "bcb_timeout",
            "bcb_cache_seconds",
            "stock_cache_seconds",
        ):
            self.assertTrue(
                any(key in str(call) for call in logger.warning.call_args_list)
            )


if __name__ == "__main__":
    unittest.main()
