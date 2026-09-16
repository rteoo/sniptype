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
from rich_text_support import build_rich_text_payload


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


class WorkflowHotkeyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp, {"xhi": "hello", "_codes": {"city": "GYN"}})
        self.app.gui = mock.Mock()
        self.app.task_runner = mock.Mock()

    def test_listener_routes_hotkey_without_gui_work_and_release_rearms(self):
        self.app.hotkey_router = tx.HotkeyRouter(
            {"open_manager": "<ctrl>+<shift>+m"},
            self.app._dispatch_hotkey_action,
        )

        self.assertIsNone(self.app.on_press(Key.ctrl))
        self.assertIsNone(self.app.on_press(Key.shift))
        self.app.typed_text = "partial"
        self.app.on_press(KeyCode.from_char("m"))
        self.assertEqual("", self.app.typed_text)
        self.app.gui.submit.assert_not_called()
        self.assertEqual(self.app._run_hotkey_action, self.app.task_runner.start.call_args.args[0])
        self.assertEqual("open_manager", self.app.task_runner.start.call_args.args[1])

        self.app.on_release(Key.ctrl)
        self.app.on_release(Key.shift)
        self.app.on_release(KeyCode.from_char("m"))
        self.app.task_runner.reset_mock()
        self.app.on_press(Key.ctrl)
        self.app.on_press(Key.shift)
        self.app.on_press(KeyCode.from_char("m"))
        self.assertEqual(1, self.app.task_runner.start.call_count)

    def test_edit_last_and_toggle_actions_queue_safe_seams(self):
        reference = tx.SnippetRef("static", "xhi")
        self.app.workflow_state.record_success(reference)

        self.app._run_hotkey_action("edit_last")
        self.assertEqual(reference, self.app._pending_manager_target)
        self.app.gui.submit.assert_called_once_with(self.app._show_manager_window)

        self.app.gui.reset_mock()
        self.app._run_hotkey_action("toggle_enabled")
        self.app.gui.submit.assert_called_once_with(self.app._toggle_enabled_from_hotkey)
        self.app.icon = None
        self.assertTrue(self.app.enabled)
        self.app._toggle_enabled_from_hotkey()
        self.assertFalse(self.app.enabled)

    def test_success_records_static_mapping_and_renamed_dynamic_stable_refs(self):
        self.app.expand_snippet = mock.Mock(return_value=True)
        self.app._run_expansion("xhi")
        self.assertEqual(tx.SnippetRef("static", "xhi"), self.app.workflow_state.last_successful_item)

        self.app.expand_snippet.reset_mock()
        self.app._run_expansion("codescity")
        self.assertEqual(
            tx.SnippetRef("mapping", "city", "_codes"),
            self.app.workflow_state.last_successful_item,
        )

        self.app.dynamic_registry = {"stable": {"trigger": "xnow"}}
        self.app.snippets["xnow"] = lambda: "now"
        self.app.refresh_runtime_indexes()
        target = self.app.trigger_index["direct_targets_by_last_char"]["w"][0]
        self.app.dynamic_registry = {}
        self.app._run_expansion(target)
        self.assertEqual(tx.SnippetRef("dynamic", "stable"), self.app.workflow_state.last_successful_item)

    def test_failed_or_cancelled_expansion_does_not_record(self):
        self.app.expand_snippet = mock.Mock(return_value=False)
        self.app._run_expansion("xhi")
        self.assertIsNone(self.app.workflow_state.last_successful_item)

    def test_hotkey_router_changes_only_after_atomic_settings_save(self):
        self.app.settings_file = os.path.join(self.tmp, "settings.json")
        self.app.settings = {"hotkeys": {"open_manager": "<ctrl>+m"}, "future": 1}
        original_router = self.app.hotkey_router

        with mock.patch.object(tx, "save_settings", return_value=False):
            self.assertFalse(self.app._save_hotkey_bindings({"open_manager": "<alt>+m"}))
        self.assertIs(original_router, self.app.hotkey_router)
        self.assertEqual("<ctrl>+m", self.app.settings["hotkeys"]["open_manager"])

        with mock.patch.object(tx, "save_settings", return_value=True) as save:
            self.assertTrue(self.app._save_hotkey_bindings({"open_manager": "<alt>+m"}))
        save.assert_called_once()
        self.assertEqual("<alt>+m", self.app.settings["hotkeys"]["open_manager"])
        self.assertIsNot(original_router, self.app.hotkey_router)


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


class GroupPolicyHotpathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _app(self, snippets, metadata, *, terminator_mode=False):
        app = make_app(self.tmp, snippets)
        app.library_metadata = metadata
        app.terminator_mode = terminator_mode
        app.refresh_runtime_indexes()
        app._erase_chars = mock.Mock()
        return app

    def test_foreground_identity_is_queried_only_after_a_scoped_candidate(self):
        metadata = {
            "groups": {
                "allow": {
                    "applications": {
                        "mode": "allow",
                        "executables": ["editor.exe"],
                    }
                }
            },
            "items": {"static": {"xhi": {"group_id": "allow"}}},
        }
        app = self._app({"xhi": "hello"}, metadata)
        with mock.patch.object(
            tx.platform_support,
            "IS_WINDOWS",
            True,
        ), mock.patch.object(
            tx.platform_support,
            "foreground_executable_name",
            return_value="editor.exe",
        ) as identity:
            app._handle_char("z")
            identity.assert_not_called()
            app._handle_char("x")
            app._handle_char("h")
            app._handle_char("i")
        identity.assert_called_once_with()

    def test_denied_longest_candidate_leaves_buffer_and_does_not_dispatch(self):
        metadata = {
            "groups": {
                "deny": {
                    "applications": {
                        "mode": "deny",
                        "executables": ["blocked.exe"],
                    }
                }
            },
            "items": {"static": {"x": {"group_id": "deny"}, "wx": {"group_id": "deny"}}},
        }
        app = self._app({"x": "short", "wx": "long"}, metadata)
        with mock.patch.object(tx.platform_support, "IS_WINDOWS", True), \
                mock.patch.object(
                    tx.platform_support,
                    "foreground_executable_name",
                    return_value="blocked.exe",
                ):
            app._handle_char("w")
            app._handle_char("x")
        app._erase_chars.assert_not_called()
        app.task_runner.start.assert_not_called()
        self.assertEqual("wx", app.typed_text)

    def test_prefixed_target_passes_stable_identity_to_worker(self):
        metadata = {
            "groups": {"work": {"prefix": "w"}},
            "items": {"static": {"xhi": {"group_id": "work"}}},
        }
        app = self._app({"xhi": "hello"}, metadata)
        for char in "wxhi":
            app._handle_char(char)
        args = app.task_runner.start.call_args
        target = args.args[1]
        self.assertEqual("wxhi", target.effective_trigger)
        self.assertEqual("xhi", target.stable_identity)
        self.assertEqual(4, app._erase_chars.call_args.args[0])

    def test_mixed_immediate_and_terminated_groups_use_separate_buckets(self):
        metadata = {
            "groups": {
                "immediate": {"terminator": "immediate"},
                "terminated": {"terminator": "terminator"},
            },
            "items": {
                "static": {
                    "xfast": {"group_id": "immediate"},
                    "xslow": {"group_id": "terminated"},
                }
            },
        }
        app = self._app(
            {"xfast": "fast", "xslow": "slow"},
            metadata,
            terminator_mode=True,
        )
        for char in "xfast":
            app._handle_char(char)
        self.assertEqual("xfast", app.task_runner.start.call_args.args[1].effective_trigger)
        app.task_runner.reset_mock()
        app._erase_chars.reset_mock()
        for char in "xslow ":
            app._handle_char(char)
        args = app.task_runner.start.call_args
        self.assertEqual("xslow", args.args[1].effective_trigger)
        self.assertEqual(" ", args.args[2])

    def test_group_terminator_policy_works_when_global_mode_is_immediate(self):
        metadata = {
            "groups": {"terminated": {"terminator": "terminator"}},
            "items": {"static": {"xslow": {"group_id": "terminated"}}},
        }
        app = self._app({"xslow": "slow"}, metadata, terminator_mode=False)

        for char in "xslow":
            app._handle_char(char)
        app.task_runner.start.assert_not_called()
        app._handle_char(" ")

        args = app.task_runner.start.call_args
        self.assertEqual("xslow", args.args[1].effective_trigger)
        self.assertEqual(" ", args.args[2])

    def test_group_prefix_contributes_to_trigger_buffer_length(self):
        prefix = "department-" * 8
        metadata = {
            "groups": {"long": {"prefix": prefix}},
            "items": {"static": {"x": {"group_id": "long"}}},
        }
        app = self._app({"x": "value"}, metadata)

        self.assertGreaterEqual(
            app.max_trigger_length,
            len(prefix + "x") + tx.TRIGGER_BUFFER_MARGIN,
        )

    def test_queued_target_keeps_stable_identity_across_index_refresh(self):
        metadata = {
            "groups": {"work": {"prefix": "w"}},
            "items": {"static": {"xhi": {"group_id": "work"}}},
        }
        app = self._app({"xhi": "hello"}, metadata)
        for char in "wxhi":
            app._handle_char(char)
        target = app.task_runner.start.call_args.args[1]
        app.task_runner.reset_mock()
        app.library_metadata = {
            "groups": {"other": {"prefix": "z"}},
            "items": {"static": {"xhi": {"group_id": "other"}}},
        }
        app.refresh_runtime_indexes()
        with mock.patch.object(app, "expand_snippet", return_value=True) as expand:
            app._run_expansion(target)
        expand.assert_called_once_with("xhi")


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
        self._non_windows = mock.patch.object(tx.platform_support, "IS_WINDOWS", False)
        self._non_windows.start()
        self.addCleanup(self._non_windows.stop)
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

    def test_windows_focus_is_restored_to_the_exact_target(self):
        events = []
        target = ("hwnd", 42)

        def build(root):
            events.append(("build", root))
            return "Ada"

        with mock.patch.object(tx.platform_support, "IS_WINDOWS", True), \
                mock.patch.object(
                    tx.platform_support,
                    "capture_text_target",
                    side_effect=lambda: events.append(("capture", None)) or target,
                ), mock.patch.object(
                    tx.platform_support,
                    "restore_text_target",
                    side_effect=lambda value: events.append(("restore", value)) or True,
                ):
            result = self.app._run_modal_dialog(build, None, "campos")

        self.assertEqual("Ada", result)
        self.assertEqual(
            [("capture", None), ("build", mock.ANY), ("restore", target)],
            events,
        )

    def test_windows_missing_target_fails_closed_before_showing_dialog(self):
        build = mock.Mock(return_value="Ada")
        with mock.patch.object(tx.platform_support, "IS_WINDOWS", True), \
                mock.patch.object(
                    tx.platform_support, "capture_text_target", return_value=None
                ), mock.patch.object(
                    tx.platform_support, "restore_text_target"
                ) as restore:
            with self.assertRaisesRegex(RuntimeError, "capture"):
                self.app._run_modal_dialog(build, None, "campos")

        build.assert_not_called()
        restore.assert_not_called()

    def test_windows_restore_failure_discards_dialog_result(self):
        target = ("hwnd", 42)
        with mock.patch.object(tx.platform_support, "IS_WINDOWS", True), \
                mock.patch.object(
                    tx.platform_support, "capture_text_target", return_value=target
                ), mock.patch.object(
                    tx.platform_support, "restore_text_target", return_value=False
                ) as restore:
            with self.assertRaisesRegex(RuntimeError, "restore"):
                self.app._run_modal_dialog(lambda _root: "Ada", None, "campos")

        restore.assert_called_once_with(target)

    def test_windows_cancelled_dialog_restores_target_and_releases_lock(self):
        target = ("hwnd", 42)
        with mock.patch.object(tx.platform_support, "IS_WINDOWS", True), \
                mock.patch.object(
                    tx.platform_support, "capture_text_target", return_value=target
                ), mock.patch.object(
                    tx.platform_support, "restore_text_target", return_value=True
                ) as restore:
            self.assertIsNone(
                self.app._run_modal_dialog(lambda _root: None, None, "campos")
            )
            self.assertEqual(
                "again",
                self.app._run_modal_dialog(lambda _root: "again", None, "campos"),
            )

        self.assertEqual(2, restore.call_count)

    def test_windows_dialog_exception_restores_target_and_releases_lock(self):
        target = ("hwnd", 42)
        with mock.patch.object(tx.platform_support, "IS_WINDOWS", True), \
                mock.patch.object(
                    tx.platform_support, "capture_text_target", return_value=target
                ), mock.patch.object(
                    tx.platform_support, "restore_text_target", return_value=True
                ) as restore:
            with self.assertRaisesRegex(ValueError, "dialog failed"):
                self.app._run_modal_dialog(
                    lambda _root: (_ for _ in ()).throw(ValueError("dialog failed")),
                    None,
                    "campos",
                )
            self.assertEqual(
                "again",
                self.app._run_modal_dialog(lambda _root: "again", None, "campos"),
            )

        self.assertEqual(2, restore.call_count)


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
        self._press("ab")
        self.app.on_press(Key.enter)
        self.assertEqual("", self.app.typed_text)

    def test_backspace_pops_the_last_buffered_char(self):
        self._press("abx")
        self.app.on_press(Key.backspace)
        self.assertEqual("ab", self.app.typed_text)

    def test_unknown_special_key_neither_crashes_nor_changes_buffer(self):
        self._press("ab")
        self.app.on_press(Key.shift)
        self.assertEqual("ab", self.app.typed_text)

    def test_escape_does_not_dispatch_or_clear_buffer(self):
        self._press("ab")
        self.app.task_runner.reset_mock()
        self.app.on_press(Key.esc)
        self.assertEqual("ab", self.app.typed_text)
        self.app.task_runner.start.assert_not_called()





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
            "_template_codes": {
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

    def test_structured_form_renders_defaults_and_uses_one_pass_values(self):
        app = make_app(self.tmp, {
            "xform": "Olá %%cliente%%, %%nome%%",
            "cliente": "equipe",
        })
        app.library_metadata = {
            "items": {
                "static": {
                    "xform": {
                        "form": {
                            "fields": [{"name": "nome", "default": "Cliente"}]
                        }
                    }
                }
            }
        }
        app.refresh_runtime_indexes()
        with mock.patch.object(app, "_show_form_dialog", return_value={}) as dialog, \
                mock.patch.object(tx.time, "sleep"):
            app._run_expansion("xform")

        dialog.assert_called_once()
        self.assertEqual(["nome"], dialog.call_args.args[0])
        self.assertEqual("Olá equipe, Cliente", app.text_inserter.insert_text.call_args.args[0])

        app.text_inserter.reset_mock()
        dialog.reset_mock()
        with mock.patch.object(app, "_show_form_dialog", return_value={"nome": "%%literal%%"}) as literal_dialog, \
                mock.patch.object(tx.time, "sleep"):
            app._run_expansion("xform")
        literal_dialog.assert_called_once()
        self.assertEqual("Olá equipe, %%literal%%", app.text_inserter.insert_text.call_args.args[0])

    def test_structured_form_supports_all_field_types(self):
        app = make_app(self.tmp, {
            "xform": "%%name%%|%%body%%|%%kind%%|%%when%%|%%maybe%%",
        })
        app.library_metadata = {
            "items": {
                "static": {
                    "xform": {"form": {"fields": [
                        {"name": "name", "type": "text"},
                        {"name": "body", "type": "multiline"},
                        {"name": "kind", "type": "choice", "options": ["A", "B"]},
                        {"name": "when", "type": "date", "default": "2026-09-16", "output_format": "%Y/%m/%d"},
                        {"name": "maybe", "type": "optional", "content": "[ok]"},
                    ]}}
                }
            }
        }
        app.refresh_runtime_indexes()
        values = {"name": "Ana", "body": "linha 1\nlinha 2", "kind": "B",
                  "when": "2026-09-17", "maybe": True}
        with mock.patch.object(app, "_show_form_dialog", return_value=values) as dialog, \
                mock.patch.object(tx.time, "sleep"):
            app._run_expansion("xform")
        dialog.assert_called_once()
        self.assertEqual(
            "Ana|linha 1\nlinha 2|B|2026/09/17|[ok]",
            app.text_inserter.insert_text.call_args.args[0],
        )

    def test_structured_form_cancel_inserts_nothing_or_reemits_terminator(self):
        app = make_app(self.tmp, {"xform": "Olá %%nome%%"})
        app.library_metadata = {
            "items": {"static": {"xform": {"form": {"fields": [{"name": "nome"}]}}}}
        }
        app.refresh_runtime_indexes()
        with mock.patch.object(app, "_show_form_dialog", return_value=None) as dialog, \
                mock.patch.object(tx.time, "sleep"):
            app._run_expansion("xform", append_text=" ")
        dialog.assert_called_once()
        app.text_inserter.insert_text.assert_not_called()
        app.keyboard_controller.type.assert_not_called()

    def test_structured_form_rebuilds_rich_spans_after_expansion(self):
        rich = build_rich_text_payload(
            "Olá %%nome%%", [{"tag": "bold", "start": 0, "end": len("Olá %%nome%%")}]
        )
        app = make_app(self.tmp, {"xrich": rich})
        app.library_metadata = {
            "items": {
                "static": {
                    "xrich": {"form": {"fields": [{"name": "nome"}]}}
                }
            }
        }
        app.refresh_runtime_indexes()
        with mock.patch.object(app, "_show_form_dialog", return_value={"nome": "Alexander"}), \
                mock.patch.object(tx.time, "sleep"):
            app._run_expansion("xrich")

        result = app.text_inserter.insert_text.call_args.args[0]
        self.assertEqual("Olá Alexander", result["text"])
        self.assertEqual([{"tag": "bold", "start": 0, "end": len("Olá Alexander")}], result["spans"])

    def test_prefixed_structured_form_keeps_stable_key_for_worker(self):
        app = make_app(self.tmp, {"xform": "Olá %%nome%%"})
        app.library_metadata = {
            "groups": {"work": {"prefix": "w"}},
            "items": {
                "static": {
                    "xform": {
                        "group_id": "work",
                        "form": {"fields": [{"name": "nome"}]},
                    }
                }
            },
        }
        app.refresh_runtime_indexes()
        with mock.patch.object(app, "_show_form_dialog", return_value={"nome": "Ana"}) as dialog, \
                mock.patch.object(tx.time, "sleep"):
            for char in "wxform":
                app._handle_char(char)
            target = app.task_runner.start.call_args.args[1]
            self.assertEqual("xform", target.stable_identity)
            app._run_expansion(target)

        self.assertEqual("xform", target.stable_identity)
        self.assertIsNotNone(dialog.call_args.args[1])
        app.text_inserter.insert_text.assert_called_once_with("Olá Ana")

    def test_dispatch_snapshots_slow_route_across_index_refresh(self):
        app = make_app(self.tmp, {"xform": "Olá %%nome%%"})
        app.library_metadata = {
            "groups": {"work": {"prefix": "w"}},
            "items": {
                "static": {
                    "xform": {
                        "group_id": "work",
                        "form": {"fields": [{"name": "nome"}]},
                    }
                }
            },
        }
        app.refresh_runtime_indexes()

        with mock.patch.object(tx.time, "sleep"):
            for char in "wxform":
                app._handle_char(char)

        worker_target = app.task_runner.start.call_args.args[1]
        slow_route = app.task_runner.start.call_args.args[3]
        self.assertTrue(slow_route)

        # Simulate a manager refresh before the queued worker gets CPU time.
        app.trigger_index = dict(app.trigger_index)
        app.trigger_index["slow_triggers"] = frozenset()
        app.trigger_index["form_triggers"] = frozenset()
        with mock.patch.object(app, "run_slow_snippet", return_value=True) as slow, \
                mock.patch.object(app, "expand_snippet") as plain:
            app._run_expansion(worker_target, "", slow_route)

        slow.assert_called_once_with("xform")
        plain.assert_not_called()


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
