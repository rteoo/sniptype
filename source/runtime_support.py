import ctypes
import logging
import os
import sys
import threading
import time
from ctypes import wintypes
from logging.handlers import RotatingFileHandler

from rich_text_support import extract_plain_text, get_clipboard_payload


LOGGER_NAME = "txt_xpander"
LOG_FILE_NAME = "txt_xpander.log"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_LOG_MAX_BYTES = 1_000_000
_LOG_BACKUP_COUNT = 3


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
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

# The clipboard is a single OS-global resource and paste is a
# snapshot -> set -> paste -> restore sequence. Serialize it so concurrent
# expansion workers cannot interleave and clobber each other's payload or lose
# the user's original clipboard contents.
_CLIPBOARD_PASTE_LOCK = threading.Lock()


def configure_logging(log_dir=None, level=logging.INFO):
    """Attach file and (dev-only) console handlers to the shared app logger.

    Idempotent: repeated calls do not duplicate handlers. A rotating file
    handler (1 MB x 3) is added when ``log_dir`` is given, so errors survive in
    the windowed/packaged build where stdout is discarded. A console handler is
    added only when a real stdout exists (running from a terminal in dev).
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(_LOG_FORMAT)

    if log_dir:
        log_path = os.path.abspath(os.path.join(log_dir, LOG_FILE_NAME))
        has_file_handler = any(
            isinstance(handler, RotatingFileHandler)
            and os.path.abspath(getattr(handler, "baseFilename", "")) == log_path
            for handler in logger.handlers
        )
        if not has_file_handler:
            # A read-only install dir (e.g. Program Files) must not crash startup:
            # fall through to the console/last-resort handler instead.
            try:
                os.makedirs(log_dir, exist_ok=True)
                file_handler = RotatingFileHandler(
                    log_path,
                    maxBytes=_LOG_MAX_BYTES,
                    backupCount=_LOG_BACKUP_COUNT,
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
            except OSError as error:
                logger.warning(f"Não foi possível criar o log em {log_dir}: {error}")

    stream = getattr(sys, "stdout", None)
    if stream is not None:
        has_stream_handler = any(
            isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, RotatingFileHandler)
            for handler in logger.handlers
        )
        if not has_stream_handler:
            stream_handler = logging.StreamHandler(stream)
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)

    return logger


class AppLogger:
    """Thin wrapper over the shared stdlib logger.

    Output goes to the rotating log file (and the console in dev) once
    ``configure_logging`` has run. Before configuration, records fall through
    to logging's last-resort stderr handler, so nothing is silently dropped.
    """

    def __init__(self, name=LOGGER_NAME):
        self._logger = logging.getLogger(name)

    def info(self, message):
        self._logger.info(message)

    def warning(self, message):
        self._logger.warning(message)

    def error(self, message):
        self._logger.error(message)


class BackgroundTaskRunner:
    """Small thread launcher used for background UI and snippet tasks."""

    def start(self, target, *args, daemon=True, name=None, **kwargs):
        thread = threading.Thread(
            target=target,
            args=args,
            kwargs=kwargs,
            daemon=daemon,
            name=name,
        )
        thread.start()
        return thread


def truncate_notification_text(message, max_length=160):
    """Keep tray messages short and single-line so Windows notifications stay readable."""

    normalized = " ".join(str(message).split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def build_snippet_failure_notification(trigger, value):
    """Return a concise notification message when a snippet result represents a fetch failure."""

    text = extract_plain_text(value).strip()
    if not text or text == "[Cancelado]":
        return None

    lowered = text.lower()
    bracketed = text.startswith("[") and text.endswith("]")
    single_line = "\n" not in text

    if lowered.startswith("[erro"):
        detail = text[1:-1].strip()
        return truncate_notification_text(f"Falha no snippet {trigger}: {detail}")

    if bracketed and ("indispon" in lowered or "falha" in lowered or "n/a" in lowered):
        detail = text[1:-1].strip()
        return truncate_notification_text(f"Falha no snippet {trigger}: {detail}")

    if single_line and lowered.endswith(": n/a"):
        return truncate_notification_text(f"Falha no snippet {trigger}: dado indisponível.")

    return None


def _html_clipboard_bytes(fragment):
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
    start_fragment = start_html + document.index(start_marker) + len(start_marker)
    end_fragment = start_html + document.index(end_marker)
    end_html = start_html + len(encoded_document)
    header = header_template.format(
        start_html=start_html,
        end_html=end_html,
        start_fragment=start_fragment,
        end_fragment=end_fragment,
    )
    return (header + document).encode("utf-8")


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

    @classmethod
    def _open(cls, retries=10, delay=0.02):
        for _ in range(retries):
            if USER32.OpenClipboard(None):
                return True
            time.sleep(delay)
        return False

    @classmethod
    def get_text(cls):
        if not cls._open():
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

    @classmethod
    def set_content(cls, value):
        payload = get_clipboard_payload(value)
        if not cls._open():
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


class TextInserter:
    """Insert snippets through the clipboard, with typed fallback."""

    def __init__(self, keyboard_controller, logger=None, restore_delay=0.12):
        self.keyboard_controller = keyboard_controller
        self.logger = logger or AppLogger()
        self.restore_delay = restore_delay

    def insert_text(self, value):
        plain_text = extract_plain_text(value)
        if self._paste_value(value):
            return True
        self.logger.warning("Falha ao colar snippet; usando digitacao normal.")
        self.keyboard_controller.type(plain_text)
        return True

    def _paste_value(self, value):
        # ceiling: only plain text survives the save/restore round-trip; images, file lists
        # and rich formats on the clipboard are lost on every expansion. Preserve original
        # format handles if that loss starts to hurt (audit 2.7).
        # The lock keeps the snapshot/set/paste/restore atomic across expansion workers.
        with _CLIPBOARD_PASTE_LOCK:
            previous_text = WindowsClipboard.get_text()
            plain_text = extract_plain_text(value)
            if not WindowsClipboard.set_content(value):
                return False

            time.sleep(0.05)
            self._send_paste_shortcut()
            time.sleep(self.restore_delay)

            if previous_text is not None:
                current_text = WindowsClipboard.get_text()
                if current_text is not None and extract_plain_text(current_text) == plain_text:
                    WindowsClipboard.set_content(previous_text)
            return True

    def _send_paste_shortcut(self):
        from pynput.keyboard import Key

        self.keyboard_controller.press(Key.ctrl)
        self.keyboard_controller.press('v')
        self.keyboard_controller.release('v')
        self.keyboard_controller.release(Key.ctrl)


