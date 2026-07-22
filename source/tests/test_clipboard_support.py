import contextlib
import logging
import re
import subprocess
import types
import unittest
from unittest import mock

import clipboard_support
from clipboard_support import (
    PosixClipboard,
    _html_clipboard_bytes,
    build_clipboard,
    posix_clipboard_commands,
)


def _which(*available):
    known = set(available)
    return lambda name: f"/usr/bin/{name}" if name in known else None


class NormalizeClipboardNewlinesTests(unittest.TestCase):
    def test_lf_text_becomes_crlf(self):
        self.assertEqual(
            clipboard_support.normalize_clipboard_newlines("a\nb"), "a\r\nb"
        )

    def test_crlf_text_is_not_doubled(self):
        """Regression: text taken from the clipboard already carries CRLF.

        A blind ``\\n`` -> ``\\r\\n`` turned it into ``\\r\\r\\n``, which pastes a
        doubled blank line and makes the stored payload no longer equal to the
        snippet it was built from. Every ``%%clipboard-paste%%`` snippet hits this
        whenever the copied text is multi-line.
        """
        self.assertEqual(
            clipboard_support.normalize_clipboard_newlines("a\r\nb"), "a\r\nb"
        )

    def test_normalization_is_idempotent(self):
        once = clipboard_support.normalize_clipboard_newlines("a\r\nb\nc\rd")
        self.assertEqual(clipboard_support.normalize_clipboard_newlines(once), once)

    def test_lone_cr_is_normalized(self):
        self.assertEqual(
            clipboard_support.normalize_clipboard_newlines("a\rb"), "a\r\nb"
        )

    def test_empty_string_is_unchanged(self):
        self.assertEqual("", clipboard_support.normalize_clipboard_newlines(""))

    def test_bare_newline_characters_become_crlf(self):
        self.assertEqual("\r\n", clipboard_support.normalize_clipboard_newlines("\n"))
        self.assertEqual("\r\n", clipboard_support.normalize_clipboard_newlines("\r"))
        self.assertEqual(
            "\r\n", clipboard_support.normalize_clipboard_newlines("\r\n")
        )

    def test_cr_followed_by_crlf_expands_to_two_stable_breaks(self):
        # "\r\r\n" is a bare CR then a CRLF: two line breaks, normalized to two
        # CRLF breaks. It must be a fixed point, never grow on a second pass.
        result = clipboard_support.normalize_clipboard_newlines("\r\r\n")
        self.assertEqual("\r\n\r\n", result)
        self.assertEqual(result, clipboard_support.normalize_clipboard_newlines(result))

    def test_lf_then_cr_expands_to_two_stable_breaks(self):
        result = clipboard_support.normalize_clipboard_newlines("\n\r")
        self.assertEqual("\r\n\r\n", result)
        self.assertEqual(result, clipboard_support.normalize_clipboard_newlines(result))

    def test_hostile_mixes_are_all_idempotent(self):
        # The load-bearing property: whatever the input, a second normalization
        # pass must not change the result (no CRLF doubling).
        for hostile in ["", "\n", "\r", "\r\n", "\r\r\n", "\n\r", "\n\n",
                        "a\nb\r\nc\rd", "\r\n\r\n", "line\r\r\rend"]:
            once = clipboard_support.normalize_clipboard_newlines(hostile)
            twice = clipboard_support.normalize_clipboard_newlines(once)
            self.assertEqual(once, twice, f"not idempotent for {hostile!r}")
            self.assertNotIn("\r\r", once, f"produced doubled CR for {hostile!r}")


class HtmlClipboardBytesTests(unittest.TestCase):
    def test_html_clipboard_bytes_include_required_header(self):
        payload = _html_clipboard_bytes("<div><strong>abc</strong></div>")

        self.assertIn(b"Version:0.9", payload)
        self.assertIn(b"StartHTML:", payload)
        self.assertIn(b"EndHTML:", payload)
        self.assertIn(b"StartFragment:", payload)
        self.assertIn(b"EndFragment:", payload)
        self.assertIn(b"<strong>abc</strong>", payload)

    def test_fragment_offsets_are_byte_offsets_for_non_ascii_content(self):
        """Regression: CF_HTML offsets are byte offsets into the UTF-8 payload.
        Character offsets undercount once the fragment has accented letters,
        making EndFragment land short and truncating the pasted rich text."""
        fragment = "<div>expansão de ação</div>"
        payload = _html_clipboard_bytes(fragment)

        header = payload.decode("utf-8")
        start = int(re.search(r"StartFragment:(\d+)", header).group(1))
        end = int(re.search(r"EndFragment:(\d+)", header).group(1))

        self.assertEqual(fragment, payload[start:end].decode("utf-8"))


class BackendSelectionTests(unittest.TestCase):
    @unittest.skipUnless(clipboard_support.IS_WINDOWS, "needs a Windows host")
    def test_windows_selects_the_win32_backend(self):
        self.assertIsInstance(build_clipboard(), clipboard_support.WindowsClipboard)

    @unittest.skipIf(clipboard_support.IS_WINDOWS, "Win32 names exist on Windows")
    def test_win32_implementation_is_absent_off_windows(self):
        """The ctypes bindings must not half-exist: absent beats NameError."""
        self.assertFalse(hasattr(clipboard_support, "WindowsClipboard"))
        self.assertFalse(hasattr(clipboard_support, "USER32"))

    def test_non_windows_selects_the_posix_backend(self):
        with mock.patch.object(clipboard_support, "IS_WINDOWS", False), \
                mock.patch.object(clipboard_support, "IS_MAC", True), \
                mock.patch.object(clipboard_support.shutil, "which", _which("pbcopy", "pbpaste")):
            self.assertIsInstance(build_clipboard(), PosixClipboard)


class PosixCommandSelectionTests(unittest.TestCase):
    def test_macos_uses_pbcopy_and_pbpaste(self):
        with mock.patch.object(clipboard_support, "IS_MAC", True), \
                mock.patch.object(clipboard_support.shutil, "which", _which("pbcopy", "pbpaste")):
            self.assertEqual((["pbcopy"], ["pbpaste"]), posix_clipboard_commands({}))

    def test_wayland_is_preferred_when_wl_clipboard_is_installed(self):
        with mock.patch.object(clipboard_support, "IS_MAC", False), \
                mock.patch.object(clipboard_support.shutil, "which", _which("wl-copy", "wl-paste", "xclip")):
            copy_argv, paste_argv = posix_clipboard_commands({"WAYLAND_DISPLAY": "wayland-0"})

        self.assertEqual(["wl-copy"], copy_argv)
        self.assertEqual(["wl-paste", "--no-newline"], paste_argv)

    def test_x11_falls_back_to_xclip_then_xsel(self):
        with mock.patch.object(clipboard_support, "IS_MAC", False), \
                mock.patch.object(clipboard_support.shutil, "which", _which("xclip", "xsel")):
            copy_argv, _ = posix_clipboard_commands({})
        self.assertEqual(["xclip", "-selection", "clipboard"], copy_argv)

        with mock.patch.object(clipboard_support, "IS_MAC", False), \
                mock.patch.object(clipboard_support.shutil, "which", _which("xsel")):
            copy_argv, paste_argv = posix_clipboard_commands({})
        self.assertEqual(["xsel", "--clipboard", "--input"], copy_argv)
        self.assertEqual(["xsel", "--clipboard", "--output"], paste_argv)

    def test_wayland_without_wl_clipboard_falls_back_to_x11(self):
        with mock.patch.object(clipboard_support, "IS_MAC", False), \
                mock.patch.object(clipboard_support.shutil, "which", _which("xclip")):
            copy_argv, _ = posix_clipboard_commands({"WAYLAND_DISPLAY": "wayland-0"})
        self.assertEqual(["xclip", "-selection", "clipboard"], copy_argv)

    def test_no_tool_installed_returns_no_commands(self):
        with mock.patch.object(clipboard_support, "IS_MAC", False), \
                mock.patch.object(clipboard_support.shutil, "which", _which()):
            self.assertEqual((None, None), posix_clipboard_commands({}))


def _make_posix_clipboard(*available, environ=None):
    with mock.patch.object(clipboard_support, "IS_MAC", False), \
            mock.patch.object(clipboard_support.shutil, "which", _which(*available)):
        return PosixClipboard(environ or {})


class PosixClipboardRoundTripTests(unittest.TestCase):
    def test_set_content_pipes_text_to_the_copy_tool(self):
        clipboard = _make_posix_clipboard("xclip")
        completed = subprocess.CompletedProcess(["xclip"], 0, b"", b"")

        with mock.patch.object(clipboard_support.subprocess, "run", return_value=completed) as run:
            self.assertTrue(clipboard.set_content("olá mundo"))

        run.assert_called_once()
        self.assertEqual(["xclip", "-selection", "clipboard"], run.call_args.args[0])
        self.assertEqual("olá mundo".encode("utf-8"), run.call_args.kwargs["input"])

    def test_copy_never_captures_output(self):
        """Regression: xclip/wl-copy fork a daemon that owns the selection and
        inherits our stdout pipe. Reading it to EOF waits on the daemon, not on
        the command, so capturing output hangs every paste until the timeout."""
        clipboard = _make_posix_clipboard("xclip")
        completed = subprocess.CompletedProcess(["xclip"], 0, b"", b"")

        with mock.patch.object(clipboard_support.subprocess, "run", return_value=completed) as run:
            clipboard.set_content("texto")

        kwargs = run.call_args.kwargs
        self.assertNotIn("capture_output", kwargs)
        self.assertIs(subprocess.DEVNULL, kwargs["stdout"])
        self.assertIs(subprocess.DEVNULL, kwargs["stderr"])
        self.assertEqual(clipboard_support._POSIX_TIMEOUT, kwargs["timeout"])

    def test_hanging_copy_tool_fails_instead_of_blocking_forever(self):
        error = subprocess.TimeoutExpired(["xclip"], clipboard_support._POSIX_TIMEOUT)
        clipboard = _make_posix_clipboard("xclip")

        with mock.patch.object(clipboard_support.subprocess, "run", side_effect=error), \
                self.assertLogs(clipboard_support._LOGGER, level=logging.WARNING):
            self.assertFalse(clipboard.set_content("texto"))

    def test_get_text_decodes_the_paste_tool_output(self):
        clipboard = _make_posix_clipboard("xclip")
        completed = subprocess.CompletedProcess(["xclip"], 0, "olá".encode("utf-8"), b"")

        with mock.patch.object(clipboard_support.subprocess, "run", return_value=completed) as run:
            self.assertEqual("olá", clipboard.get_text())

        self.assertEqual(["xclip", "-selection", "clipboard", "-o"], run.call_args.args[0])

    def test_round_trip_through_a_fake_clipboard_tool(self):
        clipboard = _make_posix_clipboard("xclip")
        buffer = {}

        def fake_run(argv, **kwargs):
            if argv[-1] == "-o":
                return subprocess.CompletedProcess(argv, 0, buffer.get("data", b""), b"")
            buffer["data"] = kwargs["input"]
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with mock.patch.object(clipboard_support.subprocess, "run", fake_run):
            self.assertTrue(clipboard.set_content("round trip"))
            self.assertEqual("round trip", clipboard.get_text())

    def test_failing_tool_reports_failure_instead_of_raising(self):
        clipboard = _make_posix_clipboard("xclip")
        completed = subprocess.CompletedProcess(["xclip"], 1, b"", b"boom")

        with mock.patch.object(clipboard_support.subprocess, "run", return_value=completed):
            self.assertFalse(clipboard.set_content("texto"))
            self.assertIsNone(clipboard.get_text())

    def test_subprocess_error_is_logged_and_swallowed(self):
        clipboard = _make_posix_clipboard("xclip")

        with mock.patch.object(
            clipboard_support.subprocess, "run", side_effect=OSError("no such tool")
        ), self.assertLogs(clipboard_support._LOGGER, level=logging.WARNING):
            self.assertFalse(clipboard.set_content("texto"))

    def test_missing_tool_degrades_with_a_log_line(self):
        with self.assertLogs(clipboard_support._LOGGER, level=logging.WARNING) as logs:
            clipboard = _make_posix_clipboard()

        with mock.patch.object(clipboard_support, "IS_MAC", False), \
                mock.patch.object(clipboard_support.shutil, "which", _which()):
            self.assertTrue(any("xclip" in line for line in logs.output))
            self.assertIsNone(clipboard.get_text())
            self.assertFalse(clipboard.set_content("texto"))

    def test_tool_installed_after_startup_is_picked_up_without_a_restart(self):
        """The app lives in the tray for weeks; a clipboard tool that appears
        later (session start, fresh install) must work without relaunching."""
        with self.assertLogs(clipboard_support._LOGGER, level=logging.WARNING):
            clipboard = _make_posix_clipboard()

        # The commands are re-resolved on every call, so the "no tool yet" state
        # has to hold for the assertion too — otherwise the host's real pbcopy
        # (macOS) or xclip (Linux) answers and the clipboard reports success.
        with mock.patch.object(clipboard_support, "IS_MAC", False), \
                mock.patch.object(clipboard_support.shutil, "which", _which()):
            self.assertFalse(clipboard.set_content("cedo demais"))

        completed = subprocess.CompletedProcess(["xclip"], 0, b"", b"")
        with mock.patch.object(clipboard_support, "IS_MAC", False), \
                mock.patch.object(clipboard_support.shutil, "which", _which("xclip")), \
                mock.patch.object(clipboard_support.subprocess, "run", return_value=completed) as run:
            self.assertTrue(clipboard.set_content("agora vai"))

        self.assertEqual(["xclip", "-selection", "clipboard"], run.call_args.args[0])


class PosixRichTextDowngradeTests(unittest.TestCase):
    def test_rich_text_is_downgraded_to_plain_text_and_logged(self):
        clipboard = _make_posix_clipboard("xclip")
        rich_value = {
            "__kind__": "rich_text",
            "text": "negrito",
            "spans": [],
            "html": "<strong>negrito</strong>",
            "rtf": r"{\rtf1\ansi negrito}",
        }
        completed = subprocess.CompletedProcess(["xclip"], 0, b"", b"")

        with mock.patch.object(clipboard_support.subprocess, "run", return_value=completed) as run, \
                self.assertLogs(clipboard_support._LOGGER, level=logging.INFO) as logs:
            self.assertTrue(clipboard.set_content(rich_value))

        self.assertEqual(b"negrito", run.call_args.kwargs["input"])
        self.assertTrue(any("texto simples" in line for line in logs.output))

        # The downgrade is logged once per session, not once per paste — a
        # daily-use rich snippet would otherwise flood the log.
        with mock.patch.object(clipboard_support.subprocess, "run", return_value=completed), \
                self.assertNoLogs(clipboard_support._LOGGER, level=logging.INFO):
            self.assertTrue(clipboard.set_content(rich_value))


@contextlib.contextmanager
def _win32_backend():
    """Patch the ctypes Win32 bindings with success-configured mocks.

    Every clipboard test drives ``WindowsClipboard`` through these mocks so no
    real user32/kernel32 call ever runs and the real clipboard is never touched.
    ``ctypes.memmove``/``wstring_at`` are stubbed because the mocked GlobalLock
    hands back a plain int rather than a writable address. Individual tests
    override single return values to force a failure at one step.
    """
    with mock.patch.object(clipboard_support, "USER32") as user32, \
            mock.patch.object(clipboard_support, "KERNEL32") as kernel32, \
            mock.patch.object(clipboard_support.ctypes, "memmove") as memmove, \
            mock.patch.object(
                clipboard_support.ctypes, "wstring_at", return_value="conteúdo"
            ) as wstring_at, \
            mock.patch.object(clipboard_support.time, "sleep"):
        user32.OpenClipboard.return_value = 1
        user32.CloseClipboard.return_value = 1
        user32.EmptyClipboard.return_value = 1
        user32.SetClipboardData.return_value = 1
        user32.IsClipboardFormatAvailable.return_value = 1
        user32.GetClipboardData.return_value = 0xABC
        kernel32.GlobalAlloc.return_value = 0x1000
        kernel32.GlobalLock.return_value = 0x2000
        kernel32.GlobalUnlock.return_value = 1
        kernel32.GlobalFree.return_value = 0
        yield types.SimpleNamespace(
            user32=user32,
            kernel32=kernel32,
            memmove=memmove,
            wstring_at=wstring_at,
        )


_RICH_VALUE = {
    "__kind__": "rich_text",
    "text": "negrito",
    "spans": [{"tag": "bold", "start": 0, "end": 7}],
    "html": "<div><strong>negrito</strong></div>",
    "rtf": r"{\rtf1\ansi negrito}",
}


@unittest.skipUnless(clipboard_support.IS_WINDOWS, "needs the Win32 backend")
class WindowsClipboardSetContentTests(unittest.TestCase):
    def test_plain_text_success_writes_utf16_and_closes(self):
        with _win32_backend() as m:
            clipboard = clipboard_support.WindowsClipboard()
            self.assertTrue(clipboard.set_content("olá mundo"))

        m.user32.EmptyClipboard.assert_called_once()
        self.assertEqual(1, m.user32.SetClipboardData.call_count)
        m.user32.CloseClipboard.assert_called_once()
        buffer = m.memmove.call_args.args[1]
        self.assertEqual("olá mundo\0", buffer.decode("utf-16-le"))

    def test_emoji_payload_survives_utf16_encoding(self):
        with _win32_backend() as m:
            clipboard = clipboard_support.WindowsClipboard()
            self.assertTrue(clipboard.set_content("café 🎉"))

        buffer = m.memmove.call_args.args[1]
        self.assertEqual("café 🎉\0", buffer.decode("utf-16-le"))

    def test_embedded_null_byte_is_encoded_verbatim(self):
        # Null-byte hostility: a snippet carrying an interior NUL must not crash
        # the encoder. It is written faithfully (the truncation risk is on the
        # read side via wstring_at, not here).
        with _win32_backend() as m:
            clipboard = clipboard_support.WindowsClipboard()
            self.assertTrue(clipboard.set_content("a\0b"))

        buffer = m.memmove.call_args.args[1]
        self.assertEqual("a\0b\0", buffer.decode("utf-16-le"))

    def test_open_failure_returns_false_and_never_closes(self):
        with _win32_backend() as m:
            m.user32.OpenClipboard.return_value = 0
            clipboard = clipboard_support.WindowsClipboard()
            self.assertFalse(clipboard.set_content("x"))

        self.assertEqual(10, m.user32.OpenClipboard.call_count)  # retried
        m.user32.CloseClipboard.assert_not_called()

    def test_empty_clipboard_failure_still_closes(self):
        with _win32_backend() as m:
            m.user32.EmptyClipboard.return_value = 0
            clipboard = clipboard_support.WindowsClipboard()
            self.assertFalse(clipboard.set_content("x"))

        m.user32.SetClipboardData.assert_not_called()
        m.user32.CloseClipboard.assert_called_once()

    def test_global_alloc_failure_closes_without_freeing(self):
        with _win32_backend() as m:
            m.kernel32.GlobalAlloc.return_value = 0
            clipboard = clipboard_support.WindowsClipboard()
            self.assertFalse(clipboard.set_content("x"))

        m.kernel32.GlobalFree.assert_not_called()
        m.user32.SetClipboardData.assert_not_called()
        m.user32.CloseClipboard.assert_called_once()

    def test_global_lock_failure_frees_handle_and_closes(self):
        with _win32_backend() as m:
            m.kernel32.GlobalLock.return_value = 0
            clipboard = clipboard_support.WindowsClipboard()
            self.assertFalse(clipboard.set_content("x"))

        m.kernel32.GlobalFree.assert_called_once_with(0x1000)
        m.user32.CloseClipboard.assert_called_once()

    def test_set_clipboard_data_failure_frees_handle_and_closes(self):
        with _win32_backend() as m:
            m.user32.SetClipboardData.return_value = 0
            clipboard = clipboard_support.WindowsClipboard()
            self.assertFalse(clipboard.set_content("x"))

        m.kernel32.GlobalFree.assert_called_once_with(0x1000)
        m.user32.CloseClipboard.assert_called_once()

    def test_rich_text_writes_unicode_html_and_rtf(self):
        with _win32_backend() as m:
            clipboard = clipboard_support.WindowsClipboard()
            self.assertTrue(clipboard.set_content(_RICH_VALUE))

        formats = [call.args[0] for call in m.user32.SetClipboardData.call_args_list]
        self.assertEqual(3, len(formats))
        self.assertIn(clipboard_support.CF_UNICODETEXT, formats)
        self.assertIn(clipboard_support.CF_HTML, formats)
        self.assertIn(clipboard_support.CF_RTF, formats)
        buffers = [call.args[1] for call in m.memmove.call_args_list]
        self.assertTrue(any(b"Version:0.9" in buffer for buffer in buffers))
        m.user32.CloseClipboard.assert_called_once()

    def test_html_write_failure_mid_sequence_frees_and_closes(self):
        def set_side_effect(clipboard_format, handle):
            return 0 if clipboard_format == clipboard_support.CF_HTML else 1

        with _win32_backend() as m:
            m.user32.SetClipboardData.side_effect = set_side_effect
            clipboard = clipboard_support.WindowsClipboard()
            self.assertFalse(clipboard.set_content(_RICH_VALUE))

        # The unicode write consumed its handle; the failed HTML handle is freed.
        m.kernel32.GlobalFree.assert_called_once_with(0x1000)
        m.user32.CloseClipboard.assert_called_once()


@unittest.skipUnless(clipboard_support.IS_WINDOWS, "needs the Win32 backend")
class WindowsClipboardGetTextTests(unittest.TestCase):
    def test_success_returns_text_and_closes(self):
        with _win32_backend() as m:
            clipboard = clipboard_support.WindowsClipboard()
            self.assertEqual("conteúdo", clipboard.get_text())

        m.kernel32.GlobalUnlock.assert_called_once()
        m.user32.CloseClipboard.assert_called_once()

    def test_open_failure_returns_none_without_closing(self):
        with _win32_backend() as m:
            m.user32.OpenClipboard.return_value = 0
            clipboard = clipboard_support.WindowsClipboard()
            self.assertIsNone(clipboard.get_text())

        m.user32.CloseClipboard.assert_not_called()

    def test_format_unavailable_returns_none_but_closes(self):
        with _win32_backend() as m:
            m.user32.IsClipboardFormatAvailable.return_value = 0
            clipboard = clipboard_support.WindowsClipboard()
            self.assertIsNone(clipboard.get_text())

        m.user32.CloseClipboard.assert_called_once()

    def test_null_data_handle_returns_none_but_closes(self):
        with _win32_backend() as m:
            m.user32.GetClipboardData.return_value = 0
            clipboard = clipboard_support.WindowsClipboard()
            self.assertIsNone(clipboard.get_text())

        m.user32.CloseClipboard.assert_called_once()

    def test_lock_failure_returns_none_but_closes(self):
        with _win32_backend() as m:
            m.kernel32.GlobalLock.return_value = 0
            clipboard = clipboard_support.WindowsClipboard()
            self.assertIsNone(clipboard.get_text())

        m.user32.CloseClipboard.assert_called_once()


if __name__ == "__main__":
    unittest.main()
