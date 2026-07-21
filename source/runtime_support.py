import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import json

from clipboard_support import Clipboard
from rich_text_support import extract_plain_text
from snippet_utils import write_json_atomic


LOGGER_NAME = "txt_xpander"
NOTIFICATION_HISTORY_LIMIT = 120


def load_notification_history(path, limit=NOTIFICATION_HISTORY_LIMIT):
    """Load the persisted notification ring, or [] when missing/invalid."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    # Keep only well-formed entries so the history window (which reads dict keys)
    # can't crash on an externally corrupted file.
    return [item for item in data if isinstance(item, dict)][-limit:]


def save_notification_history(path, history, limit=NOTIFICATION_HISTORY_LIMIT):
    """Persist the newest ``limit`` notifications atomically. Best effort."""
    try:
        write_json_atomic(path, history[-limit:])
        return True
    except Exception:
        return False
LOG_FILE_NAME = "txt_xpander.log"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_LOG_MAX_BYTES = 1_000_000
_LOG_BACKUP_COUNT = 3


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
            previous_text = Clipboard.get_text()
            plain_text = extract_plain_text(value)
            if not Clipboard.set_content(value):
                return False

            time.sleep(0.05)
            self._send_paste_shortcut()
            time.sleep(self.restore_delay)

            if previous_text is not None:
                current_text = Clipboard.get_text()
                if current_text is not None and extract_plain_text(current_text) == plain_text:
                    Clipboard.set_content(previous_text)
            return True

    def _send_paste_shortcut(self):
        from pynput.keyboard import Key
        from platform_support import paste_modifier_is_cmd

        modifier = Key.cmd if paste_modifier_is_cmd() else Key.ctrl
        self.keyboard_controller.press(modifier)
        self.keyboard_controller.press('v')
        self.keyboard_controller.release('v')
        self.keyboard_controller.release(modifier)


