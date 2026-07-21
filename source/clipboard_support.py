"""Clipboard backends, selected per OS at import time.

The Win32 ctypes bindings used to be executed at ``runtime_support`` import time,
which made the whole app unimportable off Windows even though clipboard paste is
the only piece that needs Win32. They now live behind :data:`Clipboard`, an
instance of the backend chosen for the running OS, so importing this module on
macOS/Linux never touches ``WinDLL``.

Backends expose the same two-method contract:

``get_text()``      -> the clipboard's plain text, or ``None`` when unavailable.
``set_content(v)``  -> place a snippet value (plain string or rich-text payload)
                       on the clipboard; ``True`` on success.
"""

import logging
import os
import shutil
import subprocess
import time

from platform_support import IS_WINDOWS, IS_MAC
from rich_text_support import get_clipboard_payload


# Same logger tree as runtime_support.LOGGER_NAME; importing it here would make
# the dependency circular (runtime_support imports this module).
_LOGGER = logging.getLogger("txt_xpander")

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_POSIX_TIMEOUT = 5


def _html_clipboard_bytes(fragment):
    """Wrap an HTML fragment in the CF_HTML header Windows expects."""
    start_marker = "<!--StartFragment-->"
    end_marker = "<!--EndFragment-->"
    document = f"<html><body>{start_marker}{fragment}{end_marker}</body></html>"
    header_template = (
        "Version:0.9\r\n"
        "StartHTML:{start_html:010d}\r\n"
        "EndHTML:{end_html:010d}\r\n"
        "StartFragment:{start_fragment:010d}\r\n"
        "EndFragment:{end_fragment:010d}\r\n"
    )
    dummy_header = header_template.format(start_html=0, end_html=0, start_fragment=0, end_fragment=0)
    start_html = len(dummy_header.encode("utf-8"))
    encoded_document = document.encode("utf-8")
    # CF_HTML offsets are byte offsets into the UTF-8 payload, so they must be
    # computed on the encoded document: character offsets drift as soon as the
    # fragment contains a multi-byte character (any accented letter).
    start_marker_bytes = start_marker.encode("utf-8")
    start_fragment = (
        start_html
        + encoded_document.index(start_marker_bytes)
        + len(start_marker_bytes)
    )
    end_fragment = start_html + encoded_document.index(end_marker.encode("utf-8"))
    end_html = start_html + len(encoded_document)
    header = header_template.format(
        start_html=start_html,
        end_html=end_html,
        start_fragment=start_fragment,
        end_fragment=end_fragment,
    )
    return (header + document).encode("utf-8")


# ---------------------------------------------------------------------------
# Windows (ctypes user32/kernel32)
# ---------------------------------------------------------------------------

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    SIZE_T = ctypes.c_size_t
    LPVOID = ctypes.c_void_p
    HANDLE = wintypes.HANDLE
    BOOL = wintypes.BOOL
    UINT = wintypes.UINT
    HWND = wintypes.HWND

    USER32 = ctypes.WinDLL("user32", use_last_error=True)
    KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

    USER32.OpenClipboard.argtypes = [HWND]
    USER32.OpenClipboard.restype = BOOL
    USER32.CloseClipboard.argtypes = []
    USER32.CloseClipboard.restype = BOOL
    USER32.EmptyClipboard.argtypes = []
    USER32.EmptyClipboard.restype = BOOL
    USER32.IsClipboardFormatAvailable.argtypes = [UINT]
    USER32.IsClipboardFormatAvailable.restype = BOOL
    USER32.GetClipboardData.argtypes = [UINT]
    USER32.GetClipboardData.restype = HANDLE
    USER32.SetClipboardData.argtypes = [UINT, HANDLE]
    USER32.SetClipboardData.restype = HANDLE
    USER32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    USER32.RegisterClipboardFormatW.restype = UINT

    KERNEL32.GlobalAlloc.argtypes = [UINT, SIZE_T]
    KERNEL32.GlobalAlloc.restype = HANDLE
    KERNEL32.GlobalLock.argtypes = [HANDLE]
    KERNEL32.GlobalLock.restype = LPVOID
    KERNEL32.GlobalUnlock.argtypes = [HANDLE]
    KERNEL32.GlobalUnlock.restype = BOOL
    KERNEL32.GlobalFree.argtypes = [HANDLE]
    KERNEL32.GlobalFree.restype = HANDLE

    CF_HTML = USER32.RegisterClipboardFormatW("HTML Format")
    CF_RTF = USER32.RegisterClipboardFormatW("Rich Text Format")

    # Defined inside the guard on purpose: every name below is a Win32 binding.
    # A half-defined class off Windows would fail with an obscure NameError at
    # call time instead of simply not existing.

    def _set_clipboard_data(clipboard_format, data, encoding="utf-8"):
        if clipboard_format == CF_UNICODETEXT:
            encoded = (data.replace("\n", "\r\n") + "\0").encode("utf-16-le")
        else:
            payload = data if isinstance(data, bytes) else str(data).encode(encoding)
            encoded = payload + b"\0"

        handle = KERNEL32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
        if not handle:
            return False

        locked = KERNEL32.GlobalLock(handle)
        if not locked:
            KERNEL32.GlobalFree(handle)
            return False

        try:
            ctypes.memmove(locked, encoded, len(encoded))
        finally:
            KERNEL32.GlobalUnlock(handle)

        if not USER32.SetClipboardData(clipboard_format, handle):
            KERNEL32.GlobalFree(handle)
            return False
        return True

    class WindowsClipboard:
        """Clipboard wrapper for text, HTML and RTF payloads on Windows."""

        def _open(self, retries=10, delay=0.02):
            for _ in range(retries):
                if USER32.OpenClipboard(None):
                    return True
                time.sleep(delay)
            return False

        def get_text(self):
            if not self._open():
                return None
            try:
                if not USER32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                    return None
                handle = USER32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return None
                locked = KERNEL32.GlobalLock(handle)
                if not locked:
                    return None
                try:
                    return ctypes.wstring_at(locked)
                finally:
                    KERNEL32.GlobalUnlock(handle)
            finally:
                USER32.CloseClipboard()

        def set_content(self, value):
            payload = get_clipboard_payload(value)
            if not self._open():
                return False
            try:
                if not USER32.EmptyClipboard():
                    return False
                if not _set_clipboard_data(CF_UNICODETEXT, payload["text"]):
                    return False
                html_fragment = payload.get("html")
                if html_fragment and not _set_clipboard_data(CF_HTML, _html_clipboard_bytes(html_fragment), encoding="utf-8"):
                    return False
                rtf_document = payload.get("rtf")
                if rtf_document and not _set_clipboard_data(CF_RTF, rtf_document, encoding="ascii"):
                    return False
                return True
            finally:
                USER32.CloseClipboard()


# ---------------------------------------------------------------------------
# POSIX (macOS pbcopy/pbpaste, Linux wl-clipboard/xclip/xsel)
# ---------------------------------------------------------------------------

def posix_clipboard_commands(environ=None):
    """Return ``(copy_argv, paste_argv)`` for this POSIX desktop, or ``(None, None)``.

    Wayland is preferred over X11 when ``WAYLAND_DISPLAY`` is set and
    ``wl-copy`` is installed; otherwise xclip, then xsel.
    """
    environ = os.environ if environ is None else environ

    if IS_MAC:
        if shutil.which("pbcopy") and shutil.which("pbpaste"):
            return ["pbcopy"], ["pbpaste"]
        return None, None

    if environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy") and shutil.which("wl-paste"):
        return ["wl-copy"], ["wl-paste", "--no-newline"]
    if shutil.which("xclip"):
        return (
            ["xclip", "-selection", "clipboard"],
            ["xclip", "-selection", "clipboard", "-o"],
        )
    if shutil.which("xsel"):
        return ["xsel", "--clipboard", "--input"], ["xsel", "--clipboard", "--output"]
    return None, None


class PosixClipboard:
    """Plain-text clipboard driven by the desktop's CLI tool.

    ceiling: plain text only — HTML/RTF payloads are downgraded to their plain
    text and logged. Bind a native pasteboard/portal API if rich paste is ever
    needed off Windows.
    """

    def __init__(self, environ=None):
        self._environ = environ
        self._copy_argv, self._paste_argv = posix_clipboard_commands(environ)
        self._warned_missing_tool = False
        self._warned_rich_text = False
        if self._copy_argv is None:
            self._warn_missing_tool()

    def _commands(self):
        """Return ``(copy_argv, paste_argv)``, re-resolving while none is available.

        The app sits in the tray for weeks, so a session that started before the
        desktop session (or before the tool was installed) must recover without
        a restart. Once a tool is found the lookup is cached for good.
        """
        if self._copy_argv is None:
            self._copy_argv, self._paste_argv = posix_clipboard_commands(self._environ)
            if self._copy_argv is not None:
                self._warned_missing_tool = False
                _LOGGER.info(f"Área de transferência disponível via {self._copy_argv[0]}.")
        return self._copy_argv, self._paste_argv

    def _warn_missing_tool(self):
        if self._warned_missing_tool:
            return
        self._warned_missing_tool = True
        _LOGGER.warning(
            "Nenhuma ferramenta de área de transferência encontrada "
            "(instale wl-clipboard, xclip ou xsel); a colagem será desativada."
        )

    def get_text(self):
        _, paste_argv = self._commands()
        if paste_argv is None:
            self._warn_missing_tool()
            return None
        try:
            completed = subprocess.run(
                paste_argv,
                capture_output=True,
                timeout=_POSIX_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as error:
            _LOGGER.warning(f"Falha ao ler a área de transferência: {error}")
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.decode("utf-8", errors="replace")

    def set_content(self, value):
        copy_argv, _ = self._commands()
        if copy_argv is None:
            self._warn_missing_tool()
            return False
        payload = get_clipboard_payload(value)
        if (payload.get("html") or payload.get("rtf")) and not self._warned_rich_text:
            # Once per session: a daily-use rich snippet would otherwise write
            # this line on every single paste.
            self._warned_rich_text = True
            _LOGGER.info(
                "Texto formatado não é suportado nesta plataforma; "
                "colando apenas o texto simples."
            )
        try:
            # Never capture the copy tool's output: xclip and wl-copy fork a
            # daemon that owns the selection until it is replaced, and that child
            # inherits the stdout pipe. Reading to EOF would block on the daemon
            # rather than on the command, hanging every paste until the timeout.
            completed = subprocess.run(
                copy_argv,
                input=payload["text"].encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_POSIX_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as error:
            _LOGGER.warning(f"Falha ao escrever na área de transferência: {error}")
            return False
        return completed.returncode == 0


def build_clipboard():
    """Return the clipboard backend for the running OS."""
    if IS_WINDOWS:
        return WindowsClipboard()
    return PosixClipboard()


Clipboard = build_clipboard()
