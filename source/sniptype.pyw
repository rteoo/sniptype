"""
SnipType - Windows system tray snippet expander.
Version: 1.3.0
Channel: stable

IMPORTANT: This program captures keyboard input only to expand text
snippets (shortcuts). It does not store, transmit, or log keystrokes.
Some explicitly used features make network requests; see README.md.

Libraries used:
- pynput (open source, LGPL)
- pystray (open source, LGPL)
- pillow (open source, PIL License)
- yfinance (open source, Apache 2.0)
"""

import copy
from datetime import datetime
import time
import threading
import gc
import os
import sys
import shutil
import traceback
import types
import ctypes
import webbrowser





import platform_support

# Must run before ``import pystray``: it reads PYSTRAY_BACKEND at import time.
platform_support.pin_tray_backend()

from pynput import keyboard
from pynput.keyboard import Controller, Key
from mouse_input import MouseActivityMonitor
import pystray
from PIL import Image, ImageDraw, ImageTk

from bcb_consultor import BCBConsultor
from yf_stocks import B3FundamentosConsultor
from snippet_utils import (
    build_saveable_snippets,
    calculate_max_trigger_length_with_mappings,
    find_shadowed_statics,
    get_dynamic_prefixes,
    get_default_snippets as get_static_default_snippets,
    library_change_counts,
    load_json_file,
    mapping_types,
    merge_snippets,
    validate_static_snippets,
    write_json_atomic,
    check_dynamic_pattern as resolve_dynamic_pattern,
)
from library_metadata import (
    build_library_document,
    mapping_item_metadata,
    merge_metadata,
    normalize_metadata,
    split_library_document,
    static_item_metadata,
)
from trigger_index import (
    ExpansionTarget,
    compile_trigger_index,
    find_dynamic_trigger,
    target_is_allowed,
)
from clipboard_support import Clipboard
from runtime_support import (
    AppLogger,
    BackgroundTaskRunner,
    TextInserter,
    build_snippet_failure_notification,
    configure_logging,
    load_notification_history,
    save_notification_history,
    truncate_notification_text,
    LOG_FILE_NAME,
    NOTIFICATION_HISTORY_LIMIT,
    notification_stamp,
)
from backup_support import (
    backup_time,
    create_backup,
    list_backups,
    prune_backups,
    quarantine_corrupt_file,
    should_backup_on_startup,
)
from app_paths import (
    ensure_data_dir,
    get_backups_dir,
    get_logs_dir,
    get_settings_path,
    get_snippets_path,
    migrate_snippets,
    needs_migration,
)
from settings_support import load_settings, normalize_runtime_settings, save_settings
from hotkey_support import ACTIONS, HotkeyRouter, display_hotkey, normalize_hotkeys
from workflow_support import SnippetRef, WorkflowState
from validation_support import validate_trigger
import health_support
import i18n
from manager_bridge import MANAGER_UI_SETTING, ManagerBridge, ManagerProcess, find_manager_executable
import macos_permissions
import time_format
import tray_support
import ui_theme
import ui_widgets
import win_input
from i18n import N_, _, lazy
from platform_support import (
    APP_NAME,
    AUTOSTART_ABSENT,
    AUTOSTART_CURRENT,
    AUTOSTART_MANAGED,
    AUTOSTART_STALE,
    IS_MAC,
    IS_WINDOWS,
    acquire_lockfile,
    autostart_target_exists,
    classify_autostart,
    install_autostart,
    insertion_timings,
    invalid_timing_overrides,
    is_msix_packaged,
    open_startup_settings,
    read_autostart_command,
    release_lockfile,
    remove_autostart,
)
from dynamic_registry import (
    build_dynamic_snippets,
    composed_mapping_triggers,
    effective_trigger,
    is_enabled,
    load_registry,
    reference_entries_by_category,
    validate_rename,
)
from group_policy import validate_effective_triggers
from sync_export import (
    EXPORT_FAILED,
    EXPORT_UNAVAILABLE,
    STATE_FILENAME as SYNC_STATE_FILENAME,
    export_bundle_outcome,
)
from whatsapp_support import normalize_phone_number
from whatsapp_runtime_support import ACTION_COMPLETED, execute_whatsapp_action
from rich_text_support import (
    clear_text_styles,
    configure_rich_text_widget,
    extract_plain_text,
    is_rich_text_payload,
    load_value_into_text_widget,
    rebuild_rich_text,
    serialize_text_widget_content,
    toggle_text_style,
)
from variable_support import (
    classify_variable,
    expand_inline,
    find_variable_names,
    resolve_form_variables,
    resolve_inline,
)
from form_support import compile_form, render_form
from form_dialog import FormDialog
from preview_support import resolve_preview
from editor_session import (
    CHANGED as EDITOR_CHANGED,
    EMPTY as EDITOR_EMPTY,
    GONE as EDITOR_GONE,
    MISSING as EDITOR_MISSING,
    NEW as EDITOR_NEW,
    EditorSession,
    mapping_draft_problem,
    mapping_type_key,
    mapping_type_problem,
    static_draft_problem,
    static_trigger_problem,
)
from preview_dialog import PreviewDialogController
from manager_actions import (
    MetadataReadOnlyError,
    assign_item as manager_assign_item,
    create_group as manager_create_group,
    delete_group as manager_delete_group,
    duplicate_static as manager_duplicate_static,
    group_members as manager_group_members,
    rename_static as manager_rename_static,
    restore_group as manager_restore_group,
    restore_mapping_item as manager_restore_mapping_item,
    restore_static as manager_restore_static,
    set_form as manager_set_form,
    set_mapping_form as manager_set_mapping_form,
    toggle_favorite as manager_toggle_favorite,
    toggle_mapping_favorite as manager_toggle_mapping_favorite,
    update_group as manager_update_group,
)
from manager_view_support import (
    FILTER_ALL,
    FILTER_DISABLED,
    FILTER_FAVORITES,
    FILTER_PROBLEMS,
    FILTER_RECENT,
    UNGROUPED_FILTER,
    build_manager_rows,
    filter_manager_rows,
    filter_static_rows,
    find_manager_target,
    format_trigger_pair,
    manager_row_preview,
    search_manager_rows,
    normalize_manager_view,
    geometry_intersects_monitors,
    manager_geometry_for_tk,
)
from gui_support import (
    capture_tree_scroll,
    expanded_tree_rows,
    restore_tree_scroll,
    center_dialog,
    center_on_screen,
    ellipsize_text,
    focus_modal_input,
    iter_filtered_mapping_items,
    layout_wrapping_row,
    SectionSwitcher,
    snippet_row_values,
    split_tree_columns,
)
from gui_thread import GuiThread

# GUI for managing snippets
import tkinter as tk
from tkinter import ttk, filedialog, font as tkfont



def _read_release_metadata():
    """Read the app version and release channel from this module's docstring.

    Derived rather than duplicated: the docstring and installer metadata are
    the two hand-maintained places today, and more constants would be more places
    to forget. The version remains nullable because the sync bundle's
    ``generator.version`` permits that; an absent channel is treated as stable so
    builds from older source trees keep their historical display.
    """
    metadata = {}
    for line in (__doc__ or "").splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"Version", "Channel"}:
            metadata[key.lower()] = value.strip() or None
    channel = metadata.get("channel") or "stable"
    if channel not in {"stable", "beta"}:
        raise ValueError(f"Unsupported release channel: {channel}")
    return metadata.get("version"), channel


APP_VERSION, RELEASE_CHANNEL = _read_release_metadata()
PRODUCT_NAME = APP_NAME


def format_app_version(version, channel="stable"):
    """Return the user-visible app name, version and non-stable channel."""
    if version:
        channel_suffix = f" {channel}" if channel and channel != "stable" else ""
        return f"{PRODUCT_NAME} v{version}{channel_suffix}"
    return _("{PRODUCT_NAME} — versão desconhecida").format(PRODUCT_NAME=PRODUCT_NAME)


APP_DISPLAY_NAME = format_app_version(APP_VERSION, RELEASE_CHANNEL)


APP_MUTEX_NAME = r"Local\SniptypeSingleton"
LEGACY_APP_MUTEX_NAME = r"Local\TxtXpanderSingleton"
APP_MUTEX_HANDLES = []
ERROR_ALREADY_EXISTS = 183
MB_ICONINFORMATION = 0x40
_MISSING = object()

# Extra headroom on the typed-text buffer beyond the longest known trigger, so a
# newly added long mapping item is never truncated out before its index rebuild.
TRIGGER_BUFFER_MARGIN = 8

# Characters that end a word for opt-in terminator-gated expansion.
TERMINATOR_CHARS = frozenset(" \t\n\r.,;:!?)]}\"'")

# Keys that move the caret or change the text before it without typing a
# character, so the buffer no longer describes what precedes the caret. Delete
# is absent on purpose: it removes text after the caret. Insert covers
# Shift+Insert (paste) and Menu opens a context menu that can paste or undo;
# the macOS pynput backend has neither.
BUFFER_RESET_KEYS = frozenset(
    key
    for key in (
        Key.left, Key.right, Key.up, Key.down,
        Key.home, Key.end, Key.page_up, Key.page_down,
        Key.tab, Key.esc,
        getattr(Key, "insert", None), getattr(Key, "menu", None),
    )
    if key is not None
)

# Pixels kept for an editor's formatting toolbar plus its content box.
EDITOR_CONTENT_MIN_HEIGHT = 140

# Display labels for the persisted notification ``kind`` values.
NOTIFICATION_KIND_LABELS = {"error": N_("Erro"), "status": N_("Status"), "info": N_("Info")}

# An open manager checks the Windows app theme this often while the
# appearance is System (see _check_system_appearance). A registry read costs
# microseconds; the delay is how long a theme switch takes to show.
SYSTEM_APPEARANCE_POLL_MS = 3000


def _set_enabled(widget, enabled):
    widget.configure(state=tk.NORMAL if enabled else tk.DISABLED)


def _move_focus_off(widget, fallback):
    """Hand the keyboard focus to ``fallback`` if ``widget``, now disabled, has it."""
    try:
        focused = widget.focus_get()
    except (KeyError, tk.TclError):
        # Focus is in a window Tk made itself, such as a combobox list.
        return
    if focused is widget:
        fallback.focus_set()


def get_runtime_base_dir():
    """Resolve the user-visible app directory for source and frozen builds."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_runtime_resource_dir():
    """Resolve the bundled resource directory for source and frozen builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return get_runtime_base_dir()


def acquire_single_instance_mutex():
    """Keep new and legacy-branded processes from running together."""
    global APP_MUTEX_HANDLES

    acquired = []
    kernel32 = ctypes.windll.kernel32
    for mutex_name in (LEGACY_APP_MUTEX_NAME, APP_MUTEX_NAME):
        mutex_handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not mutex_handle:
            continue
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(mutex_handle)
            for acquired_handle in acquired:
                kernel32.CloseHandle(acquired_handle)
            APP_MUTEX_HANDLES = []
            return False
        acquired.append(mutex_handle)

    APP_MUTEX_HANDLES = acquired
    return True


def show_already_running_message():
    message = _("SnipType já está em execução.")
    if IS_WINDOWS:
        ctypes.windll.user32.MessageBoxW(0, message, PRODUCT_NAME, MB_ICONINFORMATION)
    else:
        print(message)


class Sniptype:
    # Facts the health projection reads (health_support.build_health), recorded
    # where they happen; None means nothing to report. Declared on the class so
    # that anything that runs before ``__init__`` ends, or a headless fixture
    # that skips it, reads "nothing to report".
    # How a corrupt snippets.json came back, until the person replaces the
    # library (restore or import):
    library_recovery = None
    # The last failed save, until a save goes through:
    last_save_error = None
    # The last mirror copy and sync export of this session, each
    # {"ok", "at", "error", "path"}:
    last_mirror = None
    last_sync = None
    # The open manager's status widgets; None while it is closed.
    _manager_status_label = None
    _manager_status_icon = None
    # The InfoBar above the pages (ui_widgets.InfoBar):
    _manager_health = None
    # Redraws the Dados card's copy and export lines:
    _manager_data_refresh = None
    # True while the manager is mapped: routine receipts then go to its
    # status line instead of the tray (see notify). Read from any thread.
    _manager_visible = False

    def __init__(self, snippets_file: str = 'snippets.json'):
        self.keyboard_controller = Controller()
        self.typed_text = ""
        # Foreground window the buffered text was typed into (None off Windows).
        self._buffer_window = None
        # Bumped by the listener on every user keystroke; a slow-route expansion
        # whose dispatch-time value is no longer current must not be pasted.
        self._input_generation = 0
        self.mouse_monitor = MouseActivityMonitor()
        self._buffer_mouse_generation = 0
        # Every newer trigger retires an unfinished older insertion, including
        # fast snippets. Workers never wait for one another on the keyboard hook.
        self._expansion_generation = 0
        # (keystrokes, foreground HWND, clicks, trigger order) on this worker.
        self._expansion_context = threading.local()
        self.expansion_failed = False
        self.last_expansion_time = 0
        self.enabled = True
        # The exception that stopped keyboard capture. Only a restart clears
        # it, so expansion must not claim to be resumable while it is set.
        self.capture_error = None
        self.icon = None
        self.listener = None
        self.logger = AppLogger()
        self.task_runner = BackgroundTaskRunner()
        # One hidden Tk root for the whole process; every window is a Toplevel
        # of it, marshaled onto its thread. Started in run().
        self.gui = GuiThread(logger=self.logger)
        self.manager_window = None
        # The Tauri manager window (opt-in via settings "manager_ui": "tauri").
        self._manager_process = None
        self._manager_process_lock = threading.Lock()
        self._pending_manager_target = None
        self.macos_permission_window = None
        self._manager_notebook = None
        self._manager_status_var = None
        self._manager_toggle_button = None
        # Page path -> the ReceiptLine at the bottom of that page.
        self._manager_receipts = {}
        # Page name -> notebook page, for the InfoBar's actions.
        self._manager_pages = {}
        # Info issues dismissed this session (health ids).
        self._dismissed_health = set()
        self._manager_search_entries = {}
        self._manager_commands = {}
        self._manager_settings_tab = None
        self._manager_settings_sections = None
        self._manager_tab_selectors = {}
        self._manager_preview_controller = None
        # Cached macOS TCC probe. Like the autostart cache, the tray menu only
        # ever reads this: pystray re-evaluates `visible=` on every render and
        # the probe is a TCC round-trip. Empty (all unknown) off macOS.
        self._macos_permission_status = {}
        # List-rebuild callbacks registered by the manager tabs, replayed after
        # a restore/import swaps the whole library out from under them.
        self._manager_refreshers = []
        # The open manager's editors, asked before anything drops their drafts
        # (see _resolve_manager_drafts).
        self._manager_editors = []
        # The pending System-appearance check of the open manager: (window, after id).
        self._manager_appearance_poll = None
        self._manager_views = {}
        self._manager_search_jobs = {}
        self._manager_pending_search = {}
        self._manager_rows_revision = 0
        self._manager_rows_cache = None
        self._last_successful_expansion_at = None
        self._manager_last_expansion_var = None
        # Serializes expansion dialogs; see _run_modal_dialog.
        self._dialog_lock = threading.Lock()
        # Serializes autostart toggles; see _apply_autostart_toggle.
        self._autostart_lock = threading.Lock()
        # Cached autostart classification. Reading the real entry costs a
        # PowerShell round-trip on Windows and pystray re-evaluates `checked=`
        # on every menu render, so the menu only ever reads this.
        self._autostart_state = AUTOSTART_ABSENT
        # Serializes the cooldown check and history read-modify-write in notify():
        # it is called from the listener thread (secure-input, listener errors)
        # and worker threads at once. Held only around in-memory state, never
        # across the disk write or any GUI call, so it cannot deadlock or stall.
        self._notification_lock = threading.Lock()
        self.notification_timestamps = {}
        self.notification_history = []
        self.pending_notifications = []

        # User data lives in a stable per-user dir (~/.sniptype), never inside
        # OneDrive; bundled resources may live in _internal for the frozen build.
        self.base_dir = get_runtime_base_dir()
        self.resource_dir = get_runtime_resource_dir()
        self.data_dir = ensure_data_dir()
        self.legacy_snippets_file = os.path.join(self.base_dir, snippets_file)
        self.snippets_file = get_snippets_path(self.data_dir)
        self.backups_dir = get_backups_dir(self.data_dir)
        self.logs_dir = get_logs_dir(self.data_dir)
        self.settings_file = get_settings_path(self.data_dir)
        self.notification_history_file = os.path.join(self.data_dir, "notifications.json")
        self.notification_history = load_notification_history(self.notification_history_file)
        self.settings, invalid_runtime_settings = normalize_runtime_settings(
            load_settings(self.settings_file)
        )
        self.workflow_state = WorkflowState()
        self.hotkey_router = HotkeyRouter(
            self.settings.get("hotkeys", {}),
            self._dispatch_hotkey_action,
        )
        # Opt-in: expand only after a terminator (space/punctuation). Default off
        # to preserve the existing expand-on-last-character muscle memory.
        self.terminator_mode = self.settings.get("terminator_mode", False)
        i18n.set_language(self.settings.get("language"))
        ui_theme.set_preference(self.settings.get("appearance"))
        ui_theme.set_density(self.settings.get("density"))
        # Clipboard/erase delays: per-OS defaults, overridable per key from
        # settings.json. Resolved once — they are read on the listener thread.
        timings = insertion_timings(self.settings)
        self.erase_key_delay = timings["erase_key_delay"]
        # Windows injects the erase and the paste chord as single atomic
        # SendInput batches; elsewhere pynput sends them key by key.
        self.batch_keyboard = (
            win_input.BatchKeyboard() if platform_support.IS_WINDOWS else None
        )
        self.text_inserter = TextInserter(
            self.keyboard_controller,
            logger=self.logger,
            settle_delay=timings["clipboard_settle_delay"],
            restore_delay=timings["paste_restore_delay"],
            notify=self.notify_error,
            batch_keyboard=self.batch_keyboard,
            still_current=self._expansion_target_is_current,
        )
        configure_logging(self.logs_dir)
        for key, default in invalid_runtime_settings.items():
            self.logger.warning(
                f"settings.json: valor inválido para '{key}'; usando o padrão "
                f"({default!r})."
            )
        for key in invalid_timing_overrides(self.settings):
            self.logger.warning(
                f"settings.json: valor inválido para '{key}'; usando o padrão "
                f"da plataforma ({timings[key]}s)."
            )
        self.migrate_legacy_data()
        self.ensure_seed_snippets_file(snippets_file)
        self.logger.info(f"➡ Diretório de dados: {self.data_dir}")
        self.logger.info(f"➡ Arquivo de snippets configurado para: {self.snippets_file}")
        self.backup_on_startup()

        # Providers for the JSON dynamic-snippet registry. Timeouts/TTLs are
        # configurable via settings.json.
        self.b3_consultor = B3FundamentosConsultor(
            cache_seconds=self.settings.get("stock_cache_seconds", 600)
        )
        self.bcb = BCBConsultor(
            timeout=self.settings.get("bcb_timeout", 3),
            cache_seconds=self.settings.get("bcb_cache_seconds", 300),
        )
        # Dynamic snippets are described in dynamic_snippets.json (bundled), with an
        # optional per-user override in the data dir. slow_snippets is derived from
        # the registry rather than hardcoded.
        self.dynamic_registry_file = os.path.join(self.data_dir, "dynamic_snippets.json")
        self.dynamic_registry = load_registry(
            self.resolve_resource_path("dynamic_snippets.json"),
            self.dynamic_registry_file,
            logger=self.logger,
        )
        self.slow_snippets = set()
        # Static values whose key a dynamic trigger shadows in the merged map;
        # kept so no save can drop them from snippets.json. Set by load_snippets,
        # which itself can save on first run.
        self.shadowed_static_snippets = {}

        # Load snippets before anything else
        self.library_metadata = split_library_document({})[1]
        self.snippets = self.load_snippets()
        self.refresh_runtime_indexes()

    # =====================================================================
    # SNIPPET LOADING AND SAVING
    # =====================================================================

    def is_admin(self):
        """Check whether the program is running as administrator."""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False
    
    def migrate_legacy_data(self):
        """One-time move of a legacy exe-side snippets file into the data dir.

        The legacy file is copied (never moved) so it remains as an extra safety
        copy; a backup and a tray notice follow. Idempotent: a second launch
        finds the data-dir file already present and does nothing.
        """
        if not needs_migration(self.legacy_snippets_file, self.data_dir):
            return
        try:
            migrated = migrate_snippets(self.legacy_snippets_file, self.data_dir)
        except OSError as e:
            self.logger.error(f"⚠ Falha ao migrar dados para {self.data_dir}: {e}")
            return

        self.logger.info(f"✓ Dados migrados de {self.legacy_snippets_file} para {migrated}")
        try:
            if create_backup(self.snippets_file, self.backups_dir):
                prune_backups(self.backups_dir)
        except OSError as e:
            self.logger.warning(f"Falha ao criar backup pós-migração: {e}")
        self.notify_deferred_status(
            _("Dados movidos para {data_dir}. O arquivo antigo foi mantido como cópia.").format(data_dir=self.data_dir),
            key="data-migrated",
        )

    def ensure_seed_snippets_file(self, snippets_file: str):
        """Seed the user-writable snippets file from bundled defaults on first run."""
        if os.path.exists(self.snippets_file):
            return

        bundled_path = os.path.join(self.resource_dir, snippets_file)
        if not os.path.exists(bundled_path):
            return

        try:
            shutil.copyfile(bundled_path, self.snippets_file)
            self.logger.info(f"✓ snippets.json inicial copiado de: {bundled_path}")
        except Exception as e:
            self.logger.warning(f"Falha ao copiar snippets iniciais: {e}")

    def resolve_resource_path(self, filename: str):
        """Prefer bundled resources, falling back to the user-visible app directory."""
        for base in (self.resource_dir, self.base_dir):
            candidate = os.path.join(base, filename)
            if os.path.exists(candidate):
                return candidate
        return None
    
    def load_snippets(self):
        """Load snippets from the JSON file and add the dynamic ones."""
        self.logger.info(f"➡ Usando arquivo de snippets: {os.path.abspath(self.snippets_file)}")

        self.library_metadata = split_library_document({})[1]
        if os.path.exists(self.snippets_file):
            try:
                document = validate_static_snippets(load_json_file(self.snippets_file))
                if document is None:
                    self.logger.warning("⚠ Formato inesperado em snippets.json; tentando restaurar.")
                    document = self.recover_snippets_file("formato inválido")  # i18n: not ui
            except Exception as e:
                self.logger.error(f"⚠ Erro ao carregar snippets: {e}")
                document = self.recover_snippets_file(str(e))
        else:
            self.logger.info("ℹ Primeira execução: criando arquivo de snippets padrão")
            document = self.get_default_snippets()
            self.save_snippets(document)

        static_snippets, metadata = split_library_document(document)
        self.library_metadata = normalize_metadata(
            metadata,
            self._metadata_available_items(static_snippets),
        )
        if self.library_metadata.read_only:
            issue = "malformados" if self.library_metadata.malformed else "de uma versão mais nova"  # i18n: not ui
            self.logger.warning(
                f"⚠ Metadados {issue}; snippets carregados em modo de compatibilidade somente leitura."
            )
            if self.library_metadata.malformed:
                message = _("Os metadados da biblioteca estão malformados. Os snippets continuam "
                            "funcionando, mas grupos, formulários e favoritos não podem ser "
                            "alterados nesta versão.")
            else:
                message = _("Os metadados da biblioteca são de uma versão mais nova. Os snippets "
                            "continuam funcionando, mas grupos, formulários e favoritos não podem "
                            "ser alterados nesta versão.")
            self.notify_error(
                message,
                key="library-metadata-read-only",
                cooldown_seconds=60,
            )
        self.logger.info(f"✓ Snippets carregados do arquivo: {len(static_snippets)} snippets")

        # Add dynamic snippets
        dynamic_snippets = self.get_dynamic_snippets()

        # Merge: JSON snippets + dynamic ones (dynamic take priority)
        all_snippets = merge_snippets(static_snippets, dynamic_snippets)

        # A dynamic trigger sharing a name with a static snippet replaces it in
        # the merged map with a callable; without this the next save would drop
        # the static value from disk with no trace.
        self.shadowed_static_snippets = find_shadowed_statics(static_snippets, dynamic_snippets)
        if self.shadowed_static_snippets:
            names = ", ".join(sorted(self.shadowed_static_snippets))
            self.logger.warning(
                f"⚠ Snippet(s) estático(s) com o mesmo nome de um trigger dinâmico: {names}. "
                "O dinâmico tem prioridade ao digitar; o valor estático continua salvo em snippets.json."
            )
            self.notify_error(
                _("Trigger(s) em conflito com snippets dinâmicos: {names}. O dinâmico é que expande.").format(names=names),
                key="shadowed-static",
                cooldown_seconds=60,
            )

        self.logger.info(f"✓ Total de snippets: {len(all_snippets)} ({len(static_snippets)} estáticos + {len(dynamic_snippets)} dinâmicos)")

        return all_snippets

    def recover_snippets_file(self, reason: str):
        """Quarantine a corrupt snippets file and restore from the newest backup.

        Never overwrites the bad file with defaults: the corrupt copy is renamed
        aside for forensics, the newest backup is restored when one exists, and
        only a truly unrecoverable state falls back to sample defaults.
        """
        quarantined = None
        try:
            quarantined = quarantine_corrupt_file(self.snippets_file)
            self.logger.error(f"⚠ snippets.json corrompido ({reason}); movido para {quarantined}")
        except OSError as e:
            self.logger.error(f"⚠ Não foi possível isolar snippets.json corrompido: {e}")
        recovery = {
            "kind": health_support.SAMPLE_DEFAULTS,
            "at": self._now_iso(),
            "backup_at": None,
            "quarantined": os.path.basename(quarantined) if quarantined else None,
        }

        # Try each backup newest-first; a single unreadable backup must not skip
        # the older valid ones (a corrupt file can be copied into a fresh backup
        # at startup and rank newest by mtime).
        for backup in list_backups(self.backups_dir):
            try:
                data = validate_static_snippets(load_json_file(backup))
            except Exception as e:
                self.logger.error(f"⚠ Backup inválido, tentando o próximo ({backup}): {e}")
                continue
            if data is not None:
                shutil.copyfile(backup, self.snippets_file)
                backup_name = os.path.basename(backup)
                self.logger.info(f"✓ snippets.json restaurado do backup {backup_name}")
                self.library_recovery = {
                    **recovery,
                    "kind": health_support.RECOVERED_FROM_BACKUP,
                    "backup_at": backup_time(backup).isoformat(timespec="seconds"),
                }
                self._library_replaced()
                self.notify_error(
                    _("snippets.json estava corrompido; restaurado do backup {backup_name}.").format(backup_name=backup_name),
                    key="snippets-restored",
                )
                return data

        self.logger.warning("⚠ Sem backup válido; usando snippets de exemplo.")
        self.library_recovery = recovery
        self._library_replaced()
        self.notify_error(
            _("snippets.json estava corrompido e não havia backup; usando snippets de exemplo."),
            key="snippets-restored",
        )
        defaults = self.get_default_snippets()
        self.save_snippets(defaults)
        return defaults

    def get_default_snippets(self):
        """Return default example snippets (static only, for the JSON file)."""
        return get_static_default_snippets()

    def snippets_file_is_valid(self):
        """True when the on-disk snippets file parses to a valid static dict.

        Used to avoid poisoning the backup set with a corrupt file, which could
        otherwise rank newest by mtime and defeat recovery.
        """
        if not os.path.exists(self.snippets_file):
            return False
        try:
            return validate_static_snippets(load_json_file(self.snippets_file)) is not None
        except Exception:
            return False

    def backup_on_startup(self):
        """Take one backup at launch when the newest is missing or older than 24 h."""
        try:
            if should_backup_on_startup(self.backups_dir) and self.snippets_file_is_valid():
                created = create_backup(self.snippets_file, self.backups_dir)
                if created:
                    self.logger.info(f"✓ Backup de inicialização criado: {os.path.basename(created)}")
                    prune_backups(self.backups_dir)
        except OSError as e:
            self.logger.warning(f"Falha ao criar backup de inicialização: {e}")

    def save_snippets(self, snippets: dict, metadata=None) -> bool:
        """Save static snippets to disk, backing up the previous copy first.

        Returns True on success, False on failure. A rotating backup of the
        pre-write file is taken before the atomic replace so no save can lose an
        earlier state.
        """
        saveable = build_saveable_snippets(snippets, self.shadowed_static_snippets)
        metadata_source = self.library_metadata if metadata is None else metadata
        normalized_metadata = normalize_metadata(
            metadata_source,
            self._metadata_available_items(saveable),
        )
        document = build_library_document(saveable, normalized_metadata)
        try:
            # Only back up a valid prior file, so a corrupt on-disk copy can never
            # become the newest backup and defeat recovery.
            if self.snippets_file_is_valid():
                create_backup(self.snippets_file, self.backups_dir)
        except Exception as e:
            self.logger.error(f"Falha ao criar backup antes de salvar: {e}")
            self._record_save_failure(e)
            return False
        try:
            prune_backups(self.backups_dir)
        except OSError as e:
            # The prior library is already safe. Retention cleanup is best-effort
            # and must not turn a successful backup into a failed save.
            self.logger.warning(f"Falha ao remover backups antigos: {e}")

        try:
            write_json_atomic(self.snippets_file, document)
            self.library_metadata = normalized_metadata
            self._invalidate_manager_rows()
            self.logger.info("✓ snippets.json salvo com sucesso.")
        except Exception as e:
            self.logger.error(f"Erro ao salvar snippets: {e}")
            self._record_save_failure(e)
            return False
        if self.last_save_error is not None:
            self.last_save_error = None
            self._request_health_refresh()

        # Mirroring is best-effort redundancy: it must never turn a persisted
        # save into a reported failure, so it runs after the write succeeded.
        self.mirror_snippets_file()
        self.export_sync_bundle()
        return True

    def mirror_snippets_file(self):
        """Copy the saved file to an optional write-only mirror (e.g. a cloud dir).

        Never read back from the mirror; it is redundancy only, so a failure is
        logged but does not fail the save.
        """
        mirror_dir = self.settings.get("mirror_dir")
        if not mirror_dir:
            self._record_mirror(None)
            return
        try:
            os.makedirs(mirror_dir, exist_ok=True)
            shutil.copyfile(self.snippets_file, os.path.join(mirror_dir, "snippets.json"))
        except Exception as e:
            # Broad guard: a bad mirror_dir value (e.g. hand-edited to a non-path)
            # must not disturb the already-successful save.
            self.logger.warning(f"Falha ao espelhar snippets para {mirror_dir}: {e}")
            self._record_mirror({"ok": False, "error": str(e), "path": str(mirror_dir)})
            return
        self._record_mirror({"ok": True, "error": None, "path": str(mirror_dir)})

    def export_sync_bundle(self):
        """Write the compiled mobile bundle when ``sync_export_dir`` is configured.

        Both inputs are re-read from disk rather than taken from ``self``. That is
        not symmetry: ``self.snippets`` holds bound callables and no registry
        metadata, it does not exist yet when ``load_snippets`` saves on first run,
        and it is stale between a restore/import write and the reload that follows.
        ``self.dynamic_registry`` is likewise reassigned only *after* the registry
        writers persist, so reading it here would compile the pre-toggle state.

        Best-effort: any failure logs, is recorded in ``last_sync`` for the
        health projection and returns, never turning a persisted save into a
        reported failure.
        """
        export_dir = self.settings.get("sync_export_dir")
        if not export_dir:
            self._record_sync(None)
            return
        failure = {"ok": False, "path": str(export_dir)}

        try:
            document = validate_static_snippets(load_json_file(self.snippets_file))
        except Exception as e:
            self.logger.warning(f"Bundle de sincronização ignorado: falha ao ler snippets.json ({e}).")
            self._record_sync({**failure, "error": str(e)})
            return
        if document is None:
            self.logger.warning("Bundle de sincronização ignorado: snippets.json com formato inválido.")
            self._record_sync({**failure, "error": _("snippets.json com formato inválido")})
            return
        static_snippets, _metadata = split_library_document(document)

        try:
            registry = load_registry(
                self.resolve_resource_path("dynamic_snippets.json"),
                self.dynamic_registry_file,
                logger=self.logger,
            )
            outcome = export_bundle_outcome(
                static_snippets,
                registry,
                export_dir,
                os.path.join(self.data_dir, SYNC_STATE_FILENAME),
                mirror_dir=self.settings.get("mirror_dir"),
                app_version=APP_VERSION,
                logger=self.logger,
            )
        except Exception as e:
            # Broad guard for the same reason as mirror_snippets_file: a bad
            # hand-edited value must not disturb an already-successful save.
            self.logger.warning(f"Falha ao gerar o bundle de sincronização: {e}")
            self._record_sync({**failure, "error": str(e)})
            return
        if outcome.status == EXPORT_UNAVAILABLE:
            self._record_sync({
                **failure,
                "error": _("a pasta não existe, não é absoluta ou não está acessível"),
            })
        elif outcome.status == EXPORT_FAILED:
            self._record_sync({**failure, "error": outcome.error})
        else:
            self._record_sync({"ok": True, "error": None, "path": str(export_dir)})

    @staticmethod
    def _now_iso():
        return datetime.now().isoformat(timespec="seconds")

    def _record_save_failure(self, error):
        """Remember that the library did not reach disk; health shows it until a save does."""
        self.last_save_error = {"at": self._now_iso(), "error": str(error)}
        self._request_health_refresh()

    def _record_mirror(self, result):
        """Store the outcome of a mirror copy (None: no mirror is configured)."""
        self.last_mirror = None if result is None else {"at": self._now_iso(), **result}
        self._request_health_refresh()

    def _record_sync(self, result):
        """Store the outcome of a sync export (None: no export is configured)."""
        self.last_sync = None if result is None else {"at": self._now_iso(), **result}
        self._request_health_refresh()

    def retry_sync(self):
        """Mirror the library and export the bundle again, as a save does."""
        self.mirror_snippets_file()
        self.export_sync_bundle()

    # =====================================================================
    # BACKUP / RESTORE / EXPORT / IMPORT
    # =====================================================================

    def reload_snippets_from_disk(self):
        """Reload the static library from disk and rebuild runtime indexes."""
        self.snippets = self.load_snippets()
        self.refresh_runtime_indexes()

    def _backup_current_library(self):
        """Back up the current valid file; return False if protection failed."""
        try:
            if self.snippets_file_is_valid() and create_backup(
                self.snippets_file, self.backups_dir, force=True
            ):
                try:
                    prune_backups(self.backups_dir)
                except OSError as e:
                    self.logger.warning(f"Falha ao remover backups antigos: {e}")
            return True
        except Exception as e:
            self.logger.error(f"Falha ao criar backup de segurança: {e}")
            return False

    def backup_now(self):
        """Create an explicit backup on demand. Returns the path, or None."""
        try:
            created = create_backup(self.snippets_file, self.backups_dir, force=True)
            if created:
                prune_backups(self.backups_dir)
                self.logger.info(f"✓ Backup manual criado: {os.path.basename(created)}")
            return created
        except OSError as e:
            self.logger.error(f"Falha ao criar backup manual: {e}")
            return None

    def _read_backup(self, backup_path):
        """Load and check a backup: ``(snippets, None)`` or ``(None, error_message)``."""
        try:
            data = validate_static_snippets(load_json_file(backup_path))
        except Exception as e:
            return None, _("Backup inválido: {error}").format(error=e)
        if data is None:
            return None, _("Backup inválido: formato inesperado.")

        restored_snippets, restored_metadata = split_library_document(data)
        restored_metadata = normalize_metadata(
            restored_metadata,
            self._metadata_available_items(restored_snippets),
        )
        collision_error = self._library_collision_error(
            restored_snippets,
            restored_metadata,
        )
        if collision_error:
            return None, _("Backup inválido: {error}").format(error=collision_error)
        return restored_snippets, None

    def _saved_library(self):
        """The static library as it is on disk: no callables, shadowed statics kept."""
        return build_saveable_snippets(self.snippets, self.shadowed_static_snippets)

    def preview_restore(self, backup_path):
        """What restoring ``backup_path`` changes: ``(counts, None)`` or ``(None, error)``.

        ``counts`` is :func:`snippet_utils.library_change_counts` from the live
        library to the backup.
        """
        restored, error = self._read_backup(backup_path)
        if error:
            return None, error
        return library_change_counts(self._saved_library(), restored), None

    def restore_backup(self, backup_path):
        """Replace the live library with a backup (current file backed up first).

        Returns (ok, error_message).
        """
        _restored, error = self._read_backup(backup_path)
        if error:
            return False, error

        if not self._backup_current_library():
            return False, _("Falha ao criar backup de segurança; restauração cancelada.")
        try:
            shutil.copyfile(backup_path, self.snippets_file)
        except OSError as e:
            return False, _("Falha ao restaurar: {error}").format(error=e)

        self.mirror_snippets_file()
        self.export_sync_bundle()
        self.reload_snippets_from_disk()
        # The person chose the library now in place; a recovery no longer applies.
        self.library_recovery = None
        self._library_replaced()
        return True, None

    def export_library(self, dest_path):
        """Copy the current library to dest_path. Returns (ok, error_message)."""
        try:
            shutil.copyfile(self.snippets_file, dest_path)
            return True, None
        except OSError as e:
            return False, str(e)

    def read_import_source(self, src_path):
        """Load a library file to import: ``(document, None)`` or ``(None, error_message)``.

        The document is ``(snippets, metadata)``; hand it to :meth:`apply_import`.
        """
        try:
            data = validate_static_snippets(load_json_file(src_path))
        except Exception as e:
            return None, _("Arquivo inválido: {error}").format(error=e)
        if data is None:
            return None, _("Arquivo inválido: o JSON precisa ser um objeto.")
        return split_library_document(data), None

    def _imported_snippets(self, imported_snippets, mode):
        """The static library an import in ``mode`` leaves, before metadata."""
        if mode == "merge":
            return {**self._saved_library(), **imported_snippets}
        return imported_snippets

    def import_change_counts(self, document):
        """``{mode: counts}`` for both import modes of a :meth:`read_import_source` document."""
        current = self._saved_library()
        return {
            mode: library_change_counts(current, self._imported_snippets(document[0], mode))
            for mode in ("merge", "replace")
        }

    def import_library(self, src_path, mode="replace"):
        """Import a library file (mode 'replace' or 'merge').

        Validates the source is a JSON object, backs up the current library,
        applies the change, mirrors and reloads. Returns (ok, error_message).
        """
        document, error = self.read_import_source(src_path)
        if error:
            return False, error
        return self.apply_import(document, mode)

    def apply_import(self, document, mode):
        """Apply a :meth:`read_import_source` document; see :meth:`import_library`."""
        imported_snippets, imported_metadata = document
        merged = self._imported_snippets(imported_snippets, mode)
        if mode == "merge":
            try:
                merged_metadata = merge_metadata(
                    self.library_metadata,
                    imported_metadata,
                    {
                        "mode": "merge",
                        "imported_items": self._imported_metadata_winners(imported_snippets),
                    },
                )
            except ValueError as e:
                return False, _("Falha ao importar metadados: {error}").format(error=e)
        else:
            merged_metadata = imported_metadata

        merged_metadata = normalize_metadata(
            merged_metadata,
            self._metadata_available_items(merged),
        )
        collision_error = self._library_collision_error(merged, merged_metadata)
        if collision_error:
            return False, _("Falha ao importar: {error}").format(error=collision_error)

        if not self._backup_current_library():
            return False, _("Falha ao criar backup de segurança; importação cancelada.")
        document = build_library_document(merged, merged_metadata)

        try:
            write_json_atomic(self.snippets_file, document)
        except Exception as e:
            return False, _("Falha ao importar: {error}").format(error=e)

        self.mirror_snippets_file()
        self.export_sync_bundle()
        self.reload_snippets_from_disk()
        # The person chose the library now in place; a recovery no longer applies.
        self.library_recovery = None
        self._library_replaced()
        return True, None

    @staticmethod
    def _metadata_available_items(imported_snippets):
        """Return static and nested mapping keys whose imported content wins."""
        static = set()
        mappings = {}
        for key, value in imported_snippets.items():
            if key.startswith("_") and isinstance(value, dict):
                mappings[key] = {item for item in value if item != "__prefix__"}
            else:
                static.add(key)
        return {"static": static, "mappings": mappings}

    _imported_metadata_winners = _metadata_available_items

    @staticmethod
    def _library_collision_error(snippets, metadata):
        """Describe exact static effective-trigger collisions, if any."""
        collisions = validate_effective_triggers(snippets, metadata)["collisions"]
        if not collisions:
            return None
        details = "; ".join(
            f"'{trigger}' ({', '.join(stored_keys)})"
            for trigger, stored_keys in collisions
        )
        return f"conflito de triggers efetivos: {details}."

    def open_data_folder(self):
        """Open the user data directory in the OS file manager."""
        self._open_in_shell(self.data_dir, make_dir=True)

    def open_log(self):
        """Open the app log, or its folder when no log has been written yet."""
        path = os.path.join(self.logs_dir, LOG_FILE_NAME)
        if os.path.exists(path):
            self._open_in_shell(path)
        else:
            self._open_in_shell(self.logs_dir, make_dir=True)

    def _open_in_shell(self, path, *, make_dir=False):
        """Open a file or folder with the OS; a failure is logged and told, never silent.

        ``make_dir`` creates our own folder first. A folder the person
        configured (a mirror) is never created: a typo would make one.
        """
        try:
            if make_dir:
                os.makedirs(path, exist_ok=True)
            # ceiling: Windows-only shell open; a platform adapter replaces this in
            # the cross-platform phase (audit §6). Broad guard so a click never
            # raises out of the GUI/tray callback on other OSes.
            os.startfile(path)  # noqa: WPS421
        except Exception as e:
            self.logger.error(f"Falha ao abrir {path}: {e}")
            self.notify_error(_("Não foi possível abrir a pasta ou o arquivo."), key="open-shell")

    # =====================================================================
    # DATE / TEXT / INPUT UTILITIES
    # =====================================================================

    def data_extenso(self):
        """Return the date written out in Portuguese."""
        dias = ['segunda-feira', 'terça-feira', 'quarta-feira',  # i18n: not ui
                'quinta-feira', 'sexta-feira', 'sábado', 'domingo']  # i18n: not ui
        meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',  # i18n: not ui
                 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
        
        now = time.localtime()
        dia_semana = dias[now.tm_wday]
        dia = now.tm_mday
        mes = meses[now.tm_mon - 1]
        ano = now.tm_year
        
        return f"{dia_semana}, {dia:02d} de {mes} de {ano}"
    
    def _run_modal_dialog(self, build, on_busy, busy_message):
        """Run one modal dialog at a time on the GUI thread.

        The listener keeps running while a dialog is open, so a second trigger
        can arrive mid-dialog. Stacking them is not safe: each dialog blocks its
        worker inside a nested event loop, and those unwind strictly LIFO — if
        the user answers the older dialog first, its caller stays blocked and
        its result is lost. So a second dialog is refused rather than stacked,
        and the caller reports it exactly like a cancel: nothing inserted, no
        terminator re-emitted.
        """
        if not self._dialog_lock.acquire(blocking=False):
            self.logger.info(f"Diálogo ignorado, outro já está aberto: {busy_message}")
            self.notify_status(
                _("Outro diálogo já está aberto; conclua-o primeiro."),
                key="dialog-busy",
            )
            return on_busy
        try:
            restore_state = {}

            def build_and_restore_focus(root):
                if platform_support.IS_WINDOWS:
                    target = platform_support.capture_text_target()
                    if target is None:
                        raise RuntimeError(
                            "Could not capture the foreground text target"
                        )
                    restore_state["target"] = target
                    return build(root)

                target_app = platform_support.capture_frontmost_application()
                try:
                    return build(root)
                finally:
                    restored = threading.Event()
                    errors = []

                    def restore_failed(message):
                        errors.append(message)
                        restored.set()

                    cancel = platform_support.restore_application_when_ready(
                        target_app,
                        restored.set,
                        restore_failed,
                    )
                    restore_state.update(
                        event=restored,
                        errors=errors,
                        cancel=cancel,
                    )

            def wait_for_focus_restore():
                if platform_support.IS_WINDOWS:
                    target = restore_state.get("target")
                    if target is None:
                        return
                    if not platform_support.restore_text_target(target):
                        raise RuntimeError(
                            "Could not restore focus to the foreground text target"
                        )
                    return

                event = restore_state.get("event")
                if event is None:
                    return
                cancel = restore_state["cancel"]
                try:
                    if not event.wait(
                        platform_support.APPLICATION_ACTIVATION_TIMEOUT_SECONDS
                    ):
                        raise RuntimeError(
                            "Timed out returning focus to the previous application"
                        )
                    if restore_state["errors"]:
                        raise RuntimeError(restore_state["errors"][0])
                finally:
                    cancel()

            try:
                result = self.gui.call(build_and_restore_focus)
            except BaseException:
                try:
                    wait_for_focus_restore()
                except Exception as focus_error:
                    self.logger.error(
                        f"Erro ao restaurar foco após falha do diálogo: {focus_error}"
                    )
                raise

            # This wait runs on the expansion worker, never on Tk/AppKit's main
            # thread. Cmd+V cannot race ahead of the target application's native
            # activation notification.
            wait_for_focus_restore()
            self._rebaseline_expansion_context()
            return result
        finally:
            self._dialog_lock.release()

    def ask_ticker_input(self, prompt_title: str):
        """Ask for a ticker symbol in a modal dialog. Worker-thread only.

        Returns the upper-cased ticker, or None when the user cancels or
        submits an empty value.
        """
        print(f"📊 Abrindo input para {prompt_title}...")

        def build(root):
            ui = ui_theme.bind(root)
            result = [None]

            dialog = tk.Toplevel(root)
            dialog.withdraw()
            dialog.title(_(prompt_title))
            dialog.resizable(False, False)
            dialog.configure(bg=ui.surface)
            self._set_window_icon(dialog)
            ui_theme.prepare_window(dialog, ui)

            container = tk.Frame(dialog, bg=ui.surface, padx=18, pady=18)
            container.pack(fill=tk.BOTH, expand=True)

            tk.Label(
                container,
                text=_("Digite o ticker:"),
                font=ui.font(10, "bold"),
                bg=ui.surface,
                fg=ui.text,
            ).pack(anchor="w")
            tk.Label(
                container,
                text=_("Ex: PETR4, AAPL, MSFT"),
                font=ui.caption_font(),
                bg=ui.surface,
                fg=ui.text_muted,
            ).pack(anchor="w", pady=(2, 8))

            entry = ui_widgets.entry(container, width=28)
            entry.pack(fill=tk.X, pady=(0, 12))

            buttons = tk.Frame(container, bg=ui.surface)
            buttons.pack(fill=tk.X)

            def on_cancel(_event=None):
                dialog.destroy()  # result stays None

            def on_ok(_event=None):
                ticker = entry.get().strip().upper()
                result[0] = ticker or None
                dialog.destroy()

            ui_widgets.button(buttons, text=_("Cancelar"), width=10, command=on_cancel).pack(side=tk.RIGHT, padx=(6, 0))
            ui_widgets.button(buttons, text=_("OK"), width=10, command=on_ok, variant="accent").pack(side=tk.RIGHT)

            entry.bind("<Return>", on_ok)
            dialog.bind("<Escape>", on_cancel)
            dialog.protocol("WM_DELETE_WINDOW", on_cancel)

            # No grab_set — see _show_form_dialog: _run_modal_dialog already
            # serializes expansion dialogs, and every window shares one root
            # now, so a grab would also freeze the manager window.
            center_on_screen(dialog)
            cancel_activation = focus_modal_input(dialog, entry, self.gui.submit)
            try:
                dialog.wait_window(dialog)
            finally:
                cancel_activation()
            return result[0]

        try:
            ticker = self._run_modal_dialog(build, None, f"ticker ({prompt_title})")
        except Exception as e:
            self.logger.error(f"Erro no diálogo de ticker: {e}")
            self.notify_error(
                _("Erro ao abrir diálogo de ticker: {e}").format(e=e),
                key="ticker-dialog-error",
                cooldown_seconds=5,
            )
            return None

        if ticker:
            print(f"✓ Ticker digitado: {ticker}")
        else:
            print("⚠ Cancelado ou vazio")
        return ticker

    def ask_whatsapp_input(self, initial_phone: str = "", initial_message: str = ""):
        """Show a small modal dialog for manual WhatsApp phone/message input.

        Worker-thread only: the dialog is built on the shared GUI thread and
        this call blocks until the user submits or cancels.
        """
        def build(root):
            ui = ui_theme.bind(root)
            result = {"phone": None, "message": None}

            dialog = tk.Toplevel(root)
            dialog.withdraw()
            dialog.title(_("Abrir WhatsApp"))
            dialog.resizable(False, False)
            dialog.configure(bg=ui.surface)
            self._set_window_icon(dialog)
            ui_theme.prepare_window(dialog, ui)

            container = tk.Frame(dialog, bg=ui.surface, padx=18, pady=18)
            container.pack(fill=tk.BOTH, expand=True)
            container.grid_columnconfigure(0, weight=1)

            tk.Label(
                container,
                text=_("Abrir conversa no WhatsApp"),
                font=ui.subtitle_font(),
                bg=ui.surface,
                fg=ui.text,
            ).grid(row=0, column=0, sticky="w")

            tk.Label(
                container,
                text=_("Informe o telefone com DDD ou código do país. Se faltar o país, será usado +55."),
                font=ui.caption_font(),
                bg=ui.surface,
                fg=ui.text_muted,
                wraplength=380,
                justify=tk.LEFT,
            ).grid(row=1, column=0, sticky="w", pady=(6, 12))

            tk.Label(container, text=_("Telefone"), font=ui.font(), bg=ui.surface, fg=ui.text_native).grid(row=2, column=0, sticky="w")
            entry_phone = ui_widgets.entry(container, width=42)
            entry_phone.grid(row=3, column=0, sticky="ew", pady=(4, 0))
            if initial_phone:
                entry_phone.insert(0, initial_phone)
            phone_error = tk.Label(
                container, text="", font=ui.caption_font(), bg=ui.surface, fg=ui.danger,
                anchor="w", justify=tk.LEFT, wraplength=380,
            )
            phone_error.grid(row=4, column=0, sticky="ew", pady=(2, 6))

            tk.Label(container, text=_("Mensagem"), font=ui.font(), bg=ui.surface, fg=ui.text_native).grid(row=5, column=0, sticky="w")
            message_field, text_message = ui_widgets.text_area(
                container, width=42, height=5, padx=ui.space_sm, pady=ui.space_xs,
            )
            message_field.grid(row=6, column=0, sticky="ew", pady=(4, 12))
            if initial_message:
                text_message.insert("1.0", initial_message)

            def cancel_dialog():
                dialog.destroy()  # result stays empty

            def submit_dialog():
                phone_text = entry_phone.get().strip()
                message_text = text_message.get("1.0", tk.END).rstrip("\n")
                normalized_phone = normalize_phone_number(phone_text)

                if not normalized_phone:
                    phone_error.configure(
                        text=_("Informe um telefone com DDD ou código do país em um formato válido."))
                    entry_phone.focus_set()
                    return

                result["phone"] = normalized_phone
                result["message"] = message_text
                dialog.destroy()

            ui_widgets.dialog_footer(
                container, (_("Abrir WhatsApp"), submit_dialog), cancel_dialog, ui=ui,
            ).grid(row=7, column=0, sticky="ew")
            dialog.protocol("WM_DELETE_WINDOW", cancel_dialog)

            # No grab_set — see _show_form_dialog. The pre-refactor grab was
            # local to this dialog's own Tcl interpreter; on the shared root it
            # would freeze the manager window too.
            center_on_screen(dialog, vertical_divisor=3)
            cancel_activation = focus_modal_input(
                dialog,
                entry_phone,
                self.gui.submit,
            )
            try:
                dialog.wait_window(dialog)
            finally:
                cancel_activation()
            return result["phone"], result["message"]

        try:
            return self._run_modal_dialog(build, (None, None), "whatsapp")
        except Exception as e:
            self.logger.error(f"Erro ao abrir diálogo do WhatsApp: {e}")
            self.notify_error(
                _("Erro ao abrir diálogo do WhatsApp: {e}").format(e=e),
                key="whatsapp-dialog-error",
                cooldown_seconds=5,
            )
            return None, None

    def open_url_in_browser(self, url: str):
        """Open a URL with webbrowser and fall back to os.startfile on Windows."""
        errors = []

        try:
            if webbrowser.open(url, new=2):
                return True, None
            errors.append("webbrowser.open retornou False")
        except Exception as exc:
            errors.append(f"webbrowser.open falhou: {exc}")

        try:
            os.startfile(url)
            return True, None
        except Exception as exc:
            errors.append(f"os.startfile falhou: {exc}")

        return False, "; ".join(errors)

    # =====================================================================
    # DYNAMIC SNIPPETS (dates, BCB, stocks)
    # =====================================================================

    def get_dynamic_snippets(self):
        """Bind the JSON dynamic-snippet registry to provider callables.

        The set of slow triggers is derived from the registry (never hardcoded),
        so adding or disabling a trigger is a data change, not a code change.
        """
        snippets, slow_triggers, identities = build_dynamic_snippets(
            self.dynamic_registry,
            self,
            logger=self.logger,
            include_identities=True,
        )
        self.slow_snippets = slow_triggers
        self.dynamic_identities = identities
        return snippets

    # =====================================================================
    # WHATSAPP ACTION (bound by the 'whatsapp' provider)
    # =====================================================================

    def run_whatsapp_action(self, trigger: str):
        """Execute one of the built-in WhatsApp actions."""
        return execute_whatsapp_action(
            trigger,
            get_clipboard_text=Clipboard.get_text,
            ask_input=self.ask_whatsapp_input,
            set_clipboard_content=Clipboard.set_content,
            open_url=self.open_url_in_browser,
            notify_error=self.notify_error,
        )

    # =====================================================================
    # SPECIAL PATTERNS (cnpj/cpf/cge)
    # =====================================================================

    def check_dynamic_pattern(self, text: str):
        """Check whether the text matches a dynamic pattern (cnpj/cpf/cge/custom)."""
        return resolve_dynamic_pattern(self.snippets, text)

    # =====================================================================
    # SNIPPET EXPANSION
    # =====================================================================

    def expand_snippet(self, trigger: str):
        """Produce and insert a non-slow snippet (callable, plain, or dynamic).

        Runs on a worker thread; the typed trigger has already been erased by the
        listener, so this method does not touch the keyboard buffer itself.
        """
        if not self.enabled:
            return False

        # Slow snippets are not run here (they go through the dialog/fetch path)
        if trigger in self.trigger_index["slow_triggers"]:
            return False
            
        snippet = None
        is_callable_snippet = False
        
        if trigger in self.snippets:
            snippet = self.snippets[trigger]
            if callable(snippet):
                is_callable_snippet = True
                snippet = snippet()
        else:
            snippet, _prefix = self.check_dynamic_pattern(trigger)
        
        if snippet is ACTION_COMPLETED:
            return ACTION_COMPLETED

        if snippet is not None:
            if is_callable_snippet:
                self.notify_snippet_failure(trigger, snippet)

            # Resolve inline variables (clipboard + snippet refs) before inserting.
            plain_text = extract_plain_text(snippet)
            resolved_text = resolve_inline(
                plain_text,
                self.snippets,
                Clipboard.get_text,
                _seen={trigger},
                prefixes=self.trigger_index["dynamic_prefixes"],
                notify_failure=self.notify_snippet_failure,
            )
            if resolved_text != plain_text:
                if is_rich_text_payload(snippet):
                    snippet = rebuild_rich_text(snippet, resolved_text)
                else:
                    snippet = resolved_text

            try:
                time.sleep(0.05)
                inserted = self.text_inserter.insert_text(snippet)
                if inserted is False:
                    return False

                self.expansion_failed = False
                self.last_expansion_time = time.time()
                return True

            except Exception as e:
                current_time = time.time()
                if not self.expansion_failed or (current_time - self.last_expansion_time) > 5:
                    print(f"\n⚠️  AVISO: Não foi possível expandir o snippet!")
                    print(f"   Motivo: {str(e)}")
                    print(f"   Solução: Execute como administrador ou use em aplicativos normais\n")
                    self.notify_error(
                        _("Falha ao expandir snippet {trigger}: {e}").format(trigger=trigger, e=e),
                        key=f"expand-error:{trigger}",
                        cooldown_seconds=5,
                    )
                    self.expansion_failed = True
                    self.last_expansion_time = current_time
                return False
        return False

    def run_slow_snippet(self, trigger: str):
        """
        Run 'heavy' snippets (stocks) in a separate thread:
        - open a popup
        - fetch the data
        - type the result
        Also handles direct and mapping snippets with form-fill variables
        (%%campo%%).
        """
        try:
            if trigger in self.snippets:
                func = self.snippets[trigger]
            else:
                func, _prefix = self.check_dynamic_pattern(trigger)
            if func is None:
                return False

            if not callable(func):
                # Non-callable snippet routed here because it has form-fill variables.
                raw = func
                plain = extract_plain_text(raw)
                prefixes = self.trigger_index["dynamic_prefixes"]
                # Clipboard text and dynamic output stay out of ``plain`` until
                # the final render, so a %%token%% inside them is never
                # mistaken for a form field.
                plain, inline_values = expand_inline(
                    plain,
                    self.snippets,
                    Clipboard.get_text,
                    _seen={trigger},
                    prefixes=prefixes,
                    notify_failure=self.notify_snippet_failure,
                )
                form_names = [
                    n for n in find_variable_names(plain)
                    if classify_variable(n, self.snippets, prefixes) == "form_field"
                ]
                form_data = {}
                form_metadata = self._form_metadata_for_trigger(trigger)
                compiled_form = None
                if form_metadata is not None:
                    compiled_form = compile_form(
                        plain,
                        form_metadata.get("fields", []),
                        self.snippets,
                    )
                    form_names = list(compiled_form.field_names)
                if form_names:
                    if compiled_form is None:
                        form_data = self._show_form_dialog(form_names)
                    else:
                        form_data = self._show_form_dialog(form_names, compiled_form)
                    if form_data is None:
                        return False  # user cancelled — nothing inserted
                result = (
                    render_form(compiled_form, form_data, inline_values)
                    if compiled_form is not None
                    else resolve_form_variables(plain, form_data, inline_values)
                )
                if is_rich_text_payload(raw):
                    result = rebuild_rich_text(raw, result)
                time.sleep(0.05)
                inserted = self.text_inserter.insert_text(result)
                return inserted is not False

            result = func()
            if result is ACTION_COMPLETED:
                return ACTION_COMPLETED
            if not result:
                return False
            self.notify_snippet_failure(trigger, result)
            time.sleep(0.05)
            inserted = self.text_inserter.insert_text(result)
            if inserted is False:
                return False
            if self._is_whatsapp_insert_trigger(trigger):
                Clipboard.set_content(result)
            return True
        except Exception as e:
            self.logger.error(f"Erro ao executar snippet lento {trigger}: {e}")
            self.notify_error(
                _("Falha ao executar snippet {trigger}: {e}").format(trigger=trigger, e=e),
                key=f"slow-snippet-error:{trigger}",
                cooldown_seconds=5,
            )
            return False

    def _is_whatsapp_insert_trigger(self, trigger):
        """Recognize the insert-link action after a registry trigger rename."""
        identities = getattr(self, "dynamic_identities", {})
        stable_key = identities.get(trigger) if isinstance(identities, dict) else None
        registry = getattr(self, "dynamic_registry", {})
        if stable_key is None:
            stable_key = next(
                (
                    key for key, entry in registry.items()
                    if is_enabled(entry, key=key)
                    and effective_trigger(key, entry) == trigger
                ),
                None,
            )
        entry = registry.get(stable_key) if stable_key is not None else None
        return (
            isinstance(entry, dict)
            and entry.get("provider") == "whatsapp"
            and entry.get("mode") == "insert"
        )
    
    def _show_form_dialog(self, field_names, compiled_form=None):
        """
        Show a modal dialog for form-fill variables.
        Called from a worker thread; the dialog is built on the shared GUI
        thread and this call blocks until it closes.
        ``compiled_form`` selects the structured field controls.  Omitting it
        preserves the legacy one-entry-per-name behavior used by old callers.
        Returns {field_name: value} or None if the user cancels.
        """
        if compiled_form is not None:
            def build_structured(root):
                form_dialog = FormDialog(root, compiled_form)
                dialog = form_dialog.window
                dialog.withdraw()
                self._set_window_icon(dialog)
                center_on_screen(dialog)
                first_control = form_dialog._controls.get(field_names[0]) if field_names else None
                cancel_activation = focus_modal_input(
                    dialog,
                    first_control,
                    self.gui.submit,
                )
                try:
                    dialog.wait_window(dialog)
                finally:
                    cancel_activation()
                return form_dialog.controller.result

            try:
                return self._run_modal_dialog(
                    build_structured,
                    None,
                    f"campos ({', '.join(field_names)})",  # i18n: not ui
                )
            except Exception as e:
                self.logger.error(f"Erro no diálogo estruturado de campos: {e}")
                self.notify_error(
                    _("Erro ao abrir diálogo de campos: {e}").format(e=e),
                    key="form-dialog-error",
                    cooldown_seconds=5,
                )
                return None

        def build(root):
            ui = ui_theme.bind(root)
            result = [None]
            entries = {}

            dialog = tk.Toplevel(root)
            dialog.withdraw()
            dialog.title(_("Preencher campos"))
            dialog.resizable(False, False)
            dialog.configure(bg=ui.surface)
            self._set_window_icon(dialog)
            ui_theme.prepare_window(dialog, ui)

            tk.Label(
                dialog,
                text=_("Preencha os campos do snippet:"),
                font=ui.subtitle_font(),
                bg=ui.surface,
                fg=ui.text,
            ).pack(padx=20, pady=(16, 8), anchor="w")

            frame = tk.Frame(dialog, bg=ui.surface)
            frame.pack(fill=tk.BOTH, padx=20, pady=(0, 8))
            frame.grid_columnconfigure(0, weight=1)

            first_entry = None
            for i, name in enumerate(field_names):
                label_text = name.replace("_", " ").title()
                tk.Label(
                    frame,
                    text=label_text + ":",
                    font=ui.font(),
                    bg=ui.surface,
                    fg=ui.text_strong,
                ).grid(row=i * 2, column=0, sticky="w", pady=(6, 0))
                entry = ui_widgets.entry(frame, width=42)
                entry.grid(row=i * 2 + 1, column=0, sticky="ew", pady=(4, 0))
                entries[name] = entry
                if first_entry is None:
                    first_entry = entry

            btn_frame = tk.Frame(dialog, bg=ui.surface)
            btn_frame.pack(fill=tk.X, padx=20, pady=(12, 16))

            def on_ok(_event=None):
                result[0] = {name: entries[name].get() for name in field_names}
                dialog.destroy()

            def on_cancel(_event=None):
                dialog.destroy()  # result[0] stays None

            ui_widgets.button(
                btn_frame, text=_("Cancelar"), width=10, command=on_cancel,
            ).pack(side=tk.RIGHT, padx=(6, 0))
            ui_widgets.button(
                btn_frame, text=_("OK"), width=10, command=on_ok, variant="accent",
            ).pack(side=tk.RIGHT)

            dialog.bind("<Return>", on_ok)
            dialog.bind("<Escape>", on_cancel)
            dialog.protocol("WM_DELETE_WINDOW", on_cancel)

            # No grab_set: _run_modal_dialog serializes expansion dialogs, so a
            # grab adds no modality — and with every window on the shared root
            # it would freeze the manager window while the form is open.
            center_on_screen(dialog)
            cancel_activation = focus_modal_input(
                dialog,
                first_entry,
                self.gui.submit,
            )
            try:
                dialog.wait_window(dialog)
            finally:
                cancel_activation()
            return result[0]

        try:
            return self._run_modal_dialog(build, None, f"campos ({', '.join(field_names)})")  # i18n: not ui
        except Exception as e:
            self.logger.error(f"Erro no diálogo de campos: {e}")
            self.notify_error(
                _("Erro ao abrir diálogo de campos: {e}").format(e=e),
                key="form-dialog-error",
                cooldown_seconds=5,
            )
            return None

    def rebuild_trigger_index(self):
        """Rebuild compiled trigger metadata after snippet changes."""
        dynamic_identities = dict(getattr(self, "dynamic_identities", {}))
        # Compatibility for tests/custom embedders that replace the registry
        # directly instead of going through ``load_snippets``. Supported reload
        # paths already carry the exact binder winner in ``dynamic_identities``.
        for stable_key, entry in self.dynamic_registry.items():
            if not isinstance(stable_key, str) or not isinstance(entry, dict):
                continue
            trigger = effective_trigger(stable_key, entry)
            if trigger not in dynamic_identities and callable(self.snippets.get(trigger)):
                dynamic_identities[trigger] = stable_key
        self.trigger_index = compile_trigger_index(
            self.snippets,
            self.slow_snippets,
            metadata=self.library_metadata,
            terminator_mode=self.terminator_mode,
            dynamic_identities=dynamic_identities,
        )

    def _validate_trigger_warnings(self, trigger):
        """Return save-time warnings for a proposed static trigger."""
        static_triggers = {
            key for key, value in self.snippets.items()
            if not key.startswith("_") and not callable(value)
        }
        composed = composed_mapping_triggers(self.snippets)
        # Mapping entries remain in the ordinary trigger set for prefix/suffix
        # warnings. They are not runtime callables in ``self.snippets``: a
        # direct static entry wins an exact collision, so the generic dynamic
        # warning (which claims dynamic priority) would be false here.
        dynamic_names = {key for key, value in self.snippets.items() if callable(value)}
        existing = (static_triggers - {trigger}) | composed
        warnings = validate_trigger(trigger, existing, dynamic_names)
        if trigger in composed:
            warnings.insert(
                0,
                _("Já existe um mapeamento dinâmico com o trigger '{trigger}'; o snippet "
                  "estático tem prioridade e o item mapeado não será acionado.").format(trigger=trigger),
            )
        return warnings

    def refresh_runtime_indexes(self):
        """Refresh max trigger length and compiled trigger metadata.

        The buffer is always sized to include composed dynamic mapping triggers
        (prefix + item name) plus a small safety margin, so a long mapping item
        can never be truncated out of the typed-text buffer and fail to match.
        """
        self._invalidate_manager_rows()
        self.rebuild_trigger_index()
        direct_max = max(
            (len(target.effective_trigger) for target in self.trigger_index["direct_targets"]),
            default=0,
        )
        self.max_trigger_length = max(
            calculate_max_trigger_length_with_mappings(self.snippets),
            direct_max,
        ) + TRIGGER_BUFFER_MARGIN

    def _store_static_snippet(self, trigger, value):
        """Apply a static-editor save to the in-memory maps.

        When a dynamic trigger owns the name the callable stays in the merged
        map and the static value is only recorded in ``shadowed_static_snippets``
        so it still reaches disk (via ``build_saveable_snippets``). Overwriting
        ``self.snippets[trigger]`` with the string would make the rebuilt trigger
        index expand the static for the rest of the session, contradicting the
        "the dynamic snippet is what expands" invariant that a reload restores.
        Otherwise the static value goes straight into the merged map.
        """
        if callable(self.snippets.get(trigger)):
            self.shadowed_static_snippets[trigger] = value
        else:
            self.snippets[trigger] = value

    def save_static_snippet(self, trigger, value):
        """Store one static snippet and persist the library; False if nothing changed on disk.

        On a failed write memory goes back to what it was, so every manager
        shows exactly what ``snippets.json`` holds.
        """
        previous = self.snippets.get(trigger, EDITOR_MISSING)
        previous_shadow = self.shadowed_static_snippets.get(trigger, EDITOR_MISSING)
        self._store_static_snippet(trigger, value)
        if not self.save_snippets(self.snippets):
            if previous is EDITOR_MISSING:
                self.snippets.pop(trigger, None)
            else:
                self.snippets[trigger] = previous
            if previous_shadow is EDITOR_MISSING:
                self.shadowed_static_snippets.pop(trigger, None)
            else:
                self.shadowed_static_snippets[trigger] = previous_shadow
            return False
        self.refresh_runtime_indexes()
        return True

    def save_mapping_item(self, container, name, value, *, metadata=None):
        """Store one mapping item (and ``metadata`` when given) and persist; False if nothing changed on disk."""
        previous = self.snippets.get(container, _MISSING)
        snapshot = dict(previous) if isinstance(previous, dict) else previous
        previous_metadata = self.library_metadata
        if metadata is not None:
            self.library_metadata = metadata
        if not isinstance(previous, dict):
            self.snippets[container] = {}
        self.snippets[container][name] = value
        if not self.save_snippets(self.snippets):
            self.library_metadata = previous_metadata
            if previous is _MISSING:
                self.snippets.pop(container, None)
            else:
                self.snippets[container] = snapshot
            return False
        self.refresh_runtime_indexes()
        return True

    def delete_mapping_item(self, container, name):
        """Remove one mapping item and persist; False (and nothing removed) on a failed write.

        Its metadata stays, so Desfazer can restore the item as it was.
        """
        mapping = self.snippets[container]
        removed = mapping.pop(name)
        if not self.save_snippets(self.snippets):
            mapping[name] = removed
            return False
        self.refresh_runtime_indexes()
        return True

    def create_mapping_type(self, container, prefix):
        """Add an empty mapping type and persist; False (and no type) on a failed write."""
        self.snippets[container] = {"__prefix__": prefix}
        if not self.save_snippets(self.snippets):
            del self.snippets[container]
            return False
        self.refresh_runtime_indexes()
        return True

    def delete_mapping_type(self, container):
        """Remove a mapping type with every item and persist; False (and the type kept) on a failed write."""
        removed = self.snippets.pop(container)
        if not self.save_snippets(self.snippets):
            self.snippets[container] = removed
            return False
        self.refresh_runtime_indexes()
        return True

    def _delete_static_snippet(self, trigger, *, include_shadowed=False):
        """Delete a static snippet by trigger, guarding shadowed dynamics.

        A selected persisted row may explicitly include a shadowed static;
        free-form callers keep the dynamic-route refusal. It asks nothing:
        the manager offers Desfazer instead. Returns one of
        ``"missing"``, ``"dynamic"`` (a dynamic trigger owns the name — refused
        so the preserved static is not lost, and the caller directs the user
        to Ações dinâmicas), ``"error"`` (save failed, in-memory state rolled
        back) or ``"ok"``.
        """
        if (include_shadowed and trigger in self.shadowed_static_snippets
                and (trigger not in self.snippets or callable(self.snippets[trigger]))):
            # A selected library row names the persisted static, not the
            # provider that owns expansion. Keep that callable in place.
            value = self.shadowed_static_snippets.pop(trigger)
            if not self.save_snippets(self.snippets):
                self.shadowed_static_snippets[trigger] = value
                return "error"
            self.refresh_runtime_indexes()
            return "ok"
        if trigger not in self.snippets:
            return "missing"
        if callable(self.snippets[trigger]):
            return "dynamic"
        value = self.snippets[trigger]
        del self.snippets[trigger]
        # An explicit delete must win over the shadow safety net, or the
        # preserved value would be written back on the next save.
        shadowed = self.shadowed_static_snippets.pop(trigger, None)
        if not self.save_snippets(self.snippets):
            # Roll back the in-memory delete on failure.
            self.snippets[trigger] = value
            if shadowed is not None:
                self.shadowed_static_snippets[trigger] = shadowed
            return "error"
        self.refresh_runtime_indexes()
        return "ok"

    def notify(self, message: str, title: str = PRODUCT_NAME, key: str = None, cooldown_seconds: float = 0, kind: str = "info", in_manager: bool = False):
        """Tell the person something: a receipt in the manager, or a tray notification.

        Routine success (``kind="status"``) is quiet while the person is in the
        window: it becomes a receipt on the manager's status line, never a
        toast. ``in_manager`` says the person just did it there; any other
        status becomes a receipt only while the manager has the input focus,
        and is a toast when they are working elsewhere. Errors, and everything
        else, are always tray notifications. Every message is kept in the
        history either way.

        The cooldown check and the history append are done under
        ``_notification_lock`` so concurrent callers (listener + workers) cannot
        lose an update or both pass the same cooldown window. The disk write and
        the tray call run outside the lock, against a snapshot taken inside it,
        so the lock is never held across I/O.
        """
        with self._notification_lock:
            icon = self.icon
        in_window = kind == "status" and self._manager_visible
        if not icon and not in_window:
            return False

        text = truncate_notification_text(message)
        moment = datetime.now()
        entry = {
            "time": moment.strftime("%H:%M:%S"),
            "at": moment.isoformat(timespec="seconds"),
            "title": title,
            "message": text,
            "kind": kind,
        }

        with self._notification_lock:
            # A receipt for what the person just did replaces the line, so it
            # needs no cooldown; anything that can still become a toast keeps it.
            if key and not (in_window and in_manager):
                now = time.time()
                last_sent = self.notification_timestamps.get(key, 0)
                if (now - last_sent) < cooldown_seconds:
                    return False
                self.notification_timestamps[key] = now
            self.notification_history.append(entry)
            if len(self.notification_history) > NOTIFICATION_HISTORY_LIMIT:
                self.notification_history = self.notification_history[-NOTIFICATION_HISTORY_LIMIT:]
            history_snapshot = list(self.notification_history)

        save_notification_history(self.notification_history_file, history_snapshot)

        if in_window:
            # The window is Tk's: the receipt is drawn on the GUI thread, which
            # also sees whether the person is looking at it.
            self.gui.submit(lambda _root: self._show_receipt(text, title, in_manager))
            return True
        return self._toast(icon, text, title)

    def _toast(self, icon, text, title):
        try:
            icon.notify(text, title)
            return True
        except Exception as e:
            self.logger.warning(f"Falha ao exibir notificação: {e}")
            return False

    def _manager_has_focus(self):
        """True while one of the app's windows has the input focus. GUI thread."""
        window = self.manager_window
        try:
            return window is not None and window.focus_displayof() is not None
        except tk.TclError:
            return False

    def _current_receipt(self):
        """The status line of the page the manager shows, or None. GUI thread."""
        notebook = self._manager_notebook
        if notebook is None:
            return None
        try:
            return self._manager_receipts.get(str(notebook.select()))
        except tk.TclError:
            return None

    def _show_receipt(self, text, title, in_manager):
        """Write ``text`` on the manager's status line, or toast it. GUI thread.

        The window can close between the check that chose the receipt and
        here, and a status from the tray or a hotkey reaches a manager the
        person is not looking at; both fall back to the tray.
        """
        receipt = self._current_receipt()
        if receipt is not None and (in_manager or self._manager_has_focus()):
            receipt.show(text)
            return
        icon = self.icon
        if icon:
            self._toast(icon, text, title)

    def notify_status(self, message: str, key: str = None, *, in_manager: bool = False):
        return self.notify(
            message, key=key, cooldown_seconds=2, kind="status", in_manager=in_manager)

    def receipt(self, outcome: str, name: str = None, key: str = None, *, in_manager: bool = True):
        """Receipt of a command: "Salvo às 14:32 · xola".

        ``outcome`` is the interface string, marked with ``N_``, with a
        ``{time}`` slot ("Salvo às {time}"); ``name`` is the object it was
        done to, when the outcome does not already say. ``in_manager`` is
        False for a command given outside the window (tray, hotkey), whose
        receipt reaches the status line only while the window has the focus.
        """
        text = _(outcome).format(time=time_format.clock(datetime.now()))
        return self.notify_status(
            text if name is None else f"{text} · {name}", key=key, in_manager=in_manager)

    def _notify_or_queue(self, message: str, key: str, kind: str, cooldown_seconds: float):
        """Notify now, or queue for tray startup when the icon is not up yet."""
        with self._notification_lock:
            # pystray assigns the icon object before its backend has created the
            # native tray item.  Queue until ``on_tray_ready`` marks it visible,
            # otherwise an early secure-input notice can be lost or call into a
            # half-initialized backend.
            if not self.icon or not getattr(self.icon, "visible", False):
                self.pending_notifications.append((message, key, kind, cooldown_seconds))
                return False
        return self.notify(message, key=key, cooldown_seconds=cooldown_seconds, kind=kind)

    def notify_error(self, message: str, key: str = None, cooldown_seconds: float = 8):
        return self._notify_or_queue(message, key, "error", cooldown_seconds)

    def notify_deferred_status(self, message: str, key: str = None, cooldown_seconds: float = 8):
        """Queue an informational tray message that must survive an early startup."""
        return self._notify_or_queue(message, key, "status", cooldown_seconds)

    def notify_snippet_failure(self, trigger: str, result):
        message = build_snippet_failure_notification(trigger, result)
        if message:
            self.notify_error(message, key=f"snippet-failure:{trigger}")
        return message

    def on_tray_ready(self, icon):
        with self._notification_lock:
            self.icon = icon
        icon.visible = True
        self.task_runner.start(self.notify_launch_ready, name="startup-notify")
        self.task_runner.start(self.resolve_autostart_state, name="autostart-state")
        # After the icon exists, so the denied state can be notified rather than
        # queued, and the window opens over an app that is already up.
        self.task_runner.start(self.resolve_macos_permissions, name="macos-permissions")

    def notify_launch_ready(self, icon=None):
        if icon is not None:
            with self._notification_lock:
                self.icon = icon
        time.sleep(0.75)
        self.notify_status(_("SnipType iniciado com sucesso."), key="startup")
        with self._notification_lock:
            pending, self.pending_notifications = self.pending_notifications, []
        for message, key, kind, cooldown in pending:
            self.notify(message, key=key, cooldown_seconds=cooldown, kind=kind)

    # =====================================================================
    # KEYBOARD LISTENER
    # =====================================================================
    def _dispatch_hotkey_action(self, action):
        """Queue a workflow action away from the keyboard listener callback."""
        self.task_runner.start(
            self._run_hotkey_action,
            action,
            name=f"hotkey-{action}",
        )

    def _run_hotkey_action(self, action):
        """Perform one configured workflow action through its safe seam."""
        try:
            if action == "edit_last":
                self._pending_manager_target = self.workflow_state.last_successful_item
            if action == "open_manager":
                self.open_manager()
            elif action == "edit_last":
                # Jumping to an item is a classic-manager feature for now.
                self.gui.submit(self._show_manager_window)
            elif action == "toggle_enabled":
                self.gui.submit(self._toggle_enabled_from_hotkey)
        except Exception as e:
            self.logger.error(f"Falha no atalho de fluxo '{action}': {e}")

    def _toggle_enabled_from_hotkey(self, _root=None):
        """Apply the enabled toggle on the GUI thread, where tray state is safe."""
        self.toggle_enabled(self.icon, None)

    def _workflow_ref(self, trigger):
        """Resolve a completed expansion to its stable workflow reference."""
        if isinstance(trigger, ExpansionTarget):
            if trigger.source_kind == "static":
                return SnippetRef("static", trigger.stable_identity)
            if trigger.source_kind == "mapping":
                # Current compiled direct targets are static-only; mappings
                # resolve through the legacy string path below. Keep a future
                # mapping target from raising because its container is not
                # carried by ExpansionTarget.
                return None
            return SnippetRef("dynamic", trigger.stable_identity)

        if not isinstance(trigger, str) or not trigger:
            return None
        # A raw string can still name a direct target in compatibility calls.
        # Prefer the compiled route because a stored key may be disabled or may
        # have a group prefix while the same typed text belongs to a mapping.
        for target in getattr(self, "trigger_index", {}).get("direct_targets", ()):
            if target.effective_trigger == trigger:
                return self._workflow_ref(target)
        value = self.snippets.get(trigger)
        if callable(value):
            for stable_key, entry in self.dynamic_registry.items():
                if effective_trigger(stable_key, entry) == trigger:
                    return SnippetRef("dynamic", stable_key)
            return SnippetRef("dynamic", trigger)
        for prefix, container in get_dynamic_prefixes(self.snippets).items():
            if not trigger.startswith(prefix) or len(trigger) <= len(prefix):
                continue
            item = trigger[len(prefix):]
            mapping = self.snippets.get(container)
            if isinstance(mapping, dict) and item in mapping and item != "__prefix__":
                return SnippetRef("mapping", item, container)
        if trigger in self.snippets and not trigger.startswith("_"):
            return SnippetRef("static", trigger)
        return None

    def on_press(self, key, injected=False):
        """Detect a trigger on the listener thread; expand on a worker thread.

        The listener must stay fast and unkillable: it only appends the keystroke,
        matches a trigger, erases the typed trigger, and hands all real work
        (callables, network, dialogs, clipboard, paste) to a background thread.

        ``injected`` comes from pynput >= 1.8 (older versions omit it). Our own
        untagged synthesized keys (macOS erase and paste, a re-emitted
        terminator) arrive here flagged, and must not look like user typing.
        """
        try:
            if not injected:
                self._input_generation += 1
            if self.hotkey_router.press(key):
                self.typed_text = ""
                return
            if not self.enabled:
                # Paused: no matching, so nothing is erased, and nothing typed
                # now can complete a trigger after resuming. The hotkey router
                # above stays live so the toggle hotkey can resume expansion.
                self.typed_text = ""
                return
            mouse_generation = self.mouse_monitor.generation
            if mouse_generation != self._buffer_mouse_generation:
                self.typed_text = ""
                self._buffer_mouse_generation = mouse_generation
            char = getattr(key, 'char', None)
            if IS_WINDOWS:
                # pynput mistranslates numpad digits, '/' and the decimal key.
                char = win_input.typed_char(getattr(key, 'vk', None), char)
            if char:
                self._handle_char(char)
            elif key == Key.space:
                # Every pynput backend delivers Space as this enum member, which
                # has no .char, so it would otherwise never reach the matcher.
                self._handle_char(" ")
            elif key == Key.enter:
                # ceiling: terminator mode does not gate on Enter (re-typing it could
                # double-submit); Enter always just resets the buffer. Extend to Enter
                # if a safe re-emit strategy is needed.
                self.typed_text = ""
            elif key == Key.backspace and self.typed_text:
                self.typed_text = self.typed_text[:-1]
            elif key in BUFFER_RESET_KEYS:
                self.typed_text = ""
        except Exception as e:
            # A detection error must never stop the global keyboard listener.
            self.typed_text = ""
            self.logger.error(f"Erro no listener de teclado: {e}")
            self.notify_error(
                _("Erro ao detectar snippet: {e}").format(e=e),
                key="listener-error",
                cooldown_seconds=10,
            )

    def on_release(self, key):
        """Release hotkey state without touching GUI, disk, or snippet data."""
        try:
            self.hotkey_router.release(key)
        except Exception as e:
            self.logger.error(f"Erro ao liberar atalho de teclado: {e}")

    def _handle_char(self, char):
        """Append a typed character and run trigger detection."""
        if self.trigger_index.get("global_terminator_mode") != self.terminator_mode:
            # Settings changes normally refresh the index immediately. Keep
            # direct in-memory toggles backward compatible with one rebuild,
            # rather than scanning policy on every keypress.
            self.rebuild_trigger_index()
        window = platform_support.foreground_window_handle()
        if window != self._buffer_window:
            # Text typed in another window cannot complete a trigger here.
            # ceiling: macOS and Linux report no window, so their buffer still
            # spans app switches; add the CGEvent target PID (darwin_intercept)
            # or X11 active window when that platform's users hit it.
            self.typed_text = ""
            self._buffer_window = window
        self.typed_text += char
        if len(self.typed_text) > self.max_trigger_length:
            self.typed_text = self.typed_text[-self.max_trigger_length:]

        immediate_candidate = self._detect_immediate()
        if char in TERMINATOR_CHARS and not immediate_candidate:
            self._detect_terminated(char)

    def _detect_immediate(self):
        """Immediate mode: expand as soon as a trigger suffix matches."""
        target, candidate_found = self._find_direct_target(self.typed_text, False)
        if candidate_found:
            if target is not None:
                self._dispatch_expansion(target, len(target.effective_trigger))
            return True
        if self.terminator_mode:
            return False
        potential_trigger, result = find_dynamic_trigger(
            self.snippets,
            self.typed_text,
            self.trigger_index,
        )
        if result is not None:
            self._dispatch_expansion(potential_trigger, len(potential_trigger))
            return True
        return False

    def _detect_terminated(self, terminator_char):
        """Terminator mode: expand only when a word-ending char follows a trigger."""
        body = self.typed_text[:-1]  # drop the terminator just typed
        target, candidate_found = self._find_direct_target(body, True)
        if candidate_found:
            if target is not None:
                self._dispatch_expansion(
                    target,
                    len(target.effective_trigger) + 1,
                    append_text=terminator_char,
                )
            return
        # Mappings and registry-backed dynamics intentionally retain the global
        # terminator policy; they are checked only in this branch.
        if not self.terminator_mode:
            return
        potential_trigger, result = find_dynamic_trigger(self.snippets, body, self.trigger_index)
        if result is not None:
            self._dispatch_expansion(potential_trigger, len(potential_trigger) + 1, append_text=terminator_char)

    def _static_form_metadata(self, stored_key):
        """Return persisted form metadata for a static stored identity, if any."""
        metadata = self.library_metadata
        if not isinstance(metadata, dict):
            return None
        items = metadata.get("items", {})
        static_items = items.get("static", {}) if isinstance(items, dict) else {}
        item = static_items.get(stored_key, {}) if isinstance(static_items, dict) else {}
        form = item.get("form") if isinstance(item, dict) else None
        return form if isinstance(form, dict) else None

    def _mapping_identity(self, trigger):
        """Return ``(container, item)`` for a composed mapping trigger."""
        if not isinstance(trigger, str):
            return None
        for prefix, container in get_dynamic_prefixes(self.snippets).items():
            if not trigger.startswith(prefix) or len(trigger) <= len(prefix):
                continue
            item = trigger[len(prefix):]
            mapping = self.snippets.get(container)
            if isinstance(mapping, dict) and item in mapping and item != "__prefix__":
                return container, item
        return None

    def _mapping_form_metadata(self, container, item_key):
        metadata = self.library_metadata
        if not isinstance(metadata, dict):
            return None
        items = metadata.get("items", {})
        mappings = items.get("mappings", {}) if isinstance(items, dict) else {}
        container_metadata = mappings.get(container, {}) if isinstance(mappings, dict) else {}
        item = container_metadata.get(item_key, {}) if isinstance(container_metadata, dict) else {}
        form = item.get("form") if isinstance(item, dict) else None
        return form if isinstance(form, dict) else None

    def _form_metadata_for_trigger(self, trigger):
        form = self._static_form_metadata(trigger)
        if form is not None:
            return form
        identity = self._mapping_identity(trigger)
        if identity is None:
            return None
        return self._mapping_form_metadata(*identity)

    def _find_direct_target(self, typed_text, terminated):
        """Find one compiled direct candidate and apply its app policy.

        The bucket is precompiled, so this performs no metadata or disk work on
        the listener.  ``candidate_found`` distinguishes a denied longest match
        from no direct match and prevents a shorter/dynamic fallback.
        """
        if not typed_text:
            return None, False
        bucket_name = (
            "direct_terminated_by_last_char"
            if terminated
            else "direct_immediate_by_last_char"
        )
        candidates = self.trigger_index.get(bucket_name, {}).get(typed_text[-1], ())
        for target in candidates:
            if typed_text.endswith(target.effective_trigger):
                if self._target_application_allowed(target):
                    return target, True
                return None, True
        return None, False

    def _target_application_allowed(self, target):
        """Resolve foreground identity only for a candidate needing it."""
        policy = self.trigger_index.get("application_policies", {}).get(target.stable_identity)
        if policy is None or policy.mode == "all":
            return True
        executable = None
        if platform_support.IS_WINDOWS:
            executable = platform_support.foreground_executable_name()
        return target_is_allowed(
            target,
            self.trigger_index,
            executable,
            windows=platform_support.IS_WINDOWS,
        )

    def _dispatch_expansion(self, trigger, erase_length, append_text=""):
        """Erase the typed trigger and run the expansion on a worker thread."""
        self._expansion_generation = getattr(self, "_expansion_generation", 0) + 1
        monitor = getattr(self, "mouse_monitor", None)
        mouse_generation = monitor.generation if monitor is not None else 0
        if mouse_generation != getattr(self, "_buffer_mouse_generation", 0):
            # A click observed between matching and erasure invalidated this match.
            self.typed_text = ""
            self._buffer_mouse_generation = mouse_generation
            return
        window = platform_support.foreground_window_handle()
        if self._secure_input_blocks_expansion():
            self.typed_text = ""
            return
        if not self._erase_chars(erase_length):
            # The trigger text (or part of it) is still in the window, and a
            # paste into a window that rejects input would be rejected too.
            # Notify from a worker: the listener must not touch the tray or
            # write history, and notify() applies the cooldown under its lock.
            self.typed_text = ""
            self.task_runner.start(
                self.notify_error,
                _("O Windows bloqueou a expansão nesta janela, provavelmente "
                  "porque ela está em execução como administrador."),
                key="injection-blocked",
                cooldown_seconds=60,
                name="injection-blocked-notify",
            )
            return
        self.typed_text = ""
        worker_target = trigger
        if isinstance(trigger, ExpansionTarget):
            # Metadata-aware expansions retain the stable stored identity while
            # carrying the effective trigger across a concurrent index refresh.
            metadata_present = getattr(self.library_metadata, "present", None)
            if metadata_present is None:
                metadata_present = bool(self.library_metadata)
            if metadata_present or (
                trigger.effective_trigger != trigger.stable_identity
            ):
                worker_target = trigger
            else:
                worker_target = trigger.effective_trigger
        effective = (
            trigger.effective_trigger
            if isinstance(trigger, ExpansionTarget)
            else trigger
        )
        # Snapshot the selected route with the immutable target. A manager save
        # may rebuild the index before the worker starts; that refresh must not
        # turn an already-selected form or slow expansion into the plain path.
        # Keep this seam tolerant of a minimal app instance. Platform gate
        # tests and shutdown-adjacent callers may exercise dispatch before an
        # index has been published; a missing snapshot means the legacy plain
        # route, not a listener-thread exception.
        trigger_index = getattr(self, "trigger_index", {})
        slow_route = (
            effective in trigger_index.get("slow_triggers", ())
            or effective in trigger_index.get("form_triggers", ())
        )
        # The text target this trigger was typed into: an int read plus one
        # user32 call, cheap enough for the listener. The worker compares it
        # right before pasting (_expansion_target_is_current). Only a slow
        # route (network, dialog) compares keystrokes: a fast expansion pastes
        # within ~0.1 s, and a fast typist's next key must not turn it into a
        # clipboard notice.
        context = (
            getattr(self, "_input_generation", 0) if slow_route else None,
            window,
            mouse_generation,
            self._expansion_generation,
        )
        self.task_runner.start(
            self._run_expansion,
            worker_target,
            append_text,
            slow_route,
            context=context,
            name="expand",
        )

    def _secure_input_blocks_expansion(self):
        """True when macOS Secure Keyboard Entry is swallowing synthesized input.

        Checked before the erase, not after: while secure input is on the system
        drops the backspaces and the Cmd+V alike, so the only clean outcome is to
        leave the trigger exactly as the user typed it and say why. Always False
        off macOS.
        """
        if not IS_MAC or not macos_permissions.secure_input_enabled():
            return False
        self.logger.info(macos_permissions.SECURE_INPUT_MESSAGE)
        # Notify off the listener thread: the deferred status path writes the
        # history JSON and calls into the tray only after the icon exists. Neither
        # operation may run on the keyboard listener (it must stay fast and
        # unkillable). The 60s cooldown is enforced inside notify() under its
        # lock, so racing triggers that each spawn a worker still produce exactly
        # one notification.
        self.task_runner.start(
            self.notify_deferred_status,
            _(macos_permissions.SECURE_INPUT_MESSAGE),
            key="secure-input",
            cooldown_seconds=60,
            name="secure-input-notify",
        )
        return True

    def _erase_chars(self, count):
        """Backspace over ``count`` characters on the listener thread.

        This thread also pumps the Windows keyboard hook, so any sleep here
        stalls keyboard input system-wide. With no per-key delay configured,
        Windows sends the whole erase as one uninterruptible batch.

        Returns False only when Windows rejected the batch, wholly or in part
        (``send_key_events`` does not tell the two apart); pynput reports no
        delivery result, so the paced erase returns True.
        """
        batch_keyboard = getattr(self, "batch_keyboard", None)
        if batch_keyboard is not None and not self.erase_key_delay:
            if not batch_keyboard.erase(count):
                self.logger.warning(
                    "Windows bloqueou o apagamento do gatilho "
                    "(janela em execução como administrador?)."
                )
                return False
            return True
        # A configured per-key delay keeps the legacy paced erase, which does
        # hold the listener for count * erase_key_delay.
        for _index in range(count):
            self.keyboard_controller.press(Key.backspace)
            self.keyboard_controller.release(Key.backspace)
            time.sleep(self.erase_key_delay)
        return True

    def _run_expansion(self, trigger, append_text="", slow_route=None, context=None):
        """Worker entry point: produce and insert the expansion for a trigger.

        The trigger text is already erased. This is wrapped so no expansion error
        (including a raising callable) can ever propagate to the listener thread.
        ``context`` is the dispatch-time text target; without it nothing is
        checked before pasting.
        """
        if not self.enabled:
            return
        self._expansion_context.value = context
        try:
            effective = trigger.effective_trigger if isinstance(trigger, ExpansionTarget) else trigger
            lookup = (
                trigger.stable_identity
                if isinstance(trigger, ExpansionTarget) and trigger.source_kind == "static"
                else effective
            )
            if slow_route is None:
                slow_route = (
                    effective in self.trigger_index["slow_triggers"]
                    or effective in self.trigger_index["form_triggers"]
                )
            if slow_route:
                outcome = self.run_slow_snippet(lookup)
            else:
                outcome = self.expand_snippet(lookup)
            completed = outcome is True or outcome is ACTION_COMPLETED
            inserted = outcome is True
            if completed:
                reference = self._workflow_ref(trigger)
                if reference is not None:
                    self.workflow_state.record_success(reference)
                    self._last_successful_expansion_at = datetime.now()
                    if self.manager_window is not None:
                        self.gui.submit(self._refresh_edit_last)
            # Only re-emit the terminator when text was actually inserted, so a
            # cancelled form dialog or a failed paste does not leave a stray char.
            if append_text and inserted and self._expansion_target_is_current():
                self.keyboard_controller.type(append_text)
        except Exception as e:
            self.logger.error(f"Erro na expansão de {getattr(trigger, 'effective_trigger', trigger)}: {e}")
            self.notify_error(
                _("Falha ao expandir {trigger}: {e}").format(trigger=getattr(trigger, 'effective_trigger', trigger), e=e),
                key=f"expand-error:{getattr(trigger, 'effective_trigger', trigger)}",
                cooldown_seconds=5,
            )
        finally:
            self._expansion_context.value = None

    def _expansion_target_is_current(self):
        """True when this worker's expansion may still be pasted.

        Mouse clicks and newer triggers retire every pending result. A slow
        route also checks ordinary typing; Windows checks the foreground HWND.
        Workers outside an expansion have no context and are never blocked.
        """
        context = getattr(self._expansion_context, "value", None)
        if context is None:
            return True
        generation, window, mouse_generation, expansion_generation = context
        if not self.enabled or expansion_generation != self._expansion_generation:
            return False
        try:
            if mouse_generation != self.mouse_monitor.generation:
                return False
        except RuntimeError:
            # A failed observer cannot establish that the insertion target is safe.
            return False
        if generation is not None and generation != self._input_generation:
            return False
        return window is None or platform_support.foreground_window_handle() == window

    def _rebaseline_expansion_context(self):
        """Accept keys/clicks inside an expansion dialog that just closed.

        The global hook sees what the user types into Sniptype's own dialog;
        only keys pressed after focus is back on the original target count.
        """
        context = getattr(self._expansion_context, "value", None)
        if context is not None:
            self._expansion_context.value = (
                self._input_generation if context[0] is not None else None,
                context[1], self.mouse_monitor.generation,
                context[3],
            )























    # =====================================================================
    # SNIPPET MANAGEMENT GUI
    # =====================================================================

    def _save_hotkey_bindings(self, bindings):
        """Persist valid hotkeys, replacing the live router only after success."""
        normalized, invalid = normalize_hotkeys(bindings)
        if invalid:
            return False
        previous = self.settings
        updated = dict(previous)
        existing = previous.get("hotkeys", {})
        existing = dict(existing) if isinstance(existing, dict) else {}
        updated["hotkeys"] = {**existing, **normalized}
        if not save_settings(self.settings_file, updated):
            return False
        self.settings = updated
        self.hotkey_router = HotkeyRouter(
            updated["hotkeys"],
            self._dispatch_hotkey_action,
        )
        return True

    def configure_hotkeys(self, icon=None, item=None):
        """Open the optional workflow-hotkey editor on the GUI thread."""
        try:
            self.gui.submit(self._show_hotkey_settings)
        except Exception as e:
            self.logger.error(f"Erro ao abrir configurações de atalhos: {e}")

    def _show_hotkey_settings(self, tk_root):
        """GUI-thread callback for editing and atomically saving hotkeys."""
        from hotkey_dialog import run_hotkey_dialog

        parent = tk_root
        manager = self.manager_window
        try:
            if manager is not None and bool(manager.winfo_exists()):
                parent = manager
        except Exception:
            pass

        result = run_hotkey_dialog(parent, self.settings.get("hotkeys", {}))
        if result is None:
            return
        if self._save_hotkey_bindings(result):
            self.notify_status(
                _("Atalhos salvos."), key="hotkeys-saved", in_manager=parent is manager)
        else:
            self.notify_error(_("Não foi possível salvar os atalhos."), key="hotkeys-save")

    def manage_snippets_gui(self, icon, item):
        """Open (or re-focus) the snippet manager window."""
        try:
            self.open_manager()
        except Exception as e:
            self.logger.error(f"Erro ao abrir gerenciador: {e}")
            self.notify_error(
                _("Erro ao abrir gerenciador: {e}").format(e=e),
                key="gui-open-error",
                cooldown_seconds=5,
            )

    def open_manager(self):
        """Show the manager the person chose: the Tauri window or the classic Tk one."""
        if self.settings.get(MANAGER_UI_SETTING) == "tauri" and self._open_tauri_manager():
            return
        self.gui.submit(self._show_manager_window)

    def _open_tauri_manager(self):
        """Start or raise the Tauri manager; False, after saying why, when it cannot run."""
        with self._manager_process_lock:
            process = self._manager_process
            if process is not None and process.alive:
                process.focus()
                return True
            executable = find_manager_executable()
            if executable is None:
                self.logger.error("Tauri manager executable not found; opening the classic manager.")
                self.notify_error(_("O novo gerenciador não foi encontrado; abrindo o gerenciador clássico."),
                                  key="manager-ui-missing", cooldown_seconds=5)
                return False
            bridge = ManagerBridge(self, version=APP_VERSION, channel=RELEASE_CHANNEL)
            try:
                self._manager_process = ManagerProcess(
                    self, executable, bridge, log_path=os.path.join(self.logs_dir, "manager-ui.log"))
            except OSError as e:
                self.logger.error(f"Tauri manager failed to start ({executable}): {e}")
                self.notify_error(_("O novo gerenciador não abriu; abrindo o gerenciador clássico."),
                                  key="manager-ui-start", cooldown_seconds=5)
                return False
            return True

    def _manager_rows(self):
        """Return the immutable local projection used by manager navigation."""
        revision = getattr(self, "_manager_rows_revision", 0)
        cached = getattr(self, "_manager_rows_cache", None)
        if cached is None or cached[0] != revision:
            rows = build_manager_rows(
                self.snippets, getattr(self, "library_metadata", None),
                getattr(self, "dynamic_registry", None),
                getattr(self, "shadowed_static_snippets", None),
            )
            self._manager_rows_cache = (revision, rows)
            return rows
        return cached[1]

    def _invalidate_manager_rows(self):
        """Invalidate after publication; failed writes never publish proposed rows."""
        self._manager_rows_revision = getattr(self, "_manager_rows_revision", 0) + 1
        self._manager_rows_cache = None

    def _schedule_manager_search(self, window, key, callback):
        self._manager_pending_search[key] = callback
        old = self._manager_search_jobs.pop(key, None)
        if old is not None:
            old[0].after_cancel(old[1])
        if not window.winfo_viewable():
            return
        def render():
            self._manager_search_jobs.pop(key, None)
            if not window.winfo_viewable():
                return
            pending = self._manager_pending_search.pop(key, None)
            if pending is not None:
                pending()
        self._manager_search_jobs[key] = (window, window.after(100, render))

    def _cancel_manager_search(self, window, *, discard=False):
        for key, (owner, job) in list(getattr(self, "_manager_search_jobs", {}).items()):
            if owner is window:
                owner.after_cancel(job)
                self._manager_search_jobs.pop(key, None)
        if discard:
            self._manager_pending_search = {}

    def _flush_manager_search(self, key=None):
        """Settle the current query before an immediate result action.

        A keyed handoff leaves other collections' debounce timers untouched.
        Reopening may omit the key to settle every retained collection.
        """
        keys = tuple(self._manager_pending_search) if key is None else (key,)
        for pending_key in keys:
            job = self._manager_search_jobs.pop(pending_key, None)
            if job is not None:
                job[0].after_cancel(job[1])
            callback = self._manager_pending_search.pop(pending_key, None)
            if callback is not None:
                callback()

    def _capture_manager_view(self, window):
        selected = str(self._manager_notebook.select())
        page = next((name for name, widget in self._manager_pages.items()
                     if str(widget) == selected), "static")
        # WM geometry can use right/bottom-relative offsets. Persist absolute
        # frame coordinates so validation and application use the same space.
        geometry = (f"{window.winfo_width()}x{window.winfo_height()}"
                    f"{window.winfo_x():+d}{window.winfo_y():+d}")
        return normalize_manager_view({"page": page, "geometry": geometry,
                                       "pages": {name: callbacks[0]() for name, callbacks
                                                 in self._manager_views.items()}})

    @staticmethod
    def _manager_monitors(window):
        if platform_support.IS_WINDOWS:
            from ctypes import wintypes
            monitors = []
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR,
                                               wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                               wintypes.LPARAM)
            def collect(_monitor, _dc, rectangle, _data):
                rect = rectangle.contents
                monitors.append((rect.left, rect.top, rect.right, rect.bottom))
                return 1
            callback = callback_type(collect)
            if ctypes.windll.user32.EnumDisplayMonitors(None, None, callback, 0):
                return monitors
            # An unavailable monitor inventory cannot validate a saved position.
            return []
        return [(window.winfo_vrootx(), window.winfo_vrooty(),
                 window.winfo_vrootx() + window.winfo_vrootwidth(),
                 window.winfo_vrooty() + window.winfo_vrootheight())]

    def _restore_manager_view(self, window, value):
        view = normalize_manager_view(value)
        geometry = view.get("geometry")
        if geometry_intersects_monitors(geometry, self._manager_monitors(window)):
            window.geometry(manager_geometry_for_tk(geometry))
        page = self._manager_pages.get(view.get("page"))
        if page is not None:
            self._manager_notebook.select(page)
        for name, state in view.get("pages", {}).items():
            callbacks = self._manager_views.get(name)
            if callbacks:
                callbacks[1](state)
        self._cancel_manager_search(window, discard=True)

    def _hide_manager_window(self, window):
        if not self._resolve_manager_drafts(window):
            return False
        view = self._capture_manager_view(window)
        if not self._persist_settings({"manager_view": view}):
            ui_widgets.alert(window, _("Não foi possível salvar a visualização"),
                             _("A janela continua aberta. Verifique os logs e tente de novo."), tone="danger")
            return False
        self._stop_system_appearance_poll(window)
        self._cancel_manager_search(window)
        window.withdraw()
        return True

    def _refresh_edit_last(self, _root=None):
        target = self.workflow_state.last_successful_item
        descriptor = self._manager_target(target) if target is not None else None
        control = getattr(self, "_manager_edit_last_control", None)
        if control is not None:
            _set_enabled(control, descriptor is not None)
        status = getattr(self, "_manager_last_expansion_var", None)
        if status is not None:
            when = getattr(self, "_last_successful_expansion_at", None)
            status.set(_("Última expansão: {name} · {when}").format(
                name=descriptor.effective_trigger if descriptor else target.key,
                when=time_format.absolute_stamp(when, datetime.now()))
                if target is not None and when is not None else _("Nada expandido ainda"))

    def _manager_target(self, target):
        """Resolve a workflow reference without touching disk or GUI state."""
        return find_manager_target(self._manager_rows(), target)

    def _manager_dynamic_triggers(self):
        """Return dynamic routes for pure manager collision validation."""
        triggers = {
            key for key, value in self.snippets.items()
            if isinstance(key, str) and callable(value)
        }
        triggers.update(composed_mapping_triggers(self.snippets))
        registry = getattr(self, "dynamic_registry", {})
        triggers.update(
            effective_trigger(key, entry)
            for key, entry in registry.items()
            if is_enabled(entry, key=key)
        )
        return triggers

    def _persist_manager_action(self, result):
        """Persist a copy-on-write manager result, then publish it in memory.

        ``save_snippets`` accepts the proposed metadata as an argument so a
        failed atomic write cannot expose a half-applied manager edit.
        """
        try:
            if not self.save_snippets(result.snippets, metadata=result.metadata):
                return False
        except MetadataReadOnlyError:
            return False
        self.snippets = result.snippets
        self.library_metadata = result.metadata
        self.refresh_runtime_indexes()
        self._refresh_manager_lists()
        return True

    def _manager_static_projection(self):
        """Values the static manager owns, alongside untouched dynamic routes."""
        return {**self.snippets, **self.shadowed_static_snippets}

    def _persist_manager_static_action(self, result):
        """Persist static-manager changes while retaining live provider identity."""
        providers = {key: value for key, value in self.snippets.items() if callable(value)}
        old_shadows = self.shadowed_static_snippets
        self.shadowed_static_snippets = {
            key: value for key, value in result.snippets.items()
            if key in providers and not callable(value)
        }
        try:
            if not self.save_snippets(result.snippets, metadata=result.metadata):
                self.shadowed_static_snippets = old_shadows
                return False
        except MetadataReadOnlyError:
            self.shadowed_static_snippets = old_shadows
            return False
        except Exception:
            self.shadowed_static_snippets = old_shadows
            raise
        self.snippets = {**result.snippets, **providers}
        self.library_metadata = result.metadata
        self.refresh_runtime_indexes()
        self._refresh_manager_lists()
        return True

    def _select_manager_target(self, target):
        """Select a pending target in its tab, returning whether it was found."""
        if target is None:
            return True
        descriptor = self._manager_target(target)
        if descriptor is None:
            self.notify_status(_("O item não está mais disponível."), key="manager-target-missing")
            return False
        selector = self._manager_tab_selectors.get(descriptor.tab)
        if selector is None or not selector(descriptor):
            self.notify_status(_("O item não está mais disponível."), key="manager-target-missing")
            return False
        return True

    def _show_manager_filter_dialog(self, root, filter_name, title):
        """Show a cross-kind Favorites/Recent chooser and navigate on activate."""
        ui = ui_theme.theme()
        rows = filter_manager_rows(
            self._manager_rows(),
            filter_name,
            workflow_state=self.workflow_state,
        )
        dialog = tk.Toplevel(root)
        dialog.title(title)
        dialog.transient(root)
        dialog.configure(bg=ui.surface)
        dialog.minsize(460, 300)
        self._set_window_icon(dialog)
        ui_theme.prepare_window(dialog, ui)
        body = tk.Frame(dialog, bg=ui.surface, padx=ui.space_lg, pady=ui.space_lg)
        body.pack(fill="both", expand=True)
        list_field = ui_widgets.list_frame(body)
        listbox = ui_widgets.tree_list(list_field)
        listbox.pack(fill="both", expand=True)
        ui_widgets.track_focus(list_field, listbox)
        kind_labels = {"static": _("Snippet"), "mapping": _("Mapeamento"), "dynamic": _("Dinâmico")}
        for index, row in enumerate(rows):
            listbox.insert(
                "", tk.END, iid=str(index),
                text=f"{kind_labels.get(row.kind, row.kind)}  •  {row.effective_trigger}",
            )
        if rows:
            listbox.selection_set(0)
        else:
            listbox.insert("", tk.END, text=_("Nenhum item disponível."))
            listbox.state(["disabled"])

        def activate(_event=None):
            selection = listbox.selection()
            if not selection or not rows:
                return
            if not self._resolve_manager_drafts(root):
                return
            if self._select_manager_target(rows[int(selection[0])].ref):
                dialog.destroy()

        listbox.bind("<Double-Button-1>", activate)
        # Enter and Escape come from the footer, which is packed first so a
        # short window shrinks the list rather than clipping the buttons.
        footer = ui_widgets.dialog_footer(body, (_("Abrir"), activate), dialog.destroy, ui=ui)
        footer.pack(side="bottom", fill="x", pady=(ui.space_md, 0))
        if not rows:
            footer.buttons["primary"].configure(state=tk.DISABLED)
        list_field.pack(fill="both", expand=True)
        listbox.focus_set()
        return dialog

    def _show_manager_window(self, tk_root):
        """Build the manager window, or raise the one already open.

        GUI thread only. In-process window tracking replaces the old Win32
        FindWindowW lookup now that every window hangs off the shared root.
        """
        pending_target = self._pending_manager_target
        self._pending_manager_target = None
        window = self.manager_window
        try:
            already_open = window is not None and bool(window.winfo_exists())
        except Exception:
            already_open = False

        if already_open:
            window.deiconify()
            self._check_system_appearance(window)
            window = self.manager_window
            self._start_system_appearance_poll(window)
            self._cancel_manager_search(window)
            self._flush_manager_search()
            self._refresh_edit_last()
            window.lift()
            window.focus_force()
            self._select_manager_target(pending_target)
            return

        self.manager_window = None
        self._build_manager_window(tk_root)
        self._select_manager_target(pending_target)

    def _build_manager_window(self, tk_root):
        """Construct the management window as a Toplevel of the shared root."""
        try:
            # Re-resolved per window so reopening the manager picks up a system
            # appearance the user changed while it was closed.
            ui = ui_theme.bind(tk_root)
            root = tk.Toplevel(tk_root)
            root.theme_kind = ui.kind
            root.theme_text_scale = ui.text_scale
            root.theme_contrast_signature = ui.contrast_signature
            root.title(self._manager_title(dirty=False))
            geometry, min_width, min_height = ui.manager_window_size
            root.geometry(geometry)
            root.minsize(min_width, min_height)
            root.resizable(True, True)
            root.configure(bg=ui.surface)
            self._set_window_icon(root)
            self._configure_manager_styles(root)

            # Identity, state, navigation, and the window-wide actions share a
            # left sidebar so every page gets the window's full height; the
            # notebook is only the page container and draws no tab strip.
            root.grid_columnconfigure(2, weight=1)
            root.grid_rowconfigure(0, weight=1)
            sidebar_bg = ui.surface_alt
            sidebar = tk.Frame(root, bg=sidebar_bg, padx=ui.space_md, pady=ui.space_lg)
            sidebar.grid(row=0, column=0, sticky="ns")
            tk.Frame(root, bg=ui.divider, width=1).grid(row=0, column=1, sticky="ns")

            brand_icon = self._manager_brand_icon(root)
            brand = tk.Label(
                sidebar, text=PRODUCT_NAME, font=ui.font(14, "bold"),
                bg=sidebar_bg, fg=ui.text, anchor="w",
                image=brand_icon or "", compound=tk.LEFT, padx=ui.space_xs,
            )
            # Tk keeps no reference to a PhotoImage; the label must hold it.
            brand.image = brand_icon
            brand.pack(fill=tk.X, padx=(ui.space_xs, 0), pady=(0, ui.space_md))

            # The first thing the window says: is expansion working. A quiet dot
            # and a muted word while it is; a tone, an icon and a written state
            # when it is not (_refresh_manager_status).
            status_row = tk.Frame(sidebar, bg=sidebar_bg)
            status_row.pack(fill=tk.X, padx=(ui.space_sm, 0))
            self._manager_status_icon = tk.Label(status_row, bg=sidebar_bg)
            self._manager_status_icon.pack(side=tk.LEFT)
            self._manager_status_var = tk.StringVar(root)
            self._manager_status_label = tk.Label(
                status_row, textvariable=self._manager_status_var,
                font=ui.font(10), bg=sidebar_bg, fg=ui.text_muted, anchor="w",
            )
            self._manager_status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._manager_toggle_button = ui_widgets.button(
                sidebar, command=lambda: self.toggle_enabled(self.icon, None, in_manager=True),
            )
            self._manager_toggle_button.pack(fill=tk.X, pady=(ui.space_xs, ui.space_lg))
            self._refresh_manager_status()

            nav = tk.Frame(sidebar, bg=sidebar_bg)
            nav.pack(fill=tk.X)

            footer = tk.Frame(sidebar, bg=sidebar_bg)
            footer.pack(side=tk.BOTTOM, fill=tk.X)
            for label, action, icon in (
                (_("Editar último"), self.edit_last_snippet, "edit"),
                (_("Notificações"), lambda: self._open_notification_history(root), "bell"),
            ):
                item = ui_widgets.nav_item(footer, label, action, icon=icon)
                if icon == "edit":
                    self._manager_edit_last_control = item
            self._manager_last_expansion_var = tk.StringVar(root)
            tk.Label(footer, textvariable=self._manager_last_expansion_var,
                     bg=sidebar_bg, fg=ui.text_muted, font=ui.caption_font(),
                     wraplength=ui.px(190), justify=tk.LEFT, anchor="w").pack(fill=tk.X)
            self._refresh_edit_last()
            help_text = _("Ctrl+1–5: seções · Ctrl+F: busca\nCtrl+K: alternar · Ctrl+/: teclado")
            help_font = tkfont.Font(root=root, font=ui.caption_font())
            # Enlarged sidebar help must reserve its complete two-line width;
            # otherwise the fixed-height shell compresses its wrapped lines.
            help_width = (
                (max(help_font.measure(line) for line in help_text.splitlines()) + ui.px(16))
                // max(1, help_font.measure("0")) + 1 if ui.text_scale > 1 else 0
            )
            shortcut_label = tk.Label(
                footer, text=help_text, width=help_width,
                font=ui.caption_font(), bg=sidebar_bg, fg=ui.text_muted,
                anchor="w", justify="left", wraplength=170,
            )
            shortcut_label.pack(fill=tk.X, padx=(ui.space_sm, 0), pady=(ui.space_md, 0))
            ui_widgets.wrap_label(shortcut_label)
            tk.Label(
                footer, text=f"v{APP_VERSION}", font=ui.caption_font(),  # i18n: not ui
                bg=sidebar_bg, fg=ui.text_muted, anchor="w",
            ).pack(fill=tk.X, padx=(ui.space_sm, 0), pady=(ui.space_xs, 0))

            # The InfoBar slot sits above the pages: trouble that stays true
            # until it is resolved, written once for every page.
            content = tk.Frame(root, bg=ui.surface)
            content.grid(row=0, column=2, sticky="nsew")
            content.grid_columnconfigure(0, weight=1)
            content.grid_rowconfigure(1, weight=1)
            self._manager_health = ui_widgets.InfoBar(content, ui=ui)
            self._manager_health.frame.grid(row=0, column=0, sticky="ew")

            notebook = ttk.Notebook(content, style="Pages.TNotebook", takefocus=0)
            notebook.grid(row=1, column=0, sticky="nsew")
            self._manager_notebook = notebook

            tab_static = tk.Frame(notebook, bg=ui.surface)
            notebook.add(tab_static, text=_("Textos"))

            tab_dynamic = tk.Frame(notebook, bg=ui.surface)
            notebook.add(tab_dynamic, text=_("Mapeamentos"))

            tab_builtin = tk.Frame(notebook, bg=ui.surface)
            notebook.add(tab_builtin, text=_("Ações dinâmicas"))

            tab_backups = tk.Frame(notebook, bg=ui.surface)
            notebook.add(tab_backups, text=_("Cópias de segurança"))

            tab_settings = tk.Frame(notebook, bg=ui.surface)
            notebook.add(tab_settings, text=_("Configurações"))
            self._manager_settings_tab = tab_settings
            self._manager_pages = {
                "static": tab_static, "mapping": tab_dynamic,
                "dynamic": tab_builtin, "backups": tab_backups, "settings": tab_settings,
            }

            nav_items = self._build_manager_nav(ui, nav, notebook)

            def tab_counter(tab, label):
                def set_count(count):
                    text = f"{label} ({count})"
                    notebook.tab(tab, text=text)
                    nav_items[str(tab)].configure(text=text)
                return set_count

            # Tabs are rebuilt with the window; drop the previous window's
            # callbacks so they can't fire against destroyed widgets.
            self._manager_refreshers = []
            self._manager_editors = []
            self._manager_tab_selectors = {}
            self._manager_search_entries = {}
            self._manager_commands = {}
            self._manager_receipts = {}
            self._manager_views = {}
            self._create_static_snippets_tab(
                tab_static, root, set_count=tab_counter(tab_static, _("Textos")))
            self._create_dynamic_mappings_tab(
                tab_dynamic, root, set_count=tab_counter(tab_dynamic, _("Mapeamentos")))
            self._create_dynamic_snippets_tab(tab_builtin, root)
            self._create_backups_tab(tab_backups, root)
            self._create_settings_tab(tab_settings, root)
            self._refresh_manager_health()

            tabs = notebook.tabs()
            for index, tab_id in enumerate(tabs, 1):
                root.bind(
                    f"<Control-Key-{index}>",
                    lambda _event, selected=tab_id: (notebook.select(selected), "break")[1],
                )

            def focus_search(_event):
                entry = self._manager_search_entries.get(notebook.select())
                if entry is not None:
                    entry.focus_set()
                    entry.selection_range(0, tk.END)
                return "break"

            root.bind("<Control-f>", focus_search)
            self._bind_manager_commands(root, notebook)

            def on_close():
                self._hide_manager_window(root)

            root.protocol("WM_DELETE_WINDOW", on_close)
            self.manager_window = root
            self._track_manager_visibility(root)
            self._start_system_appearance_poll(root)
            root.lift()
            root.focus_force()
            focus_search(None)
            self._restore_manager_view(root, self.settings.get("manager_view", {}))

        except Exception as e:
            self._release_manager_ui_refs()
            self.logger.error(f"Erro na GUI de gerenciamento: {e}")
            self.notify_error(
                _("Erro ao abrir gerenciador: {e}").format(e=e),
                key="gui-open-error",
                cooldown_seconds=5,
            )


    @staticmethod
    def _change_counts_text(counts):
        return _("Novos: {new} · Sobrescritos: {overwritten} · Removidos: {removed}").format(**counts)

    def _ask_import_mode(self, root, file_name, document):
        """Mesclar, Substituir tudo (typed SUBSTITUIR) or Cancelar: "merge", "replace" or None.

        Replacing drops every item the file lacks, so it takes a second,
        typed confirmation; merging only overwrites what the file redefines.
        """
        counts = self.import_change_counts(document)
        choice = ui_widgets.confirm(
            root,
            _("Importar biblioteca"),
            _("Arquivo: {file}\n\n"
              "Mesclar mantém a biblioteca atual e dá prioridade ao arquivo.\n{merge}\n\n"
              "Substituir tudo troca a biblioteca pelo arquivo.\n{replace}\n\n"
              "Antes, a biblioteca atual é salva em um backup.").format(
                file=file_name,
                merge=self._change_counts_text(counts["merge"]),
                replace=self._change_counts_text(counts["replace"]),
            ),
            _("Mesclar"),
            extra=_("Substituir tudo…"),
            extra_danger=True,
        )
        if choice == ui_widgets.PRIMARY:
            return "merge"
        if choice != ui_widgets.EXTRA:
            return None
        if ui_widgets.confirm(
            root,
            _("Substituir tudo"),
            _("A biblioteca inteira é trocada pelo conteúdo de {file}.\n{replace}\n\n"
              "Antes, a biblioteca atual é salva em um backup.").format(
                file=file_name, replace=self._change_counts_text(counts["replace"])),
            _("Substituir tudo"),
            danger=True,
            typed_word=_("SUBSTITUIR"),
        ):
            return "replace"
        return None

    def _create_backups_tab(self, parent, root):
        """Backups tab: list backups and expose restore/export/import actions."""
        ui = ui_theme.theme()
        self._page_receipt(parent)
        main = tk.Frame(ui_widgets.page_viewport(parent), bg=ui.surface, padx=ui.space_lg, pady=ui.space_lg)
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        tk.Label(
            main,
            text=_("Backups da biblioteca"),
            font=ui.title_font(),
            bg=ui.surface,
            fg=ui.text,
        ).grid(row=0, column=0, sticky="w")
        path_row = tk.Frame(main, bg=ui.surface)
        path_row.grid(row=1, column=0, sticky="ew", pady=(ui.space_xs, ui.space_md))
        path_row.grid_columnconfigure(0, weight=1, minsize=0)
        path_label = tk.Label(
            path_row,
            text=self.data_dir,
            font=ui.mono_font(),
            bg=ui.surface,
            fg=ui.text_muted,
            anchor="w", width=1,
        )
        path_label.grid(row=0, column=0, sticky="ew", padx=(0, ui.space_sm))
        ui_widgets.button(path_row, text=_("Copiar"),
                          command=lambda: self._copy_ui_value(root, self.data_dir)).grid(
                              row=0, column=1, sticky="e")
        measure_path = tkfont.Font(root=path_label, font=ui.mono_font()).measure
        def fit_path(event):
            # Keep the useful ends visible; Copy always uses the complete path.
            value = str(self.data_dir)
            budget = max(0, event.width - ui.space_sm)
            if measure_path(value) > budget:
                half = len(value) // 2
                while half and measure_path(value[:half] + "…" + value[-half:]) > budget:
                    half -= 1
                value = value[:half] + "…" + value[-half:] if half else "…"
            path_label.configure(text=value)
        path_label.bind("<Configure>", fit_path)

        table_card = ui_widgets.card(main, padding=ui.space_sm)
        table_card.grid(row=2, column=0, sticky="nsew")
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(0, weight=1)
        table_shell = ui_widgets.list_frame(table_card)
        table_shell.grid(row=0, column=0, sticky="nsew")
        table_shell.grid_columnconfigure(0, weight=1)
        table_shell.grid_rowconfigure(0, weight=1)
        columns = ("backup", "texts", "lists", "size")
        tree = ttk.Treeview(
            table_shell,
            columns=columns,
            show="headings",
            height=12,
            style="Manager.Treeview",
        )
        for column, label, width, anchor in (
            ("backup", _("Quando"), 300, "w"),
            ("texts", _("Textos"), 90, "e"),
            ("lists", _("Listas"), 90, "e"),
            ("size", _("Tamanho"), 90, "e"),
        ):
            tree.heading(column, text=label, anchor=anchor)
            tree.column(column, width=ui.px(width), anchor=anchor,
                        stretch=column == "backup")
        tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ui_widgets.scrollbar(table_shell, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Maps tree row id -> backup path.
        row_paths = {}
        summary = tk.StringVar(main)
        tk.Label(main, textvariable=summary, font=ui.caption_font(),
                 bg=ui.surface, fg=ui.text_muted, anchor="w").grid(
                     row=4, column=0, sticky="ew", pady=(ui.space_sm, 0))

        def human_size(num_bytes):
            size = float(num_bytes)
            for unit in ("B", "KB", "MB"):
                if size < 1024 or unit == "MB":
                    return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
                size /= 1024
            return f"{size:.1f} MB"

        def refresh_backups():
            tree.delete(*tree.get_children())
            row_paths.clear()
            for path in list_backups(self.backups_dir):
                try:
                    size_bytes = os.path.getsize(path)
                except OSError:
                    size_bytes = 0
                try:
                    data = load_json_file(path)
                    if not isinstance(data, dict):
                        raise ValueError("not a library document")
                    snippets, _metadata = split_library_document(data)
                    lists = sum(key.startswith("_") and isinstance(value, dict)
                                for key, value in snippets.items())
                    texts = len(snippets) - lists
                    empty = not snippets
                except Exception:
                    texts = lists = _("inválido")
                    empty = False
                taken = backup_time(path)
                when = (taken.strftime("%d/%m/%Y %H:%M") + " · "
                        + time_format.relative_age(taken, datetime.now()))
                if empty:
                    when += " · " + _("0 itens")
                row = tree.insert(
                    "",
                    tk.END,
                    values=(when, texts, lists, human_size(size_bytes)),
                )
                row_paths[row] = path
            summary.set(_("{count} backups disponíveis").format(count=len(row_paths))
                        if row_paths else _("Nenhum backup. Use Criar backup para proteger a biblioteca."))
            restore_button.configure(state=tk.DISABLED)

        def selected_backup():
            selection = tree.selection()
            if not selection:
                ui_widgets.alert(root, _("Restaurar backup"), _("Selecione um backup na lista."))
                return None
            return row_paths.get(selection[0])

        def on_restore():
            path = selected_backup()
            if not path:
                return
            counts, error = self.preview_restore(path)
            if error:
                ui_widgets.alert(root, _("Restaurar backup"), error, tone="danger")
                return
            taken = time_format.stamp_with_age(backup_time(path), datetime.now())
            if not ui_widgets.confirm(
                root,
                _("Restaurar backup"),
                _("Backup: {taken}\n{changes}\n\n"
                  "A biblioteca atual é trocada por este backup. Antes, ela é salva "
                  "em um novo backup.").format(
                    taken=taken, changes=self._change_counts_text(counts)),
                _("Restaurar backup"),
            ):
                return
            # The editors reload from the restored library; settle drafts first.
            if not self._resolve_manager_drafts(root):
                return
            ok, error = self.restore_backup(path)
            if ok:
                refresh_backups()
                self._refresh_manager_lists()
                self.receipt(
                    N_("Backup restaurado às {time}"),
                    time_format.absolute_stamp(backup_time(path), datetime.now()),
                    key="restore-backup",
                )
            else:
                ui_widgets.alert(
                    root, _("Restaurar backup"), _("Falha ao restaurar: {error}").format(error=error),
                    tone="danger",
                )

        def on_export():
            dest = filedialog.asksaveasfilename(
                parent=root,
                title=_("Exportar biblioteca"),
                defaultextension=".json",
                initialfile="snippets-export.json",
                filetypes=[("JSON", "*.json"), (_("Todos os arquivos"), "*.*")],
            )
            if not dest:
                return
            ok, error = self.export_library(dest)
            if ok:
                self.receipt(
                    N_("Biblioteca exportada às {time}"), os.path.basename(dest),
                    key="export-library",
                )
            else:
                ui_widgets.alert(
                    root, _("Exportar biblioteca"),
                    _("Falha ao exportar: {error}").format(error=error), tone="danger",
                )

        def on_import():
            src = filedialog.askopenfilename(
                parent=root,
                title=_("Importar biblioteca"),
                filetypes=[("JSON", "*.json"), (_("Todos os arquivos"), "*.*")],
            )
            if not src:
                return
            # One read: the counts the question shows describe what is applied.
            document, error = self.read_import_source(src)
            if not error:
                mode = self._ask_import_mode(root, os.path.basename(src), document)
                if mode is None or not self._resolve_manager_drafts(root):
                    return
                _ok, error = self.apply_import(document, mode)
            if not error:
                refresh_backups()
                self._refresh_manager_lists()
                self.receipt(
                    N_("Biblioteca importada às {time}"), os.path.basename(src),
                    key="import-library",
                )
            else:
                ui_widgets.alert(
                    root, _("Importar biblioteca"),
                    _("Falha ao importar: {error}").format(error=error), tone="danger",
                )

        def on_backup_now():
            created = self.backup_now()
            if created:
                refresh_backups()
                self.receipt(N_("Backup criado às {time}"), key="manual-backup")
            else:
                ui_widgets.alert(
                    root, _("Criar backup"), _("Falha ao criar backup. Verifique os logs."),
                    tone="danger",
                )

        self._manager_import_action = on_import
        buttons = tk.Frame(main, bg=ui.surface)
        buttons.grid(row=3, column=0, sticky="ew", pady=(ui.space_md, 0))
        ui_widgets.button(
            buttons, text=_("Criar backup"), command=on_backup_now,
            icon="add",
        ).pack(side=tk.LEFT, padx=(0, ui.space_sm))
        restore_button = ui_widgets.button(
            buttons, text=_("Restaurar"), command=on_restore, variant="accent", icon="restore",
            state=tk.DISABLED,
        )
        restore_button.pack(side=tk.LEFT, padx=(0, ui.space_sm))
        tree.bind("<<TreeviewSelect>>", lambda _event: restore_button.configure(
            state=tk.NORMAL if tree.selection() else tk.DISABLED))
        tree.bind("<Return>", lambda _event: on_restore() if tree.selection() else None)
        tree.bind("<Double-Button-1>", lambda _event: on_restore() if tree.selection() else None)
        for label, command, icon in (
            (_("Exportar…"), on_export, "export"),
            (_("Importar…"), on_import, "import"),
            (_("Abrir pasta"), self.open_data_folder, "folder"),
        ):
            ui_widgets.button(
                buttons, text=label, command=command, icon=icon,
            ).pack(side=tk.LEFT, padx=(0, ui.space_sm))
        ui_widgets.button(
            buttons, text=_("Atualizar"), command=refresh_backups, icon="refresh",
        ).pack(side=tk.RIGHT)

        refresh_backups()

        def capture_view():
            selected = next(iter(tree.selection()), "")
            focused = tree.focus()
            scroll = capture_tree_scroll(tree, row_keys={row: os.path.basename(path) for row, path in row_paths.items()})
            return {"selection": os.path.basename(row_paths.get(selected, "")),
                    "row_focus": os.path.basename(row_paths.get(focused, "")),
                    **scroll,
                    "focus": "list" if root.focus_get() is tree else ""}

        def restore_view(state):
            by_name = {os.path.basename(path): row for row, path in row_paths.items()}
            selected = by_name.get(state.get("selection"))
            focused = by_name.get(state.get("row_focus"))
            if selected is not None:
                tree.selection_set(selected)
            if focused is not None:
                tree.focus(focused)
            restore_tree_scroll(tree, state, row_keys={row: name for name, row in by_name.items()})
            if state.get("focus") == "list":
                tree.focus_set()
        self._manager_views["backups"] = (capture_view, restore_view)

    def _page_receipt(self, parent):
        """The status line at the bottom of a page that has no editor.

        Packed before the page's content, so its row is always reserved and a
        receipt never moves anything. It is the same line the editors have.
        """
        ui = ui_theme.theme()
        receipt = ui_widgets.ReceiptLine(parent, "")
        receipt.frame.pack(
            side=tk.BOTTOM, fill=tk.X, padx=ui.space_lg, pady=(0, ui.space_sm))
        self._manager_receipts[str(parent)] = receipt
        return receipt

    def _persist_settings(self, updates):
        """Save settings.json with ``updates`` applied; publish only on success."""
        updated = {**self.settings, **updates}
        if not save_settings(self.settings_file, updated):
            return False
        self.settings = updated
        return True

    @staticmethod
    def _copy_ui_value(owner, value):
        owner.clipboard_clear()
        owner.clipboard_append(str(value))

    def _create_settings_tab(self, parent, root):
        """Configurações tab: one section at a time, chosen from a side nav."""
        ui = ui_theme.theme()
        self._page_receipt(parent)
        main = tk.Frame(ui_widgets.page_viewport(parent), bg=ui.surface, padx=ui.space_lg, pady=ui.space_lg)
        main.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            main,
            text=_("Configurações"),
            font=ui.title_font(),
            bg=ui.surface,
            fg=ui.text,
        ).pack(anchor="w")
        tk.Label(
            main,
            text=_("Ajuste a aparência, a expansão e os atalhos do SnipType."),
            font=ui.caption_font(),
            bg=ui.surface,
            fg=ui.text_muted,
        ).pack(anchor="w", pady=(ui.space_xs, ui.space_md))

        body = tk.Frame(main, bg=ui.surface)
        body.pack(fill=tk.BOTH, expand=True)
        nav = tk.Frame(body, bg=ui.surface)
        nav.pack(side=tk.LEFT, fill=tk.Y, padx=(0, ui.space_lg))
        content = tk.Frame(body, bg=ui.surface)
        content.pack(side=tk.LEFT, fill=tk.Y)
        body.bind("<Configure>", lambda event: content.configure(
            width=min(ui.px(720), max(ui.px(300), event.width - nav.winfo_reqwidth() - ui.space_lg))))
        content.pack_propagate(False)
        sections = SectionSwitcher(ui, nav, content)
        self._manager_settings_sections = sections
        general = sections.add("general", _("Geral"), icon="settings")
        hotkeys = sections.add("hotkeys", _("Atalhos"), icon="keyboard")
        data = sections.add("data", _("Dados"), icon="folder")
        general = self._settings_viewport(general)
        hotkeys = self._settings_viewport(hotkeys)
        data = self._settings_viewport(data)
        self._build_language_card(general, root)
        self._build_appearance_card(general, root)
        self._build_density_card(general, root)
        self._build_expansion_card(general)
        self._build_hotkeys_card(hotkeys, root)
        self._build_data_card(data)
        self._manager_views["settings"] = (
            lambda: {"selection": sections.current},
            lambda state: sections.select(state["selection"])
            if state.get("selection") in sections.frames else None,
        )
        for inner in (general, hotkeys, data):
            canvas = inner.master
            self._bind_mousewheel_descendants(inner, canvas)
            for child in self._widget_descendants(inner):
                child.bind("<FocusIn>", canvas.reveal_focus, add="+")

    @staticmethod
    def _widget_descendants(parent):
        for child in parent.winfo_children():
            yield child
            yield from Sniptype._widget_descendants(child)

    @staticmethod
    def _settings_viewport(parent):
        """Keep full-size settings controls reachable by wheel, scrollbar and Tab."""
        ui = ui_theme.theme()
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        canvas = tk.Canvas(parent, bg=ui.surface, highlightthickness=0, takefocus=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ui_widgets.scrollbar(parent, command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        inner = tk.Frame(canvas, bg=ui.surface)
        item = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))

        def reveal_focus(event):
            canvas.update_idletasks()
            top = event.widget.winfo_rooty() - inner.winfo_rooty()
            bottom = top + event.widget.winfo_height()
            visible_top = canvas.canvasy(0)
            height = canvas.winfo_height()
            margin = ui.space_sm
            target = None
            if top - margin < visible_top:
                target = top - margin
            elif bottom + margin > visible_top + height:
                target = bottom + margin - height
            if target is not None:
                canvas.yview_moveto(max(0, target) / max(1, inner.winfo_height()))

        canvas.reveal_focus = reveal_focus
        return inner

    def _settings_card(self, parent, title, description):
        """A titled settings card; content goes in grid rows 2+ (column 1 stretches)."""
        ui = ui_theme.theme()
        card = ui_widgets.card(parent, padding=(ui.space_lg, ui.space_md))
        card.pack(fill=tk.X, pady=(0, ui.space_md))
        card.grid_columnconfigure(1, weight=1)
        title_label = tk.Label(
            card,
            text=title,
            font=ui.subtitle_font(),
            bg=ui.card,
            fg=ui.text_strong,
        )
        title_label.grid(row=0, column=0, columnspan=3, sticky="w")
        description_label = tk.Label(
            card,
            text=description,
            font=ui.caption_font(),
            bg=ui.card,
            fg=ui.text_muted,
            anchor="w",
            justify="left",
            wraplength=640,
        )
        description_label.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(ui.space_xs, ui.space_sm))
        def wrap_labels(event):
            width = max(ui.px(180), event.width - 2 * ui.space_lg)
            ui_widgets.fit_label(title_label, width)
            ui_widgets.fit_label(description_label, width)
        card.bind("<Configure>", wrap_labels, add="+")
        return card

    def _build_language_card(self, parent, root):
        ui = ui_theme.theme()
        card = self._settings_card(
            parent,
            _("Idioma"),
            _("Idioma da interface do SnipType. O texto dos snippets não muda. A "
              "mudança recarrega o gerenciador sem reiniciar o SnipType."),
        )
        names = i18n.LANGUAGES
        display = tk.StringVar(card, names[i18n.language()])
        status = tk.StringVar(card, "")
        combo = ui_widgets.combobox(
            card,
            textvariable=display,
            values=tuple(names.values()),
            width=18,
        )
        combo.grid(row=2, column=0, sticky="w")
        tk.Label(
            card,
            textvariable=status,
            font=ui.caption_font(),
            bg=ui.card,
            fg=ui.text_muted,
            anchor="w",
        ).grid(row=2, column=1, sticky="w", padx=(ui.space_md, 0))

        def apply():
            choice = next((code for code, name in names.items() if name == display.get()), None)
            if choice is None or choice == i18n.language():
                return
            # The rebuild drops what the editors show: a draft is settled
            # first, and a clean manager applies without asking.
            if not self._resolve_manager_drafts(root):
                display.set(names[i18n.language()])
                status.set(_("Alteração cancelada; o rascunho foi mantido."))
                return
            if not self._persist_settings({"language": choice}):
                display.set(names[i18n.language()])
                status.set(_("Não foi possível salvar o idioma."))
                return
            i18n.set_language(choice)
            self.refresh_tray_menu()
            root.after_idle(lambda: self._reload_manager_window(root, settings_page=True))

        combo.bind("<<ComboboxSelected>>", lambda _event: apply())

    def _build_appearance_card(self, parent, root):
        ui = ui_theme.theme()
        card = self._settings_card(
            parent,
            _("Aparência"),
            _("Use o tema do sistema ou escolha uma aparência fixa. A mudança "
            "recarrega o gerenciador sem reiniciar o SnipType."),
        )
        current = ui_theme.preference()
        labels = {key: _(label) for key, label in ui_theme.APPEARANCE_LABELS.items()}
        display = tk.StringVar(card, current)
        status = tk.StringVar(card, _(ui_theme.APPEARANCE_STATUS[current]))
        choices = tk.Frame(card, bg=ui.card)
        choices.grid(row=2, column=0, columnspan=3, sticky="w")
        tk.Label(
            card,
            textvariable=status,
            font=ui.caption_font(),
            bg=ui.card,
            fg=ui.text_muted,
            anchor="w",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(ui.space_sm, 0))

        def apply():
            choice = display.get()
            if choice is None:
                status.set(_("Escolha uma aparência válida."))
                return
            if choice == ui_theme.preference():
                status.set(_(ui_theme.APPEARANCE_STATUS[choice]))
                return
            # The rebuild drops what the editors show: a draft is settled
            # first, and a clean manager applies without asking.
            if not self._resolve_manager_drafts(root):
                display.set(ui_theme.preference())
                status.set(_("Alteração cancelada; o rascunho foi mantido."))
                return
            if not self._persist_settings({"appearance": choice}):
                display.set(ui_theme.preference())
                status.set(_("Não foi possível salvar a aparência."))
                return
            ui_theme.set_preference(choice)
            root.after_idle(lambda: self._reload_manager_window(root, settings_page=True))

        for key, label in labels.items():
            ttk.Radiobutton(choices, text=label, variable=display, value=key,
                            command=apply).pack(side=tk.LEFT, padx=(0, ui.space_md))

    def _build_density_card(self, parent, root):
        ui = ui_theme.theme()
        card = self._settings_card(parent, _("Densidade"),
                                   _("Escolha o espaço dos controles e das linhas."))
        current = self.settings.get("density", "compact")
        display = tk.StringVar(card, current)
        status = tk.StringVar(card)
        def apply():
            choice = display.get()
            if choice == current:
                return
            if not self._resolve_manager_drafts(root):
                display.set(current)
                status.set(_("Alteração cancelada; o rascunho foi mantido."))
                return
            if not self._persist_settings({"density": choice}):
                display.set(current)
                status.set(_("Não foi possível salvar."))
                return
            ui_theme.set_density(choice)
            root.after_idle(lambda: self._reload_manager_window(root, settings_page=True))
        choices = tk.Frame(card, bg=ui.card)
        choices.grid(row=2, column=0, columnspan=3, sticky="w")
        for key, label in (("compact", _("Compacta")), ("comfortable", _("Confortável")),
                           ("touch", _("Toque"))):
            ttk.Radiobutton(choices, text=label, variable=display, value=key,
                            command=apply).pack(side=tk.LEFT, padx=(0, ui.space_md))
        tk.Label(card, textvariable=status, font=ui.caption_font(), bg=ui.card,
                 fg=ui.text_muted).grid(row=3, column=0, columnspan=3, sticky="w")

    def _reload_manager_window(self, window, *, settings_page=False):
        """Rebuild the manager in place so a new appearance or language takes effect. GUI thread.

        The rebuilt window keeps its size, the items its editors had open and
        its page, or opens on Configurações with ``settings_page``. Callers
        settle unsaved drafts first (see _resolve_manager_drafts).
        """
        tk_root = window.master
        view = self._capture_manager_view(window)
        self._release_manager_ui_refs()
        window.destroy()
        # Tk variables must be collected on this thread; see on_close.
        gc.collect()
        self._build_manager_window(tk_root)
        rebuilt = self.manager_window
        if rebuilt is None:
            return
        self._restore_manager_view(rebuilt, view)
        notebook = self._manager_notebook
        if settings_page and self._manager_settings_tab is not None:
            notebook.select(self._manager_settings_tab)

    def _build_expansion_card(self, parent):
        ui = ui_theme.theme()
        card = self._settings_card(
            parent,
            _("Expansão"),
            _("Por padrão, o snippet expande no último caractere do trigger. No modo "
            "terminador, ele só expande depois de um espaço ou sinal de pontuação, "
            "que continua no texto; Enter não conta. Grupos com regra própria mantêm a sua."),
        )
        enabled = tk.BooleanVar(card, bool(self.terminator_mode))
        status = tk.StringVar(card, "")

        def toggle():
            value = bool(enabled.get())
            if not self._persist_settings({"terminator_mode": value}):
                enabled.set(not value)
                status.set(_("Não foi possível salvar."))
                return
            self.terminator_mode = value
            self.refresh_runtime_indexes()
            status.set(_("Salvo."))

        ui_widgets.switch(
            card,
            text=_("Expandir só depois de espaço ou pontuação (modo terminador)"),
            variable=enabled,
            command=toggle,
        ).grid(row=2, column=0, columnspan=2, sticky="w")
        tk.Label(
            card,
            textvariable=status,
            font=ui.caption_font(),
            bg=ui.card,
            fg=ui.text_muted,
        ).grid(row=2, column=2, sticky="e")

    def _build_hotkeys_card(self, parent, root):
        from hotkey_dialog import ACTION_LABELS

        ui = ui_theme.theme()
        card = self._settings_card(
            parent,
            _("Atalhos de teclado"),
            _("Combinações opcionais para abrir o gerenciador, editar o último "
            "snippet expandido e pausar ou retomar a expansão."),
        )
        values = {}
        for row, action in enumerate(ACTIONS, 2):
            tk.Label(
                card,
                text=_(ACTION_LABELS.get(action, action)),
                font=ui.font(),
                bg=ui.card,
                fg=ui.text,
                anchor="w",
            ).grid(row=row, column=0, sticky="w", padx=(0, ui.space_lg), pady=2)
            value = tk.Label(card, font=ui.font(), bg=ui.card, anchor="w")
            value.grid(row=row, column=1, columnspan=2, sticky="w", pady=2)
            values[action] = value

        def refresh():
            bindings = self.settings.get("hotkeys", {})
            bindings = bindings if isinstance(bindings, dict) else {}
            for action, label in values.items():
                binding = bindings.get(action)
                label.configure(
                    text=display_hotkey(binding) or _("Desativado"),
                    fg=ui.text if binding else ui.text_muted,
                )

        def edit():
            self._show_hotkey_settings(root.master)
            if card.winfo_exists():
                refresh()

        refresh()
        ui_widgets.button(
            card, text=_("Editar atalhos…"), command=edit, icon="keyboard",
        ).grid(row=2 + len(ACTIONS), column=0, sticky="w", pady=(ui.space_sm, 0))

    def _build_data_card(self, parent):
        ui = ui_theme.theme()
        card = self._settings_card(
            parent,
            _("Pasta de dados"),
            _("Biblioteca, configurações, backups e logs ficam nesta pasta. Os "
            "backups são gerenciados em Cópias de segurança."),
        )
        mirror_dir = self.settings.get("mirror_dir")
        export_dir = self.settings.get("sync_export_dir")
        # (label, value, kind): the kind is the health vocabulary of what
        # happens there, "copy" for the mirror and "export" for the bundle.
        rows = (
            (_("Pasta de dados"), self.data_dir, None),
            (_("Cópia espelho"), mirror_dir or _("Desativada"), "copy" if mirror_dir else None),
            (_("Pacote de sincronização"), export_dir or _("Desativado"), "export" if export_dir else None),
        )
        transfers = []
        row = 2
        for label, value, kind in rows:
            tk.Label(
                card,
                text=label,
                font=ui.font(),
                bg=ui.card,
                fg=ui.text,
                anchor="w",
            ).grid(row=row, column=0, sticky="w", padx=(0, ui.space_lg), pady=2)
            path_label = tk.Label(card, text=value, anchor="w", font=ui.mono_font() if kind or value == self.data_dir
                                  else ui.font(), bg=ui.card, fg=ui.text, wraplength=ui.px(340))
            path_label.grid(row=row, column=1, sticky="ew", pady=2)
            ui_widgets.wrap_label(path_label)
            ui_widgets.button(card, text=_("Copiar"),
                              command=lambda value=value: self._copy_ui_value(card, value)).grid(
                                  row=row, column=2, sticky="e")
            row += 1
            if kind is not None:
                transfer = self._transfer_status(card, kind, value)
                transfer.frame.grid(
                    row=row, column=1, columnspan=2, sticky="ew", pady=(0, ui.space_xs))
                transfers.append(transfer.refresh)
                row += 1
        data_note = tk.Label(
            card,
            text=_("A cópia espelho e o pacote de sincronização são definidos em settings.json."),
            font=ui.caption_font(),
            bg=ui.card,
            fg=ui.text_muted,
            anchor="w",
        )
        data_note.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(ui.space_xs, 0))
        ui_widgets.wrap_label(data_note)
        ui_widgets.button(
            card, text=_("Abrir pasta"), command=self.open_data_folder, icon="folder",
        ).grid(row=row + 1, column=0, sticky="w", pady=(ui.space_sm, 0))

        def refresh():
            for refresh_transfer in transfers:
                refresh_transfer()

        self._manager_data_refresh = refresh

    def _transfer_status(self, card, kind, directory):
        """One line under a destination: what the last copy or export did.

        A good result is a quiet caption; a failure is a warning band that
        offers Abrir pasta (the destination, never created) and Tentar agora.
        Returns a namespace with ``frame`` and ``refresh()``.
        """
        ui = ui_theme.theme()
        frame = tk.Frame(card, bg=ui.card)
        frame.grid_columnconfigure(0, weight=1)
        quiet = tk.Label(
            frame, font=ui.caption_font(), bg=ui.card, fg=ui.text_muted, anchor="w",
            justify=tk.LEFT,
        )
        quiet.grid(row=0, column=0, sticky="ew")
        band = tk.Frame(frame, bg=ui.warning_bg, padx=ui.space_md, pady=ui.space_sm)
        band.grid(row=1, column=0, sticky="ew")
        message = tk.Label(
            band, font=ui.caption_font(), bg=ui.warning_bg, fg=ui.warning, anchor="w",
            justify=tk.LEFT,
        )
        message.pack(fill=tk.X)
        actions = tk.Frame(band, bg=ui.warning_bg)
        actions.pack(anchor="w", pady=(ui.space_sm, 0))
        gap = ui_widgets.face_gap(actions, ui.space_sm)
        ui_widgets.button(
            actions, text=_("Abrir pasta"), icon="folder",
            command=lambda: self._open_in_shell(os.path.expanduser(directory)),
        ).pack(side=tk.LEFT)
        ui_widgets.button(
            actions, text=_("Tentar agora"), icon="refresh",
            command=lambda: (self.retry_sync(), self._refresh_manager_health()),
        ).pack(side=tk.LEFT, padx=(gap, 0))

        def fit(event):
            message.configure(wraplength=max(ui.px(160), event.width - 2 * ui.space_md))
            quiet.configure(wraplength=event.width)

        frame.bind("<Configure>", fit, add="+")

        def refresh():
            record = self.last_mirror if kind == "copy" else self.last_sync
            text, failed = health_support.describe_transfer(kind, record, datetime.now())
            if failed:
                quiet.grid_remove()
                message.configure(text=text)
                band.grid()
            else:
                band.grid_remove()
                quiet.configure(text=text)
                quiet.grid()

        refresh()
        return types.SimpleNamespace(frame=frame, refresh=refresh)

    def _manager_brand_icon(self, window):
        """The app icon sized beside the sidebar title, or None if unavailable."""
        icon_path = self.resolve_resource_path("sniptype.ico")
        if not icon_path:
            return None
        # 18pt tracks the 14pt bold title across display scaling.
        size = max(16, round(window.winfo_fpixels("18p")))
        try:
            with Image.open(icon_path) as image:
                image = image.convert("RGBA").resize((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(image, master=window)
        except Exception as e:
            self.logger.warning(f"Falha ao carregar ícone do gerenciador: {e}")  # i18n: not ui
            return None

    def _set_window_icon(self, window):
        icon_path = self.resolve_resource_path("sniptype.ico")
        if not icon_path:
            return
        try:
            # ``default`` also covers every Toplevel created afterwards: the
            # group, form-editor and hotkey dialogs never set an icon and
            # showed Tk's feather.
            window.iconbitmap(icon_path, default=icon_path)
        except Exception:
            pass

    # Sidebar icons, in notebook page order.
    MANAGER_PAGE_ICONS = ("document", "tag", "lightning", "history", "settings")

    @classmethod
    def _build_manager_nav(cls, ui, nav, notebook):
        """One sidebar entry per notebook page, in tab order, tracking selection.

        Returns ``{tab_id: button}`` so page counts can relabel them.
        """
        items = {}
        for tab_id, icon in zip(notebook.tabs(), cls.MANAGER_PAGE_ICONS):
            items[str(tab_id)] = ui_widgets.nav_item(
                nav, notebook.tab(tab_id, "text"),
                lambda target=tab_id: notebook.select(target),
                icon=icon, ui=ui,
            )

        def highlight(_event=None):
            current = str(notebook.select())
            for tab_id, button in items.items():
                ui_widgets.set_selected(button, tab_id == current, ui)

        notebook.bind("<<NotebookTabChanged>>", highlight, add="+")
        highlight()
        return items

    def _configure_manager_styles(self, root):
        ui = ui_theme.theme()
        ui_theme.prepare_window(root, ui)
        style = ttk.Style(root)

        # The manager navigates from its sidebar: the notebook is only the
        # page container, with the tab strip removed so it costs no space.
        style.configure(
            "Pages.TNotebook", background=ui.surface, borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.layout("Pages.TNotebook.Tab", [])
        style.configure(
            "Manager.Treeview",
            background=ui.card,
            fieldbackground=ui.card,
            foreground=ui.text,
            font=ui.font(10),
            borderwidth=0,
            rowheight=ui.tree_row_height,
        )
        style.map(
            "Manager.Treeview",
            background=[("selected", "focus", ui.select_bg),
                        ("selected", "!focus", ui.surface_alt)],
            foreground=[("selected", ui.select_fg)],
        )
        style.configure(
            "Manager.Treeview.Heading",
            background=ui.card,
            foreground=ui.text_muted,
            font=ui.font(9, "bold"),
            padding=(8, 6),
        )
        style.layout("Manager.Treeview", style.layout("Treeview"))

    def _create_snippet_tree(self, shell, trigger_heading="Trigger",
                             trigger_share=0.36, trigger_min=76):
        """Build the trigger/preview Treeview used by the snippet lists.

        ``shell`` must be a grid container whose row 0 / column 0 expands.
        Measured cells fit the visible tree on every resize. Capabilities have
        their own marker column; groups appear when the manager has room.
        Mapping identifiers reserve more space for the composed trigger.
        """
        columns = ("trigger", "preview", "markers", "group")
        tree = ui_widgets.tree_list(
            shell,
            columns=columns,
            headings=True,
        )
        tree.heading("trigger", text=trigger_heading, anchor="w")
        tree.heading("preview", text=_("Valor"), anchor="w")
        tree.heading("markers", text=_("Recursos"), anchor="w")
        tree.heading("group", text=_("Grupo:"), anchor="w")
        tree.column("markers", width=ui_theme.theme().px(62), minwidth=0, stretch=False)
        tree.column("group", width=100, minwidth=0, stretch=False)
        tree.column("trigger", width=trigger_min, minwidth=0, anchor="w", stretch=False)
        tree.column("preview", width=100, minwidth=0, anchor="w", stretch=False)
        tree.grid(row=0, column=0, sticky="nsew")

        def fit_columns(event):
            # A couple of pixels for the tree's own border keep the last
            # column from spilling into a horizontal overflow.
            ui = ui_theme.theme()
            group_width = ui.px(100) if tree.winfo_toplevel().winfo_width() >= ui.px(1400) else 0
            tree.configure(displaycolumns=columns if group_width else columns[:3])
            fixed = ui.px(6) + ui.px(62) + group_width
            trigger, preview = split_tree_columns(event.width - 4, fixed, trigger_share, trigger_min, 60)
            tree.column("trigger", width=trigger)
            tree.column("preview", width=preview)
            tree.column("group", width=group_width)
            measure = tkfont.Font(root=tree, font=ui.font()).measure
            attached = set(tree.get_children())
            for item, values in list(tree.full_values.items()):
                if item not in attached:
                    continue
                if tree.exists(item):
                    tree.item(item, values=tuple(
                        ellipsize_text(value, max(0, tree.column(column, "width") - ui.px(10)), measure)
                        for column, value in zip(columns, values)))

        tree.full_values = {}
        tree.fit_cells = lambda: fit_columns(types.SimpleNamespace(width=tree.winfo_width()))
        tree.bind("<Configure>", fit_columns, add="+")

        scrollbar = ui_widgets.scrollbar(shell, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._bind_mousewheel(tree, tree)
        return tree

    def _insert_snippet_row(self, tree, key, value, row=None):
        """Project row capabilities and written runtime restrictions into cells."""
        _trigger, preview, _markers = snippet_row_values(key, value)
        markers = []
        if is_rich_text_payload(value):
            markers.append("A")
        if find_variable_names(extract_plain_text(value)):
            markers.append("ƒ")
        form = self._static_form_metadata(key) if row and row.kind == "static" else (
            self._mapping_form_metadata(row.container, key) if row and row.kind == "mapping" else None)
        if form:
            markers.append("▤")
        if row and row.favorite:
            markers.append("★")
        notes = []
        if row and not row.enabled:
            notes.append(_("Desativado (grupo)"))
        if row and row.shadowed:
            notes.append(_("Sobreposto por dinâmico"))
        if notes:
            preview = " · ".join(notes + [preview])
        values = (format_trigger_pair(row) if row else key, preview, " ".join(markers),
                  row.group_label if row and row.group_id else "")
        tree.full_values[key] = values
        tags = ("unavailable",) if notes else ()
        if tree.exists(key):
            tree.item(key, values=values, tags=tags)
            tree.move(key, "", tk.END)
        else:
            tree.insert("", tk.END, iid=key, values=values, tags=tags)

    def _register_manager_refresher(self, refresher):
        """Register a list-rebuild callback invoked after restore/import.

        Those operations rebind ``self.snippets`` wholesale, so every tab that
        renders it must repopulate or it silently shows the old library.
        """
        self._manager_refreshers.append(refresher)

    def _register_manager_editor(self, editor):
        """Register an editor tab's draft handle, asked before its draft is dropped.

        ``editor.dirty`` is the state last drawn; ``is_dirty()`` reads the
        widgets now; ``target()`` is the SnippetRef it shows, or None;
        ``resolve(owner)`` settles a draft (see _resolve_manager_drafts); and
        ``hold_rebuild(held)`` says whether its draft is holding back a System
        appearance change.
        """
        self._manager_editors.append(editor)

    def _resolve_manager_drafts(self, owner):
        """Settle every unsaved editor draft before the manager drops what it shows.

        Each dirty editor asks Salvar · Descartar · Cancelar. True when no
        draft is left, each one saved or discarded; False when the person
        cancelled or a save did not go through, and the caller stops.
        """
        return all(editor.resolve(owner) for editor in list(self._manager_editors))

    def _manager_title(self, *, dirty):
        """The manager's window title; a leading "• " says a draft is unsaved."""
        title = _("{PRODUCT_NAME} — Biblioteca").format(PRODUCT_NAME=PRODUCT_NAME)
        return f"• {title}" if dirty else title

    def _refresh_manager_title(self):
        window = self.manager_window
        if window is None:
            return
        window.title(self._manager_title(
            dirty=any(editor.dirty for editor in self._manager_editors)))

    def _stop_system_appearance_poll(self, window):
        poll = getattr(self, "_manager_appearance_poll", None)
        if poll is not None and poll[0] is window:
            window.after_cancel(poll[1])
            self._manager_appearance_poll = None

    def _start_system_appearance_poll(self, window):
        """Follow live Windows theme changes while ``window`` is open.

        Only the System preference follows them (ui_theme.live_system_kind).
        The check reschedules itself on ``window`` and is cancelled when the
        window is destroyed, so it never runs against a closed manager.
        """
        self._stop_system_appearance_poll(window)
        if not window.winfo_viewable():
            return
        def tick():
            if not window.winfo_viewable():
                self._manager_appearance_poll = None
                return
            self._manager_appearance_poll = (
                window, window.after(SYSTEM_APPEARANCE_POLL_MS, tick))
            self._check_system_appearance(window)

        def stop(event):
            if event.widget is window:
                self._stop_system_appearance_poll(window)

        if not getattr(window, "_sniptype_poll_bound", False):
            window.bind("<Destroy>", stop, add="+")
            window._sniptype_poll_bound = True
        self._manager_appearance_poll = (window, window.after(SYSTEM_APPEARANCE_POLL_MS, tick))

    def _check_system_appearance(self, window):
        """Rebuild ``window`` in the Windows theme that System now resolves to.

        It waits while the window is hidden or a prompt is open, and a dirty
        editor holds the rebuild, saying so, until its draft is saved or
        discarded: a rebuild would drop it.
        """
        wanted = ui_theme.live_system_kind()
        pending = wanted is not None and wanted != window.theme_kind
        if ui_theme.theme().system == "windows":
            pending = pending or ui_theme.windows_text_scale() != getattr(window, "theme_text_scale", 1.0)
            if wanted == "contrast" and window.theme_kind == "contrast":
                pending = pending or ui_theme.windows_contrast_signature(window) != window.theme_contrast_signature
        held = pending and any(editor.is_dirty() for editor in self._manager_editors)
        for editor in self._manager_editors:
            editor.hold_rebuild(held and editor.dirty)
        if not pending or held:
            return
        if window is not self.manager_window or not window.winfo_viewable():
            return
        if window.grab_current() is not None:
            return
        self._reload_manager_window(window)

    @staticmethod
    def _shortcut_hint(widget, receipt, text):
        """Temporarily show a control's keys without replacing a newer receipt."""
        owner = object()
        state = {"receipt": None, "sources": set()}
        def show(_event, source):
            current = receipt() if callable(receipt) else receipt
            if current is None:
                return
            if state["receipt"] is not None and state["receipt"] is not current:
                state["receipt"].hide_hint(owner)
            state["receipt"] = current
            state["sources"].add(source)
            current.show_hint(owner, text)
        def hide(_event, source):
            state["sources"].discard(source)
            if not state["sources"] and state["receipt"] is not None:
                state["receipt"].hide_hint(owner)
                state["receipt"] = None
        for sequence, source in (("<Enter>", "hover"), ("<FocusIn>", "focus")):
            widget.bind(sequence, lambda event, key=source: show(event, key), add="+")
        for sequence, source in (("<Leave>", "hover"), ("<FocusOut>", "focus")):
            widget.bind(sequence, lambda event, key=source: hide(event, key), add="+")
        def release(_event):
            state["sources"].clear()
            hide(None, "destroy")
        widget.bind("<Destroy>", release, add="+")

    def _register_manager_commands(self, page, search, tree, *, new, save, delete,
                                   escape, search_key, duplicate=None, rename=None):
        """Register the existing page actions, without owning editor state."""
        self._manager_commands[str(page)] = {
            "new": new, "save": save, "delete": delete, "escape": escape,
            "duplicate": duplicate, "rename": rename, "search": search, "tree": tree,
        }

        def enter_list(_event):
            self._flush_manager_search(search_key)
            children = tree.get_children()
            if children:
                selected = tree.selection()
                key = selected[0] if selected else children[0]
                tree.selection_set(key)
                tree.focus(key)
                tree.see(key)
                tree.focus_set()
            return "break"

        search.bind("<Down>", enter_list)
        search.bind("<Return>", enter_list)

    def _bind_manager_commands(self, root, notebook):
        def allowed(event):
            return event.widget.winfo_toplevel() is root and root.grab_current() is None

        def dispatch(name, event):
            # Toplevel bindings otherwise see Text's Ctrl+N/Ctrl+D only after
            # its class binding has already moved or deleted text.
            if not allowed(event):
                return None
            commands = self._manager_commands.get(notebook.select(), {})
            if name == "delete" and event.widget is not commands.get("tree"):
                return None
            action = commands.get(name)
            if action is not None:
                action()
            return "break"

        bindings = {
            "<Control-n>": "new", "<Control-s>": "save", "<Control-d>": "duplicate",
            "<F2>": "rename", "<Delete>": "delete", "<Escape>": "escape",
        }
        # A bindtag starting with '.' is parsed as a widget path by Tcl.
        tag = "ManagerCommands:" + str(root)
        for sequence, command in bindings.items():
            root.bind_class(tag, sequence, lambda event, name=command: dispatch(name, event))
        def global_command(event, action):
            if not allowed(event):
                return None
            action()
            return "break"
        root.bind_class(tag, "<Control-k>", lambda event: global_command(event, lambda: self._show_manager_switcher(root)))
        root.bind_class(tag, "<Control-e>", lambda event: global_command(event, self.edit_last_snippet))
        root.bind_class(tag, "<Control-slash>", lambda event: global_command(event, lambda: self._show_manager_keyboard_map(root)))
        def focus_search(_event):
            if not allowed(_event):
                return None
            entry = self._manager_search_entries.get(notebook.select())
            if entry is not None:
                entry.focus_set()
                entry.selection_range(0, tk.END)
            return "break"
        root.bind_class(tag, "<Control-f>", focus_search)

        def install(widget):
            tags = widget.bindtags()
            if tag in tags:
                return
            widget.bindtags((tags[0], tag, *tags[1:]))
            for child in widget.winfo_children():
                if not isinstance(child, tk.Toplevel):
                    install(child)
        install(root)
        # Editor notices rebuild their action controls after library changes.
        # Each new child inherits this Map handler from the toplevel. Already
        # installed parents need no repeated subtree walk when shown again.
        root.bind("<Map>", lambda event: install(event.widget)
                  if event.widget.winfo_toplevel() is root else None, add="+")
        edit_last = self._manager_edit_last_control
        self._shortcut_hint(edit_last, lambda: self._manager_receipts.get(notebook.select()),
                            _("Ctrl+E — Editar último"))

    @staticmethod
    def _escape_manager_editor(root, search, dirty, question, revert):
        if search.get():
            search.set("")
        elif dirty() and ui_widgets.confirm(
            root, _("Alterações não salvas"), question(), _("Descartar"), danger=True,
        ) == ui_widgets.PRIMARY:
            revert()

    @staticmethod
    def _show_manager_keyboard_map(root):
        ui_widgets.alert(
            root, _("Teclado do gerenciador"),
            _("Ctrl+N — Novo com a busca\nCtrl+S — Salvar\nCtrl+D — Duplicar item salvo\n"
              "F2 — Renomear texto / focar identificador\nDelete — Excluir na lista (Desfazer disponível)\n"
              "Esc — Limpar busca / descartar rascunho com confirmação\n"
              "Ctrl+K — Alternar snippet\nCtrl+E — Editar último\nCtrl+F — Buscar\n"
              "Ctrl+1–5 — Seções\n↓ / Enter na busca — Focar lista\n"
              "Tab / Shift+Tab — Próximo / anterior\nCtrl+Tab — Inserir tabulação\n"
              "Ctrl+Shift+R — Referência\nCtrl+Shift+V — Área de transferência\n"
              "Ctrl+Shift+F — Campo de formulário\nCtrl+Shift+X — Limpar formato\n"
              "Ctrl+B / I / U — Negrito / itálico / sublinhado\n"
              "Ctrl+Shift+C / S — Código / tachado"), tone="info",
        )

    def _show_manager_switcher(self, root):
        """Navigate local rows by stable reference, without expanding content."""
        if root.grab_current() is not None:
            return
        ui = ui_theme.theme()
        opener = root.focus_get()
        picker = tk.Toplevel(root)
        picker.title(_("Alternar snippet"))
        picker.transient(root)
        picker.geometry("680x430")
        ui_theme.prepare_window(picker, ui)
        body = tk.Frame(picker, bg=ui.surface, padx=ui.space_md, pady=ui.space_md)
        body.pack(fill=tk.BOTH, expand=True)
        query = tk.StringVar(picker)
        entry = ui_widgets.entry(body, textvariable=query)
        entry.pack(fill=tk.X, pady=(0, ui.space_sm))
        ui_widgets.search_hint(entry, _("Pesquisar snippets"))
        tree = ui_widgets.tree_list(body, columns=("kind", "trigger", "preview"), headings=True)
        tree.heading("kind", text=_("Tipo"))
        tree.heading("trigger", text=_("Trigger"))
        tree.heading("preview", text=_("Prévia"))
        tree.column("kind", width=110, stretch=False)
        tree.column("trigger", width=160, stretch=False)
        tree.column("preview", width=280)
        kind_labels = {"static": _("Texto"), "mapping": _("Mapeamento"), "dynamic": _("Ação dinâmica")}
        rows = self._manager_rows()
        projection = self._manager_static_projection()
        displayed = []
        row_iids = {row.ref: str(index) for index, row in enumerate(rows)}
        iid_rows = {row_iids[row.ref]: row for row in rows}

        def close():
            job = self._manager_search_jobs.pop("switcher", None)
            if job is not None:
                job[0].after_cancel(job[1])
            self._manager_pending_search.pop("switcher", None)
            picker.grab_release()
            picker.destroy()
            if opener is not None and opener.winfo_exists():
                opener.focus_force()

        def refresh(*_args):
            displayed[:] = search_manager_rows(rows, query.get(), projection)
            attached = tree.get_children()
            if attached:
                tree.detach(*attached)
            tree.selection_remove(tree.selection())
            for row in displayed:
                iid = row_iids[row.ref]
                preview = manager_row_preview(row, projection).replace("\n", " ")[:120]
                if tree.exists(iid):
                    tree.move(iid, "", tk.END)
                else:
                    tree.insert("", tk.END, iid=iid, values=(
                        kind_labels[row.kind], row.effective_trigger, preview))
            if displayed:
                first = row_iids[displayed[0].ref]
                tree.selection_set(first)
                tree.focus(first)
            create.configure(text=_("Criar \"{query}\"").format(query=query.get().strip()),
                             state=tk.NORMAL if not displayed and query.get().strip() else tk.DISABLED)
            if displayed or not query.get().strip():
                create.pack_forget()
            else:
                # Reserve the empty-state action before the list takes the
                # remaining height, just like the dialog footer.
                create.pack(side=tk.BOTTOM, fill=tk.X, pady=(ui.space_sm, 0), before=tree)

        def choose(_event=None):
            self._flush_manager_search("switcher")
            selection = tree.selection()
            if selection:
                target = iid_rows[selection[0]].ref
                if not self._resolve_manager_drafts(root):
                    return "break"
                close()
                self._select_manager_target(target)
                commands = self._manager_commands.get(self._manager_notebook.select(), {})
                if commands.get("tree") is not None:
                    commands["tree"].focus_set()
            elif query.get().strip():
                create_new()
            return "break"

        def create_new():
            self._flush_manager_search("switcher")
            if displayed or not query.get().strip():
                return
            value = query.get().strip()
            if not self._resolve_manager_drafts(root):
                return
            close()
            # Creation has one home; a switcher search across other kinds still
            # opens a guarded new Textos draft, never an accidental provider.
            for page, commands in self._manager_commands.items():
                if commands.get("kind") == "static":
                    self._manager_notebook.select(page)
                    commands["new"](value)
                    break

        create = ui_widgets.button(body, _("Novo snippet"), create_new)
        ui_widgets.dialog_footer(body, (_("Abrir"), choose), close, ui=ui).pack(side=tk.BOTTOM, fill=tk.X)
        tree.pack(fill=tk.BOTH, expand=True)
        query.trace_add("write", lambda *_: self._schedule_manager_search(picker, "switcher", refresh))
        refresh()
        tree.bind("<Double-Button-1>", choose)
        def enter_list(_event):
            self._flush_manager_search("switcher")
            if displayed:
                tree.focus_set()
            return "break"
        entry.bind("<Down>", enter_list)
        picker.protocol("WM_DELETE_WINDOW", close)
        center_dialog(picker, root)
        picker.grab_set()
        entry.focus_force()

    def _release_manager_ui_refs(self):
        """Drop widget callbacks while still running on the GUI thread."""
        window = self.manager_window
        if window is not None:
            self._stop_system_appearance_poll(window)
            self._cancel_manager_search(window, discard=True)
        self._manager_views = {}
        self._manager_last_expansion_var = None
        self._manager_notebook = None
        self._manager_status_var = None
        self._manager_status_label = None
        self._manager_status_icon = None
        self._manager_toggle_button = None
        self._manager_health = None
        self._manager_data_refresh = None
        self._manager_visible = False
        self._manager_receipts = {}
        self._manager_pages = {}
        self._manager_search_entries = {}
        self._manager_commands = {}
        self._manager_edit_last_control = None
        self._manager_settings_tab = None
        self._manager_settings_sections = None
        self.manager_window = None
        self._manager_refreshers = []
        self._manager_editors = []
        self._manager_tab_selectors = {}
        self._manager_preview_controller = None
        self._manager_import_action = None

    def _refresh_manager_lists(self, _root=None):
        """Rebuild every registered list and the InfoBar, which reads the library's state.

        ``_root`` is the arg the GuiThread pump passes.
        """
        for refresher in [*self._manager_refreshers, self._refresh_manager_health, self._refresh_edit_last]:
            try:
                refresher()
            except Exception as e:
                self.logger.warning(f"Falha ao atualizar lista do gerenciador: {e}")

    def _bind_mousewheel(self, widget, target=None):
        scroll_target = target or widget

        def on_mousewheel(event):
            if getattr(event, "delta", 0):
                steps = -1 if event.delta > 0 else 1
            elif getattr(event, "num", None) == 4:
                steps = -1
            elif getattr(event, "num", None) == 5:
                steps = 1
            else:
                return None
            scroll_target.yview_scroll(steps, "units")
            return "break"

        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, on_mousewheel, add="+")

    def _bind_mousewheel_descendants(self, parent, target=None):
        self._bind_mousewheel(parent, target)
        for child in parent.winfo_children():
            self._bind_mousewheel_descendants(child, target)

    def _open_notification_history(self, root):
        ui = ui_theme.theme()
        history_window = tk.Toplevel(root)
        history_window.title(_("Histórico de notificações"))
        history_window.geometry("720x380")
        history_window.minsize(560, 280)
        history_window.configure(bg=ui.surface)
        history_window.transient(root)
        self._set_window_icon(history_window)
        ui_theme.prepare_window(history_window, ui)

        outer = tk.Frame(history_window, bg=ui.surface, padx=14, pady=14)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        header = tk.Frame(outer, bg=ui.surface)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        tk.Label(
            header,
            text=_("Últimas notificações"),
            font=ui.subtitle_font(),
            bg=ui.surface,
            fg=ui.text,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        only_errors = tk.BooleanVar(history_window, False)
        ui_widgets.checkbox(
            header, text=_("Somente erros"), variable=only_errors,
            command=lambda: fill(),
        ).grid(row=0, column=1, sticky="e")

        table_card = ui_widgets.card(outer, padding=ui.space_sm)
        table_card.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(0, weight=1)
        frame = ui_widgets.list_frame(table_card)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        columns = ("time", "kind", "message")
        # The icon column carries the error mark, so a failure is told apart by
        # shape and the word "Erro" as well as by its color.
        tree = ttk.Treeview(
            frame, columns=columns, show="tree headings", height=12, style="Manager.Treeview")
        tree.heading("#0", text="")
        tree.heading("time", text=_("Quando"), anchor="w")
        tree.heading("kind", text=_("Tipo"), anchor="w")
        tree.heading("message", text=_("Mensagem"), anchor="w")
        tree.column("#0", width=ui.px(32), minwidth=ui.px(32), anchor="w", stretch=False)
        tree.column("time", width=ui.px(140), anchor="w", stretch=False)
        tree.column("kind", width=ui.px(80), anchor="w", stretch=False)
        tree.column("message", width=ui.px(400), anchor="w")
        tree.tag_configure("error", foreground=ui.danger)
        error_icon = ui_widgets.signal_image(history_window, ui.danger, "error", ui=ui)
        history_window.error_icon = error_icon

        scrollbar = ui_widgets.scrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        empty_label = tk.Label(
            frame, font=ui.caption_font(), bg=ui.card, fg=ui.text_muted, justify="center")
        empty_label.grid(row=0, column=0, sticky="nsew")

        entries = list(reversed(self.notification_history))

        def fill():
            tree.delete(*tree.get_children())
            errors_only = bool(only_errors.get())
            now = datetime.now()
            for entry in entries:
                kind = entry.get("kind", "info")
                if errors_only and kind != "error":
                    continue
                is_error = kind == "error"
                tree.insert(
                    "",
                    tk.END,
                    image=error_icon if is_error else "",
                    values=(
                        notification_stamp(entry, now),
                        _(NOTIFICATION_KIND_LABELS.get(kind, kind)),
                        entry.get("message", ""),
                    ),
                    tags=("error",) if is_error else (),
                )
            if tree.get_children():
                tree.tkraise()
                return
            empty_label.configure(
                text=_("Nenhum erro registrado.") if errors_only
                else _("Nenhuma notificação registrada ainda."))
            empty_label.tkraise()

        fill()
        self._bind_mousewheel(tree, tree)
        history_window.bind("<Escape>", lambda _event: history_window.destroy())
        center_dialog(history_window, root)


    def _editor_header(self, parent, on_reveal):
        """The lines under an editor's title: what it edits, whether that is saved, and why.

        Returns a namespace with ``frame`` (grid it), ``show(target, dirty,
        detail, reveal)``, where ``reveal`` offers Mostrar na lista
        (``on_reveal``) for an item the list filter hides, and ``notice(kind,
        text, actions)``, a warning bar under them with ``(label, command)``
        actions; ``notice(None)`` hides it and ``notice_kind()`` says which
        one is up.
        """
        ui = ui_theme.theme()
        background = ui_widgets.surface_of(parent)
        frame = tk.Frame(parent, bg=background)
        frame.grid_columnconfigure(2, weight=1)
        target = tk.Label(frame, font=ui.font(), bg=background, fg=ui.text, anchor="w", justify=tk.LEFT)
        target.grid(row=0, column=0, sticky="w")
        state = tk.Label(
            frame, text=_("• Não salvo"), font=ui.font(10, "bold"), bg=background, fg=ui.text,
            anchor="w",
        )
        state.grid(row=0, column=1, sticky="w", padx=(ui.space_sm, 0))
        reveal = ui_widgets.button(frame, text=_("Mostrar na lista"), command=on_reveal)
        reveal.grid(row=0, column=3, sticky="e")
        # The row keeps the button's height, so revealing it moves nothing below.
        frame.grid_rowconfigure(0, minsize=reveal.winfo_reqheight())
        detail = tk.Label(
            frame, font=ui.caption_font(), bg=background, fg=ui.text_muted, anchor="w",
            justify=tk.LEFT,
        )
        detail.grid(row=1, column=0, columnspan=4, sticky="ew")
        bar = tk.Frame(frame, bg=ui.warning_bg, padx=ui.space_md, pady=ui.space_sm)
        bar.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(ui.space_sm, 0))
        message = tk.Label(
            bar, font=ui.font(), bg=ui.warning_bg, fg=ui.warning, anchor="w", justify=tk.LEFT,
        )
        message.pack(fill=tk.X)
        actions = tk.Frame(bar, bg=ui.warning_bg)
        actions.pack(anchor="w", pady=(ui.space_sm, 0))
        shown = {"notice": None}

        def fit(event):
            width = event.width
            target.configure(wraplength=max(
                ui.px(120), width - state.winfo_reqwidth() - reveal.winfo_reqwidth() - ui.space_sm))
            detail.configure(wraplength=width)
            message.configure(wraplength=max(ui.px(120), width - 2 * ui.space_md))

        frame.bind("<Configure>", fit, add="+")

        def show(target_text, dirty, detail_text="", reveal_item=False):
            target.configure(text=target_text)
            if dirty:
                state.grid()
            else:
                state.grid_remove()
            if reveal_item:
                reveal.grid()
            else:
                reveal.grid_remove()
            detail.configure(text=detail_text)

        def notice(kind, text=None, choices=()):
            for child in actions.winfo_children():
                child.destroy()
            shown["notice"] = kind
            if kind is None:
                bar.grid_remove()
                return
            message.configure(text=text)
            gap = ui_widgets.face_gap(actions, ui.space_sm)
            for index, (label, command) in enumerate(choices):
                ui_widgets.button(actions, text=label, command=command).pack(
                    side=tk.LEFT, padx=(0 if index == 0 else gap, 0))
            bar.grid()

        show("", False)
        notice(None)
        return types.SimpleNamespace(
            frame=frame, show=show, notice=notice, notice_kind=lambda: shown["notice"],
        )

    def _editor_handle(self, root, header, *, is_dirty, save, revert, question, target):
        """The draft handle an editor tab registers (see _register_manager_editor).

        ``save()`` answers whether the draft was written, ``revert()`` drops
        it, ``question()`` names what holds unsaved changes and ``target()``
        is the SnippetRef the editor shows. The tab keeps ``dirty`` current.
        """
        def resolve(owner=root):
            if not is_dirty():
                return True
            choice = ui_widgets.confirm(
                owner,
                _("Alterações não salvas"),
                question() + "\n\n" + _("Salvar grava as alterações e continua; "
                                        "Descartar continua sem elas."),
                _("Salvar"),
                extra=_("Descartar"),
                extra_danger=True,
            )
            if choice == ui_widgets.PRIMARY:
                return save()
            if choice == ui_widgets.EXTRA:
                revert()
                return True
            return False

        def apply_appearance_now():
            window = self.manager_window
            if window is not None and self._resolve_manager_drafts(window):
                # Not from inside this button's own command: the rebuild
                # destroys it.
                window.after_idle(lambda: self._reload_manager_window(window))

        def hold_rebuild(held):
            kind = header.notice_kind()
            if held and kind is None:
                header.notice(
                    "appearance",
                    _("O tema do Windows mudou. O gerenciador troca de tema quando este "
                      "rascunho for salvo ou descartado."),
                    ((_("Aplicar agora"), apply_appearance_now),),
                )
            elif not held and kind == "appearance":
                header.notice(None)

        return types.SimpleNamespace(
            dirty=False, is_dirty=is_dirty, target=target, resolve=resolve,
            hold_rebuild=hold_rebuild,
        )

    @staticmethod
    def _show_library_conflict(header, outcome, name, use_library, keep_draft):
        """Say that the library changed under an open draft, with both ways out."""
        if outcome == EDITOR_GONE:
            text = _("A biblioteca mudou: {name} não existe mais.").format(name=name)
            first = _("Descartar rascunho")
        else:
            text = _("A biblioteca mudou: {name} tem uma versão salva mais nova.").format(name=name)
            first = _("Usar a versão nova")
        header.notice(
            "library", text, ((first, use_library), (_("Manter rascunho"), keep_draft)))

    def _create_formatting_toolbar(self, parent, text_widget, on_change=None):
        """Add basic rich-text controls above a Tk text editor.

        Returns ``(update, request_update)``: ``update`` re-reads the editor
        at once, ``request_update`` once the pending events are handled.
        ``on_change`` receives the serialized content after every update,
        which covers typing, pasting, formatting and programmatic inserts.
        """
        configure_rich_text_widget(text_widget)

        ui = ui_theme.theme()
        toolbar = tk.Frame(parent, **ui.toolbar_frame_colors())
        toolbar.pack(fill=tk.X, pady=(0, 6))
        # Where the buttons alone fill the row, the status gets its own line
        # below rather than pushing the last button off the pane.
        status_row = tk.Frame(parent, **ui.toolbar_frame_colors())
        status_row.pack(fill=tk.X, pady=(0, 4))

        status_var = tk.StringVar(value=_("Formato: texto simples"))

        def show_format(payload):
            if isinstance(payload, dict):
                status_var.set(_("Formato: HTML + RTF"))
            else:
                status_var.set(_("Formato: texto simples"))

        def update_status(*_args):
            payload = serialize_text_widget_content(text_widget)
            show_format(payload)
            if on_change is not None:
                on_change(payload)

        # Serializing walks every character, so the events of one keystroke
        # (the edit, then the key release) share one update at idle time.
        pending = {"id": None}

        def run_pending():
            pending["id"] = None
            update_status()

        def request_update(*_args):
            if pending["id"] is None:
                pending["id"] = text_widget.after_idle(run_pending)

        def on_modified(_event):
            # <<Modified>> fires only when the flag rises, so it is lowered
            # again to hear the next edit; lowering it fires once more.
            if not text_widget.edit_modified():
                return
            text_widget.edit_modified(False)
            request_update()

        def cancel_pending(event):
            if event.widget is text_widget and pending["id"] is not None:
                text_widget.after_cancel(pending["id"])
                pending["id"] = None

        def apply_style(style_name):
            if not toggle_text_style(text_widget, style_name):
                ui_widgets.alert(
                    text_widget, _("Formatação"), _("Selecione um trecho para formatar."),
                    tone="info",
                )
                return
            update_status()
            text_widget.focus_set()

        def clear_styles_handler():
            clear_text_styles(text_widget)
            update_status()
            text_widget.focus_set()

        def bind_shortcut(sequence, style_name):
            def handler(event):
                apply_style(style_name)
                return "break"
            text_widget.bind(sequence, handler)

        button_base_font = tkfont.nametofont("TkDefaultFont").copy()
        icon_fonts = {
            "bold": button_base_font.copy(),
            "italic": button_base_font.copy(),
            "underline": button_base_font.copy(),
            "code": button_base_font.copy(),
            "strike": button_base_font.copy(),
            "clear": button_base_font.copy(),
        }
        icon_fonts["bold"].configure(weight="bold")
        icon_fonts["italic"].configure(slant="italic")
        icon_fonts["underline"].configure(underline=1)
        icon_fonts["code"].configure(family=ui.mono_family, weight="bold", size=max(9, button_base_font.cget("size") - 1))
        icon_fonts["strike"].configure(overstrike=1)
        icon_fonts["clear"].configure(family=ui.symbol_family, size=max(10, button_base_font.cget("size")))
        icon_fonts["var"] = button_base_font.copy()
        icon_fonts["var"].configure(family=ui.mono_family, size=max(8, button_base_font.cget("size") - 1))

        toolbar_bg = toolbar.cget("bg")

        def add_toolbar_button(label, handler, padx, tooltip, font_key, icon=None):
            if ui_widgets.uses_fluent(ui):
                # The letters stay as the label where no icon font exists.
                button = ui_widgets.button(
                    toolbar, text=label, variant="toolbar",
                )
            else:
                button = tk.Button(
                    toolbar,
                    text=label,
                    takefocus=0,
                    font=icon_fonts[font_key],
                    relief=tk.FLAT,
                    bd=0,
                    padx=0,
                    pady=0,
                    highlightthickness=0,
                    cursor="hand2",
                )

            def on_click(_event=None):
                handler()
                return "break"

            button.bind("<ButtonPress-1>", on_click)
            button.pack(side=tk.LEFT, padx=padx)
            button.bind("<Enter>", lambda _event: status_var.set(tooltip))
            button.bind("<Leave>", lambda _event: update_status())
            return button

        add_toolbar_button("B", lambda: apply_style("bold"), (0, 1), _("Formato: negrito"), "bold", "bold")
        add_toolbar_button("I", lambda: apply_style("italic"), 1, _("Formato: itálico"), "italic", "italic")
        add_toolbar_button("U", lambda: apply_style("underline"), 1, _("Formato: sublinhado"), "underline", "underline")
        add_toolbar_button("S", lambda: apply_style("strike"), 1, _("Formato: tachado"), "strike", "strike")
        add_toolbar_button("<>", lambda: apply_style("code"), 1, _("Formato: código monoespaçado"), "code", "code")
        add_toolbar_button(_("Limpar"), clear_styles_handler, 1, _("Formato: limpar estilos (Ctrl+Shift+X)"), "clear", "clear_format")

        # Separator before variable buttons
        tk.Frame(toolbar, width=1, bg=ui.divider).pack(side=tk.LEFT, padx=(8, 6), fill=tk.Y, pady=2)

        def _insert_variable_text(name):
            """Insert %%name%% at the cursor (or replace current selection)."""
            token = f"%%{name}%%"
            try:
                sel_start = text_widget.index(tk.SEL_FIRST)
                sel_end = text_widget.index(tk.SEL_LAST)
                text_widget.delete(sel_start, sel_end)
                text_widget.insert(sel_start, token)
            except tk.TclError:
                text_widget.insert(tk.INSERT, token)
            text_widget.focus_set()
            update_status()

        def _show_snippet_picker(parent_win, choices):
            """Searchable listbox dialog; calls _insert_variable_text on selection."""
            picker = tk.Toplevel(parent_win)
            picker.title(_("Inserir referência de snippet"))
            picker.geometry("320x400")
            picker.resizable(False, True)
            picker.transient(parent_win)
            picker.grab_set()

            picker.configure(bg=ui.surface)
            ui_theme.prepare_window(picker, ui)
            body = tk.Frame(picker, bg=ui.surface, padx=ui.space_md, pady=ui.space_md)
            body.pack(fill=tk.BOTH, expand=True)

            search_var = tk.StringVar()
            search_entry = ui_widgets.entry(body, textvariable=search_var)
            search_entry.pack(fill=tk.X, pady=(0, ui.space_sm))

            lf = ui_widgets.field_frame(body)
            lf.grid_columnconfigure(0, weight=1)
            lf.grid_rowconfigure(0, weight=1)

            listbox = ui_widgets.tree_list(lf)
            scrollbar = ui_widgets.scrollbar(lf, command=listbox.yview)
            listbox.config(yscrollcommand=scrollbar.set)
            listbox.grid(row=0, column=0, sticky="nsew")
            scrollbar.grid(row=0, column=1, sticky="ns")
            ui_widgets.track_focus(lf, listbox)

            displayed = list(choices)

            def refresh_list(*_args):
                nonlocal displayed
                query = search_var.get().strip().lower()
                displayed = [c for c in choices if query in c.lower()] if query else list(choices)
                listbox.delete(*listbox.get_children())
                for index, choice in enumerate(displayed):
                    listbox.insert("", tk.END, iid=str(index), text=choice)
                if displayed:
                    listbox.selection_set("0")
                    listbox.focus("0")

            search_var.trace_add("write", refresh_list)
            refresh_list()
            if displayed:
                listbox.selection_set(0)

            def confirm(*_args):
                sel = listbox.selection()
                if not sel:
                    return
                chosen = displayed[int(sel[0])]
                picker.destroy()
                _insert_variable_text(chosen)

            listbox.bind("<Double-Button-1>", confirm)
            # Enter inserts and Escape closes, from the search field or the
            # list; the footer is packed before the list so it is never clipped.
            ui_widgets.dialog_footer(
                body, (_("Inserir"), confirm), picker.destroy, ui=ui,
            ).pack(side=tk.BOTTOM, fill=tk.X, pady=(ui.space_md, 0))
            lf.pack(fill=tk.BOTH, expand=True)

            center_dialog(picker, parent_win)
            search_entry.focus_set()
            search_entry.bind("<Down>", lambda _event: (listbox.focus_set(), "break")[1])

        def insert_snippet_ref():
            # Every snippet kind is referenceable: static, runtime dynamic and
            # composed mapping triggers.
            names = {k for k in self.snippets if not k.startswith("_")}
            names |= composed_mapping_triggers(self.snippets)
            choices = sorted(names)
            if not choices:
                ui_widgets.alert(
                    text_widget, _("Variáveis"), _("Nenhum snippet disponível."), tone="info",
                )
                return
            _show_snippet_picker(text_widget.winfo_toplevel(), choices)

        def insert_clipboard_var():
            _insert_variable_text("clipboard-paste")

        def insert_form_field():
            name = ui_widgets.ask_text(
                text_widget,
                _("Campo de formulário"),
                _("Nome do campo"),
                validate=lambda value: None if value else _("Informe o nome do campo."),
                primary_label=_("Inserir"),
            )
            if name is not None:
                _insert_variable_text(name.replace(" ", "_"))

        variable_button = tk.Menubutton(
            toolbar, text=_("Inserir variável ▾"), font=ui.font(), bg=toolbar_bg, fg=ui.text,
            activebackground=ui.select_bg, activeforeground=ui.select_fg,
            relief=tk.FLAT, bd=0, padx=ui.space_sm, pady=0, takefocus=0,
        )
        variable_menu = ui_widgets.menu(variable_button, ui=ui)
        variable_button.configure(menu=variable_menu)
        variable_button.pack(side=tk.LEFT, padx=1)
        for label, shortcut, action in (
            (_("Referência"), "Ctrl+Shift+R", insert_snippet_ref),
            (_("Área de transferência"), "Ctrl+Shift+V", insert_clipboard_var),
            (_("Campo de formulário"), "Ctrl+Shift+F", insert_form_field),
        ):
            variable_menu.add_command(label=label, accelerator=shortcut, command=action)
        for sequence, action in (
            ("<Control-Shift-R>", insert_snippet_ref),
            ("<Control-Shift-V>", insert_clipboard_var),
            ("<Control-Shift-F>", insert_form_field),
            ("<Control-Shift-X>", clear_styles_handler),
        ):
            text_widget.bind(sequence, lambda _event, handler=action: (handler(), "break")[1])

        def traverse_text(backwards=False):
            target = text_widget.tk_focusPrev() if backwards else text_widget.tk_focusNext()
            if target is not None:
                target.focus_set()
            return "break"

        text_widget.bind("<Tab>", lambda _event: traverse_text())
        text_widget.bind("<Shift-Tab>", lambda _event: traverse_text(True))
        text_widget.bind("<ISO_Left_Tab>", lambda _event: traverse_text(True))
        text_widget.bind("<Control-Tab>", lambda _event: (text_widget.insert(tk.INSERT, "\t"), "break")[1])

        format_label = tk.Label(parent, textvariable=status_var, bg=toolbar_bg,
                                **ui.status_label_options())
        format_label.pack(in_=status_row, side=tk.LEFT)
        format_state = {"stacked": True}

        def fit_format_status(*_args):
            controls = sum(widget.winfo_reqwidth() + sum(map(int, widget.pack_info().get("padx", (0, 0))))
                           if isinstance(widget.pack_info().get("padx", 0), tuple)
                           else widget.winfo_reqwidth() + 2 * int(widget.pack_info().get("padx", 0))
                           for widget in toolbar.winfo_children())
            stacked = ui.stacked_toolbar_status or controls + format_label.winfo_reqwidth() + ui.space_md > toolbar.winfo_width()
            if stacked == format_state["stacked"]:
                return
            format_state["stacked"] = stacked
            format_label.pack_forget()
            if stacked:
                status_row.pack(fill=tk.X, pady=(0, 4), after=toolbar)
                format_label.pack(in_=status_row, side=tk.LEFT)
            else:
                status_row.pack_forget()
                format_label.pack(in_=toolbar, side=tk.RIGHT)

        toolbar.bind("<Configure>", fit_format_status, add="+")
        status_var.trace_add("write", fit_format_status)

        bind_shortcut("<Control-b>", "bold")
        bind_shortcut("<Control-i>", "italic")
        bind_shortcut("<Control-u>", "underline")
        text_widget.bind("<Control-Shift-C>", lambda event: (apply_style("code"), "break")[1])
        text_widget.bind("<Control-Shift-S>", lambda event: (apply_style("strike"), "break")[1])
        text_widget.bind("<KeyRelease>", request_update)
        text_widget.bind("<ButtonRelease-1>", request_update)
        text_widget.bind("<<Modified>>", on_modified, add="+")
        text_widget.bind("<Destroy>", cancel_pending, add="+")
        # The editor that owns ``on_change`` is still being built here.
        show_format(serialize_text_widget_content(text_widget))
        return update_status, request_update
    def _create_static_snippets_tab(self, parent, root, set_count=None):
        """Build the static snippets tab UI.

        ``set_count`` receives the library's snippet count whenever the list is
        rebuilt, so the navigation can show it; a search or filter narrows the
        list, not that count.
        """
        ui = ui_theme.theme()

        main = tk.Frame(
            ui_widgets.page_viewport(parent), bg=ui.surface, padx=ui.space_lg, pady=ui.space_lg
        )
        main.pack(fill=tk.BOTH, expand=True)
        # A uniform group splits by weight alone; otherwise grid sizes by
        # requested width and the editor's toolbars starve the list.
        main.grid_columnconfigure(0, weight=2, minsize=300, uniform="panes")
        main.grid_columnconfigure(1, weight=3, minsize=440, uniform="panes")
        main.grid_rowconfigure(2, weight=1)
        page_header = tk.Frame(main, bg=ui.surface)
        page_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, ui.space_sm))
        tk.Label(page_header, text=_("Textos"), font=ui.title_font(),
                 bg=ui.surface, fg=ui.text).pack(side=tk.LEFT)
        page_new = ui_widgets.button(page_header, text=_("Novo snippet"), icon="add", variant="accent")
        page_new.pack(side=tk.RIGHT)

        frame_left = ui_widgets.flat_pane(main)
        frame_left.grid(row=2, column=0, sticky="nsew", padx=(0, 1))
        tk.Frame(main, bg=ui.divider, width=1).grid(row=2, column=0, sticky="nse")
        frame_left.grid_columnconfigure(0, weight=1)
        frame_left.grid_rowconfigure(5, weight=1)

        # How many the list shows of how many there are: the navigation counts
        # the library, the list counts what the search and filters leave.
        count_var = tk.StringVar(frame_left)
        count_row = tk.Frame(frame_left, bg=ui.card)
        count_row.grid(row=0, column=0, sticky="ew")
        search_var = tk.StringVar()
        search_entry = ui_widgets.entry(count_row, textvariable=search_var, width=12)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, ui.space_xs))
        ui_widgets.search_hint(search_entry, _("Pesquisar snippets"))
        tk.Label(count_row, textvariable=count_var, font=ui.caption_font(),
                 bg=ui.card, fg=ui.text_muted).pack(side=tk.LEFT)
        clear_filter = ui_widgets.button(count_row, text=_("Limpar"), variant="subtle",
                                         command=lambda: clear_search())
        clear_filter.pack(side=tk.RIGHT)

        self._manager_search_entries[str(parent)] = search_entry

        filter_var = tk.StringVar(value=FILTER_ALL)
        group_var = tk.StringVar(value="")
        filter_frame = tk.Frame(page_header, bg=ui.surface)
        filter_frame.pack(side=tk.RIGHT, padx=(ui.space_md, ui.space_lg))
        filter_frame.grid_columnconfigure(0, weight=1)
        # One drop-down picks the group filter; each label maps back to its
        # (filter, group id). Group management lives behind the Grupos menu
        # so its Novo/Excluir are never confused with the editor's.
        group_choices = {}
        group_choice_var = tk.StringVar()
        group_filter = ui_widgets.combobox(filter_frame, textvariable=group_choice_var, width=18)
        group_filter.grid(row=0, column=0, sticky="ew")

        def on_group_filter(_event=None):
            filter_name, group_id = group_choices.get(
                group_choice_var.get(), (FILTER_ALL, ""))
            group_var.set(group_id)
            filter_var.set(filter_name)

        group_filter.bind("<<ComboboxSelected>>", on_group_filter)

        def sync_group_label(*_args):
            current = (filter_var.get(), group_var.get())
            for label, choice in group_choices.items():
                if choice == current:
                    group_choice_var.set(label)
                    return
            group_choice_var.set(_("Todos os grupos"))

        group_var.trace_add("write", sync_group_label)
        filter_var.trace_add("write", sync_group_label)

        groups_menu = ui_widgets.menu(filter_frame)
        groups_menu.add_command(label=_("Novo grupo…"), command=lambda: on_create_group())
        groups_menu.add_command(label=_("Editar grupo…"), command=lambda: on_edit_group())
        groups_menu.add_command(label=_("Excluir grupo"), command=lambda: on_delete_group())

        def show_groups_menu():
            groups_menu.tk_popup(
                group_actions.winfo_rootx(),
                group_actions.winfo_rooty() + group_actions.winfo_height(),
            )

        group_actions = ui_widgets.button(filter_frame, text=_("Grupos"), command=show_groups_menu)
        # The chevron says the button opens a menu; without the icon font it is text.
        if not ui_widgets.set_icon(group_actions, "chevron_down", trailing=True):
            group_actions.configure(text=_("Grupos") + " ▾")
        group_actions.grid(row=0, column=1, padx=(ui.space_xs, 0))
        view_buttons = tk.Frame(main, bg=ui.surface)
        view_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, ui.space_xs))
        segments = {}
        for index, (value, label) in enumerate((
            (FILTER_ALL, _("Todos")), (FILTER_FAVORITES, _("Favoritos")),
            (FILTER_RECENT, _("Recentes")), (FILTER_DISABLED, _("Desativados")),
            (FILTER_PROBLEMS, _("Com problema")),
        )):
            segment = ui_widgets.button(view_buttons, text=label, variant="nav",
                                         command=lambda value=value: filter_var.set(value))
            segment.grid(row=0, column=index, sticky="ew", padx=(0, ui.space_xs))
            segments[value] = segment

        def clear_search():
            group_var.set("")
            filter_var.set(FILTER_ALL)
            search_var.set("")
            search_entry.focus_set()

        listbox_shell = ui_widgets.list_frame(frame_left)
        listbox_shell.grid(row=5, column=0, sticky="nsew")
        listbox_shell.grid_columnconfigure(0, weight=1)
        listbox_shell.grid_rowconfigure(0, weight=1)

        tree = self._create_snippet_tree(listbox_shell, trigger_heading="Trigger")
        empty_label = tk.Frame(listbox_shell, bg=ui.card)
        empty_message = tk.Label(
            empty_label,
            text=_("Sua biblioteca está vazia."),
            font=ui.font(),
            bg=ui.card,
            fg=ui.text_muted,
            justify="center",
        )
        empty_message.pack(pady=(ui.space_lg, ui.space_sm))
        empty_new = ui_widgets.button(empty_label, text=_("Novo snippet"), command=lambda: on_new())
        empty_import = ui_widgets.button(empty_label, text=_("Importar…"),
                                         command=lambda: self._manager_import_action())
        empty_clear = ui_widgets.button(empty_label, text=_("Limpar busca"), command=clear_search)
        empty_label.grid(row=0, column=0, sticky="nsew")

        frame_right = ui_widgets.flat_pane(main)
        frame_right.grid(row=2, column=1, sticky="nsew")
        frame_right.grid_columnconfigure(0, weight=1)
        # Toolbar plus ~4 lines of text: without a floor the fixed rows took
        # every pixel at the minimum window size and the content box vanished.
        frame_right.grid_rowconfigure(5, weight=1, minsize=EDITOR_CONTENT_MIN_HEIGHT)

        # What the editor holds and whether it is saved, where a fixed
        # caption used to be.
        header = self._editor_header(frame_right, lambda: reveal_static())
        header.frame.grid(row=1, column=0, sticky="ew", pady=(ui.space_xs, ui.space_md))
        session = EditorSession("static")

        tk.Label(
            frame_right,
            text=_("Trigger armazenado"),
            font=ui.font(),
            bg=ui.card,
            fg=ui.text_strong,
        ).grid(row=2, column=0, sticky="w")
        trigger_var = tk.StringVar(frame_right)
        entry_trigger = ui_widgets.entry(frame_right, textvariable=trigger_var)
        entry_trigger.grid(row=3, column=0, sticky="ew", pady=(ui.space_xs, ui.space_md))
        effective_trigger_var = tk.StringVar(value=_("Efetivo: —"))
        tk.Label(
            frame_right,
            textvariable=effective_trigger_var,
            font=ui.caption_font(),
            bg=ui.card,
            fg=ui.text_muted,
            anchor="e",
        ).grid(row=2, column=0, sticky="e")

        editor_shell = tk.Frame(frame_right, bg=ui.card)
        editor_shell.grid(row=5, column=0, sticky="nsew", pady=(ui.space_xs, 0))
        editor_shell.grid_columnconfigure(0, weight=1)
        editor_shell.grid_rowconfigure(1, weight=1)

        text_field, text_value = ui_widgets.text_area(
            editor_shell,
            wrap=tk.WORD,
            padx=ui.space_sm,
            pady=ui.space_sm,
        )
        update_format_status, request_editor_update = self._create_formatting_toolbar(
            editor_shell, text_value, on_change=lambda payload: render_editor(payload))
        text_field.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        # The editor's status line: the hint at rest, then the receipt of
        # what was just done (notify_status writes here while the window shows).
        receipt = ui_widgets.ReceiptLine(frame_right, _("Ctrl+S para salvar"))
        receipt.frame.grid(row=6, column=0, sticky="ew", pady=(ui.space_xs, ui.space_sm))
        self._manager_receipts[str(parent)] = receipt

        btn_frame = tk.Frame(frame_right, bg=ui.card)
        btn_frame.grid(row=7, column=0, sticky="ew")
        primary_actions = tk.Frame(btn_frame, bg=ui.card)
        secondary_actions = tk.Frame(btn_frame, bg=ui.card)

        def editor_button(label, icon, *, variant="standard", parent=primary_actions):
            return ui_widgets.button(parent, text=label, icon=icon, variant=variant)

        btn_new = editor_button(_("Novo"), "add")
        btn_duplicate = editor_button(_("Duplicar"), "copy")
        btn_rename = editor_button(_("Renomear"), "rename")
        btn_delete = editor_button(_("Excluir"), "delete", variant="danger", parent=secondary_actions)
        btn_save = editor_button(_("Salvar"), "save", variant="accent", parent=secondary_actions)
        # Gaps are measured between faces: the focus margin every Fluent
        # button reserves is part of the gap, which keeps the row at its
        # pre-margin width (it must fit on one line at the minimum window).
        button_gap = ui_widgets.face_gap(btn_frame, 6)
        btn_new.pack(side=tk.LEFT, padx=(0, button_gap))
        btn_duplicate.pack(side=tk.LEFT, padx=(0, button_gap))
        btn_rename.pack(side=tk.LEFT)
        btn_delete.pack(side=tk.LEFT, padx=(0, ui_widgets.face_gap(btn_frame, ui.space_lg)))
        btn_save.pack(side=tk.LEFT)
        layout_wrapping_row(
            btn_frame, primary_actions, secondary_actions,
            ui_widgets.face_gap(btn_frame, ui.space_lg),
            ui_widgets.face_gap(btn_frame, ui.space_sm),
        )

        # The editor's group picker shows labels; this maps each back to its
        # group id ("" is no group). Rebuilt with the filter's choices.
        item_group_choices = {}
        item_group_var = tk.StringVar(value=_("Sem grupo"))
        item_favorite_var = tk.BooleanVar(value=False)
        item_frame = tk.Frame(frame_right, bg=ui.card)
        item_frame.grid(row=4, column=0, sticky="ew", pady=(0, ui.space_sm))
        item_group_controls = tk.Frame(item_frame, bg=ui.card)
        tk.Label(item_group_controls, text=_("Grupo:"), bg=ui.card, fg=ui.text_muted, font=ui.caption_font()).pack(side=tk.LEFT)
        item_group_combo = ui_widgets.combobox(item_group_controls, textvariable=item_group_var, width=16)
        item_group_combo.pack(side=tk.LEFT, padx=(4, ui.space_md))
        item_favorite_check = ui_widgets.checkbox(
            item_group_controls,
            text=_("Favorito"),
            variable=item_favorite_var,
            command=lambda: on_toggle_favorite(),
        )
        item_favorite_check.pack(side=tk.LEFT)
        item_metadata_controls = tk.Frame(item_frame, bg=ui.card)
        form_button = ui_widgets.button(
            item_metadata_controls, text=_("Formulário"), command=lambda: on_edit_form(),
            variant="subtle", icon="form",
        )
        form_button.pack(side=tk.LEFT)
        preview_button = ui_widgets.button(
            item_metadata_controls, text=_("Prévia"), command=lambda: on_preview(),
            variant="subtle", icon="preview",
        )
        preview_button.pack(side=tk.LEFT, padx=(4, 0))
        layout_wrapping_row(
            item_frame, item_group_controls, item_metadata_controls,
            ui.space_md, ui.space_sm,
        )
        metadata_warning = tk.Label(
            frame_right,
            text=_("Metadados somente leitura: grupos, favoritos e formulários estão desativados."),
            bg=ui.card,
            fg=ui.warning,
            font=ui.caption_font(),
            anchor="w",
        )
        metadata_warning.grid(row=9, column=0, sticky="ew", pady=(ui.space_xs, 0))

        def refresh_metadata_controls():
            # The item's own controls follow the editor (render_editor).
            read_only = bool(getattr(self.library_metadata, "read_only", False))
            group_actions.configure(state=tk.DISABLED if read_only else tk.NORMAL)
            if read_only:
                metadata_warning.grid()
            else:
                metadata_warning.grid_remove()

        self._bind_mousewheel(text_value, text_value)

        visible_rows = {}
        # Every static row by stored trigger, for the editor's Efetivo.
        static_rows_by_key = {}

        def refresh_group_menu():
            groups = self.library_metadata.get("groups", {}) if isinstance(self.library_metadata, dict) else {}
            group_choices.clear()
            group_choices[_("Todos os grupos")] = (FILTER_ALL, "")
            group_choices[_("Sem grupo")] = (UNGROUPED_FILTER, "")
            for group_id, definition in groups.items():
                label = str(definition.get("label", group_id) if isinstance(definition, dict) else group_id)
                if label in group_choices:
                    label = f"{label} ({group_id})"
                group_choices[label] = ("group", str(group_id))
            group_filter.configure(values=tuple(group_choices))
            sync_group_label()
            item_group_choices.clear()
            item_group_choices[_("Sem grupo")] = ""
            item_group_choices.update(
                (label, group_id)
                for label, (kind, group_id) in group_choices.items()
                if kind == "group"
            )
            item_group_combo.configure(values=tuple(item_group_choices))
            # A deleted or relabelled group must not stay on the picker.
            show_item_metadata(static_row(current_static_key()))

        def static_row(key):
            if key is None:
                return None
            return next((candidate for candidate in self._manager_rows()
                         if candidate.kind == "static" and candidate.stored_trigger == key), None)

        def show_item_metadata(row):
            """Show the saved group and favorite of ``row`` (none for a new item)."""
            group_id = row.group_id if row and row.group_id else ""
            item_group_var.set(next(
                (label for label, choice in item_group_choices.items() if choice == group_id),
                _("Sem grupo"),
            ))
            item_favorite_var.set(bool(row and row.favorite))

        def get_static_visible_snippets():
            """Visible static snippets in display order, best search match first."""
            projection = self._manager_static_projection()
            all_rows = self._manager_rows()
            static_rows_by_key.clear()
            static_rows_by_key.update(
                (row.stored_trigger, row) for row in all_rows if row.kind == "static")
            rows = filter_static_rows(
                filter_manager_rows(
                    all_rows,
                    filter_var.get(),
                    workflow_state=self.workflow_state,
                    group_id=group_var.get() or None,
                ),
                search_var.get(),
                projection,
            )
            visible_rows.clear()
            visible_rows.update((row.stored_trigger, row) for row in rows)
            return {row.stored_trigger: projection[row.stored_trigger] for row in rows}

        static_snips = get_static_visible_snippets()

        def refresh_listbox(*, keep_view=True):
            """Rebuild the list. The editor's item stays selected, the keyboard
            focus row and, unless the filter changed, the scroll position too."""
            focus_item = tree.focus()
            top = tree.yview()[0] if keep_view else 0.0
            attached = tree.get_children()
            if attached:
                tree.detach(*attached)
            static_snips.clear()
            static_snips.update(get_static_visible_snippets())
            for key in set(tree.full_values) - set(static_rows_by_key):
                tree.delete(key)
                del tree.full_values[key]
            for key in static_snips:
                row = visible_rows.get(key)
                self._insert_snippet_row(tree, key, static_snips[key], row)
            tree.fit_cells()
            if static_snips:
                empty_label.grid_remove()
                tree.grid()
            else:
                tree.grid_remove()
                empty_label.grid()
            total = len(static_rows_by_key)
            count_var.set(_("{shown} de {total}").format(shown=len(static_snips), total=total))
            for value, segment in segments.items():
                ui_widgets.set_selected(segment, filter_var.get() == value)
            for widget in (empty_new, empty_import, empty_clear):
                widget.pack_forget()
            if total:
                empty_message.configure(text=_("Nenhum snippet corresponde à busca ou aos filtros."))
                empty_clear.pack()
            else:
                empty_message.configure(text=_("Sua biblioteca está vazia."))
                empty_new.pack(pady=(0, ui.space_xs))
                empty_import.pack()
            if set_count is not None:
                set_count(total)
            if session.ref in static_snips:
                tree.selection_set(session.ref)
            if focus_item in static_snips:
                tree.focus(focus_item)
            tree.yview_moveto(top)
            render_editor()

        def editor_value():
            return serialize_text_widget_content(text_value)

        def is_dirty():
            return session.is_dirty(trigger_var.get(), editor_value())

        def stored_value(key):
            """What the library holds for static ``key``, shadowed or not."""
            value = self.shadowed_static_snippets.get(key, self.snippets.get(key, EDITOR_MISSING))
            if callable(value):
                return EDITOR_MISSING
            return value

        def current_static_key():
            """The saved snippet the editor's commands act on, or None."""
            key = session.ref
            return key if stored_value(key) is not EDITOR_MISSING else None

        def replaced_name(typed):
            """The other saved snippet that Salvar would overwrite under ``typed``, or None."""
            if typed and typed != session.ref and stored_value(typed) is not EDITOR_MISSING:
                return typed
            return None

        def render_editor(payload=None):
            """Draw the editor's target, its draft state and the commands that apply."""
            if payload is None:
                payload = editor_value()
            typed = trigger_var.get().strip()
            dirty = session.is_dirty(typed, payload)
            problem = static_draft_problem(typed, extract_plain_text(payload)) if dirty else None
            item = current_static_key()
            read_only = bool(getattr(self.library_metadata, "read_only", False))
            _set_enabled(btn_save, dirty and problem is None)
            ui_widgets.set_button_variant(btn_save, "accent" if dirty and problem is None else "standard", icon="save")
            ui_widgets.set_button_variant(page_new, "standard" if dirty and problem is None else "accent", icon="add")
            _set_enabled(btn_delete, item is not None)
            _set_enabled(preview_button, item is not None)
            for widget in (btn_duplicate, btn_rename, item_favorite_check, form_button):
                _set_enabled(widget, item is not None and not read_only)
            item_group_combo.configure(
                state="readonly" if item is not None and not read_only else tk.DISABLED)
            hidden = item is not None and session.ref not in static_snips
            if session.ref is not None:
                target = _("Editando {name}").format(name=session.ref)
            elif session.mode == EDITOR_NEW or dirty:
                target = _("Novo snippet")
            else:
                target = _("Nenhum snippet aberto")
            if problem:
                detail = _(problem)
            else:
                notes = []
                if dirty and replaced_name(typed):
                    notes.append(_("Salvar substitui {name}.").format(name=typed))
                elif dirty and item is not None and typed != session.ref:
                    notes.append(_("Salvar cria {name}; {open} continua salvo.").format(
                        name=typed, open=session.ref))
                if hidden:
                    notes.append(_("Oculto pelo filtro atual."))
                if not notes and session.mode == EDITOR_EMPTY and not dirty:
                    notes.append(_("Selecione um snippet na lista ou clique em Novo."))
                detail = " ".join(notes)
            header.show(target, dirty, detail, hidden)
            row = static_rows_by_key.get(typed)
            effective = row.effective_trigger if row else typed
            effective_trigger_var.set(
                _("Efetivo: {trigger}").format(trigger=effective) if effective else _("Efetivo: —"))
            editor.dirty = dirty
            self._refresh_manager_title()

        def load_item(key):
            """Open saved snippet ``key`` in the editor."""
            value = stored_value(key)
            trigger_var.set(key)
            load_value_into_text_widget(text_value, "" if value is EDITOR_MISSING else value)
            session.load(key, key, editor_value(), copy.deepcopy(value))
            show_item_metadata(static_row(key))
            header.notice(None)
            update_format_status()

        def clear_editor(*, new=False):
            """Show nothing, or with ``new`` a fresh draft (Novo)."""
            trigger_var.set("")
            load_value_into_text_widget(text_value, "")
            session.reset(new=new)
            show_item_metadata(None)
            header.notice(None)
            if tree.selection():
                tree.selection_remove(tree.selection())
            update_format_status()

        def revert_draft():
            """Descartar: the editor shows the saved snippet again, or nothing."""
            if current_static_key() is not None:
                load_item(session.ref)
            else:
                clear_editor()

        def draft_question():
            if session.ref is not None:
                return _("O snippet {name} tem alterações não salvas.").format(name=session.ref)
            return _("O novo snippet tem alterações não salvas.")

        def reconcile_editor():
            """After the library changed: a clean editor follows it; a draft
            is kept and the editor says what changed under it."""
            if session.ref is None:
                render_editor()
                return
            outcome = session.reconcile(stored_value(session.ref))
            if outcome not in (EDITOR_CHANGED, EDITOR_GONE):
                render_editor()
                return
            if not is_dirty():
                if outcome == EDITOR_GONE:
                    clear_editor()
                else:
                    load_item(session.ref)
                return
            name = session.ref

            def use_library():
                if current_static_key() == name:
                    load_item(name)
                else:
                    clear_editor()

            def keep_draft():
                session.keep_draft(stored_value(name))
                header.notice(None)
                refresh_listbox()

            self._show_library_conflict(header, outcome, name, use_library, keep_draft)
            render_editor()

        def on_tree_select(_event=None):
            selection = tree.selection()
            if not selection or selection[0] == session.ref:
                # The list re-selecting the open item after a rebuild, or a
                # filter hiding it: the editor keeps what it shows.
                return
            key = selection[0]
            if not editor.resolve():
                # Cancelar: the list goes back to what the editor still shows.
                if session.ref in static_snips:
                    tree.selection_set(session.ref)
                    tree.focus(session.ref)
                elif key in static_snips:
                    tree.selection_remove(key)
                return
            load_item(key)
            if key in static_snips:
                tree.selection_set(key)
                tree.focus(key)

        def reveal_static():
            """Mostrar na lista: clear what hides the open item and select it."""
            key = session.ref
            group_var.set("")
            filter_var.set(FILTER_ALL)
            search_var.set("")
            refresh_listbox()
            if key in static_snips:
                tree.selection_set(key)
                tree.focus(key)
                tree.see(key)
            tree.focus_set()

        def select_static_target(descriptor):
            if descriptor.kind != "static":
                return False
            key = descriptor.row_id
            if key != session.ref and not editor.resolve():
                # The person kept the draft; there is nothing to report.
                return True
            group_var.set("")
            filter_var.set(FILTER_ALL)
            search_var.set("")
            refresh_listbox()
            if key not in static_snips:
                return False
            try:
                if self._manager_notebook is not None:
                    self._manager_notebook.select(parent)
            except Exception:
                pass
            if key != session.ref:
                load_item(key)
            tree.selection_set(key)
            tree.focus(key)
            tree.see(key)
            return True

        self._manager_tab_selectors["static"] = select_static_target

        def manager_action_failed(title):
            if getattr(self.library_metadata, "read_only", False):
                ui_widgets.alert(
                    root, title,
                    _("Os metadados da biblioteca são somente leitura nesta versão; "
                      "favoritos, grupos e formulários não podem ser alterados."),
                )
            else:
                ui_widgets.alert(root, title, _("Não foi possível salvar a alteração."), tone="danger")

        def show_restored_static(key):
            # Desfazer puts the snippet back; the editor opens it unless it
            # holds a draft by now.
            if key in static_snips and not is_dirty():
                load_item(key)
                tree.selection_set(key)
                tree.focus(key)
                tree.see(key)
            tree.focus_set()

        def on_create_group():
            from group_dialog import run_group_dialog
            definition = run_group_dialog(root)
            if definition is None:
                return
            try:
                result = manager_create_group(
                    self._manager_static_projection(), self.library_metadata,
                    definition=definition,
                    dynamic_triggers=self._manager_dynamic_triggers(),
                )
                if self._persist_manager_static_action(result):
                    refresh_group_menu()
                    self.receipt(
                        N_("Grupo criado às {time}"), definition.get("label") or _("Sem nome"),
                        key="manager-group-create")
                else:
                    manager_action_failed(_("Criar grupo"))
            except (KeyError, ValueError, MetadataReadOnlyError) as error:
                self.logger.warning(f"Manager group creation failed: {error}")
                manager_action_failed(_("Criar grupo"))
            except Exception:
                self.logger.exception("Manager group creation failed unexpectedly")
                manager_action_failed(_("Criar grupo"))

        def on_edit_group():
            group_id = group_var.get()
            groups = self.library_metadata.get("groups", {}) if isinstance(self.library_metadata, dict) else {}
            if not group_id or group_id not in groups:
                ui_widgets.alert(root, _("Editar grupo"), _("Selecione um grupo para editar."))
                return
            from group_dialog import run_group_dialog
            definition = run_group_dialog(root, groups[group_id], title=_("Editar grupo"))
            if definition is None:
                return
            try:
                result = manager_update_group(
                    self._manager_static_projection(), self.library_metadata, group_id, definition,
                    dynamic_triggers=self._manager_dynamic_triggers(),
                )
                if self._persist_manager_static_action(result):
                    refresh_group_menu()
                    self.receipt(
                        N_("Grupo atualizado às {time}"), definition.get("label") or _("Sem nome"),
                        key=f"manager-group-edit:{group_id}")
                else:
                    manager_action_failed(_("Editar grupo"))
            except (KeyError, ValueError, MetadataReadOnlyError) as error:
                self.logger.warning(f"Manager group update failed: {error}")
                manager_action_failed(_("Editar grupo"))
            except Exception:
                self.logger.exception("Manager group update failed unexpectedly")
                manager_action_failed(_("Editar grupo"))

        def on_delete_group():
            group_id = group_var.get()
            groups = self.library_metadata.get("groups", {}) if isinstance(self.library_metadata, dict) else {}
            if not group_id or group_id not in groups:
                ui_widgets.alert(root, _("Excluir grupo"), _("Selecione um grupo para excluir."))
                return
            # Deleting is reversible for a while: the definition and the
            # members go back through the same save path on Desfazer.
            definition = copy.deepcopy(dict(groups[group_id]))
            static_members, mapping_members = manager_group_members(self.library_metadata, group_id)
            label = definition.get("label") or _("Sem nome")
            try:
                result = manager_delete_group(
                    self._manager_static_projection(), self.library_metadata, group_id,
                    dynamic_triggers=self._manager_dynamic_triggers(),
                )
                if not self._persist_manager_static_action(result):
                    manager_action_failed(_("Excluir grupo"))
                    return
            except (KeyError, ValueError, MetadataReadOnlyError) as error:
                self.logger.warning(f"Manager group deletion failed: {error}")
                manager_action_failed(_("Excluir grupo"))
                return
            except Exception:
                self.logger.exception("Manager group deletion failed unexpectedly")
                manager_action_failed(_("Excluir grupo"))
                return
            group_var.set("")
            refresh_group_menu()

            def undo():
                try:
                    restored = manager_restore_group(
                        self._manager_static_projection(), self.library_metadata, group_id, definition,
                        static_items=static_members, mapping_items=mapping_members,
                        dynamic_triggers=self._manager_dynamic_triggers(),
                    )
                    if not self._persist_manager_static_action(restored):
                        manager_action_failed(_("Desfazer exclusão"))
                        return
                except (KeyError, ValueError, MetadataReadOnlyError) as error:
                    self.logger.warning(f"Manager group restore failed: {error}")
                    ui_widgets.alert(
                        root, _("Desfazer exclusão"),
                        _("Não foi possível recriar o grupo {name}: {error}").format(name=label, error=error),
                    )
                    return
                except Exception:
                    self.logger.exception("Manager group restore failed unexpectedly")
                    manager_action_failed(_("Desfazer exclusão"))
                    return
                refresh_group_menu()
                receipt.show(_("Restaurado às {time} · {name}").format(
                    time=time_format.clock(datetime.now()), name=label))

            receipt.show(
                _("Excluído às {time} · {name}").format(time=time_format.clock(datetime.now()), name=label),
                _("Desfazer"), undo,
            )

        def on_toggle_favorite():
            key = current_static_key()
            if key is None:
                return
            try:
                result = manager_toggle_favorite(
                    self._manager_static_projection(), self.library_metadata, key,
                    item_favorite_var.get(),
                    dynamic_triggers=self._manager_dynamic_triggers(),
                )
                if not self._persist_manager_static_action(result):
                    show_item_metadata(static_row(key))
                    manager_action_failed(_("Favorito"))
            except (KeyError, ValueError, MetadataReadOnlyError) as error:
                show_item_metadata(static_row(key))
                self.logger.warning(f"Manager favorite update failed: {error}")
                manager_action_failed(_("Favorito"))
            except Exception:
                show_item_metadata(static_row(key))
                self.logger.exception("Manager favorite update failed unexpectedly")
                manager_action_failed(_("Favorito"))

        def on_group_assignment(_event=None):
            key = current_static_key()
            if key is None:
                return
            group_id = item_group_choices.get(item_group_var.get(), "")
            try:
                if group_id:
                    result = manager_assign_item(
                        self._manager_static_projection(), self.library_metadata, key, group_id,
                        dynamic_triggers=self._manager_dynamic_triggers(),
                    )
                else:
                    from manager_actions import unassign_item as manager_unassign_item
                    result = manager_unassign_item(
                        self._manager_static_projection(), self.library_metadata, key,
                        dynamic_triggers=self._manager_dynamic_triggers(),
                    )
                if not self._persist_manager_static_action(result):
                    show_item_metadata(static_row(key))
                    manager_action_failed(_("Grupo"))
            except (KeyError, ValueError, MetadataReadOnlyError) as error:
                show_item_metadata(static_row(key))
                self.logger.warning(f"Manager group assignment failed: {error}")
                manager_action_failed(_("Grupo"))
            except Exception:
                show_item_metadata(static_row(key))
                self.logger.exception("Manager group assignment failed unexpectedly")
                manager_action_failed(_("Grupo"))

        def on_edit_form():
            key = current_static_key()
            if key is None:
                return
            from form_editor_dialog import run_form_editor
            definition = self._static_form_metadata(key)
            form = run_form_editor(
                root, definition, self.snippets,
                template=extract_plain_text(stored_value(key)),
            )
            if form is None:
                return
            try:
                result = manager_set_form(
                    self._manager_static_projection(), self.library_metadata, key, form,
                    dynamic_triggers=self._manager_dynamic_triggers(),
                )
                if not self._persist_manager_static_action(result):
                    manager_action_failed(_("Formulário"))
            except (KeyError, ValueError, MetadataReadOnlyError) as error:
                self.logger.warning(f"Manager form update failed: {error}")
                manager_action_failed(_("Formulário"))
            except Exception:
                self.logger.exception("Manager form update failed unexpectedly")
                manager_action_failed(_("Formulário"))

        def on_preview():
            key = current_static_key()
            if key is None:
                return
            result = resolve_preview(stored_value(key), self.snippets, self._static_form_metadata(key))
            controller = getattr(self, "_manager_preview_controller", None)
            if controller is None or controller.shared_root is not root:
                controller = PreviewDialogController(root)
                self._manager_preview_controller = controller
            controller.show(result, title=_("Prévia — {key}").format(key=key))

        def on_new(prefill=None):
            if not editor.resolve():
                return
            clear_editor(new=True)
            trigger_var.set(search_var.get().strip() if prefill is None else prefill)
            entry_trigger.focus_set()

        def on_save():
            """Salvar and Ctrl+S. True when nothing is left unsaved."""
            trigger = trigger_var.get().strip()
            value = editor_value()
            if not session.is_dirty(trigger, value):
                return True
            problem = static_draft_problem(trigger, extract_plain_text(value))
            if problem:
                ui_widgets.alert(root, _("Salvar snippet"), _(problem))
                return False

            # The editor names one snippet, but the trigger field can point at
            # another saved one; writing over it must be a choice.
            if replaced_name(trigger) and not ui_widgets.confirm(
                root,
                _("Substituir snippet"),
                _("O snippet {name} já existe. Salvar troca o texto dele pelo que está no editor.").format(
                    name=trigger),
                _("Substituir"),
                danger=True,
            ):
                return False

            # "Already in self.snippets" is not the same as "editing an existing
            # static": a dynamic trigger occupies the key too, and that is exactly
            # the collision that needs the warning.
            if trigger not in self.snippets or callable(self.snippets[trigger]):
                warnings = self._validate_trigger_warnings(trigger)
                if warnings and not ui_widgets.confirm(
                    root,
                    _("Confirmar trigger"),
                    _("Avisos sobre este trigger:\n\n• {warnings}").format(
                        warnings="\n• ".join(warnings)
                    ),
                    _("Salvar mesmo assim"),
                ):
                    return False

            # Saving over a live dynamic trigger records the static for disk but
            # leaves the callable in the merged map, so the trigger keeps
            # expanding as the dynamic snippet this session (see helper).
            if not self.save_static_snippet(trigger, value):
                # The draft stays in the editor for another try.
                ui_widgets.alert(
                    root, _("Erro ao salvar"),
                    _("Não foi possível gravar snippets.json, então nada foi salvo. O rascunho "
                      "continua no editor; verifique os logs e tente de novo."),
                    tone="danger",
                )
                return False
            session.mark_saved(trigger, trigger, value, copy.deepcopy(stored_value(trigger)))
            header.notice(None)
            self.receipt(N_("Salvo às {time}"), trigger, key=f"save-static:{trigger}")

            refresh_listbox()
            if trigger in static_snips:
                tree.see(trigger)
            update_format_status()
            _move_focus_off(btn_save, text_value)
            return True

        def on_delete():
            if not editor.resolve():
                return
            trigger = session.ref
            if not trigger:
                ui_widgets.alert(root, _("Excluir snippet"), _("Selecione um snippet."))
                return

            # Deleting is reversible for a while (Desfazer), so it asks
            # nothing; the value and its metadata are kept until then.
            value = copy.deepcopy(stored_value(trigger))
            provider = self.snippets.get(trigger) if trigger in self.shadowed_static_snippets else None
            item_metadata = static_item_metadata(self.library_metadata, trigger)
            result = self._delete_static_snippet(trigger, include_shadowed=True)
            if result == "dynamic":
                # A dynamic trigger owns the name; the free-text box let the user
                # type it. Deleting would discard the shadowed static from disk,
                # so refuse and point at the tab that manages the dynamic entry.
                ui_widgets.alert(
                    root, _("Excluir snippet"),
                    _("'{trigger}' é um snippet dinâmico. Gerencie-o em Ações dinâmicas.").format(trigger=trigger),
                )
                return
            if result == "error":
                ui_widgets.alert(
                    root, _("Erro ao salvar"),
                    _("Não foi possível gravar snippets.json. Verifique os logs; a exclusão pode não ter sido salva."),
                    tone="danger",
                )
                return
            if result == "missing":
                ui_widgets.alert(root, _("Excluir snippet"), _("Selecione um snippet."))
                return
            clear_editor()
            refresh_listbox()

            def undo():
                try:
                    if provider is not None and self.snippets.get(trigger) is not provider:
                        raise ValueError(_("A ação dinâmica mudou desde a exclusão do snippet."))
                    projection = self._manager_static_projection()
                    if provider is not None:
                        projection.pop(trigger, None)
                    restored = manager_restore_static(
                        projection, self.library_metadata, trigger, value, item_metadata,
                        dynamic_triggers=self._manager_dynamic_triggers() - ({trigger} if provider is not None else set()),
                    )
                    if not self._persist_manager_static_action(restored):
                        manager_action_failed(_("Desfazer exclusão"))
                        return
                except (KeyError, ValueError, MetadataReadOnlyError) as error:
                    self.logger.warning(f"Manager static restore failed: {error}")
                    ui_widgets.alert(
                        root, _("Desfazer exclusão"),
                        _("Não foi possível restaurar {trigger}: {error}").format(trigger=trigger, error=error),
                    )
                    return
                except Exception:
                    self.logger.exception("Manager static restore failed unexpectedly")
                    manager_action_failed(_("Desfazer exclusão"))
                    return
                show_restored_static(trigger)
                receipt.show(_("Restaurado às {time} · {name}").format(
                    time=time_format.clock(datetime.now()), name=trigger))

            receipt.show(
                _("Excluído às {time} · {name}").format(time=time_format.clock(datetime.now()), name=trigger),
                _("Desfazer"), undo,
            )

        def new_trigger_problem(value, current=None):
            return static_trigger_problem(self.snippets, value, current)

        def on_duplicate():
            # The copy opens in the editor, so a draft is settled first.
            if current_static_key() is not None and not editor.resolve():
                return
            source_key = current_static_key()
            if source_key is None:
                ui_widgets.alert(root, _("Duplicar snippet"), _("Selecione um snippet salvo."))
                return
            destination = ui_widgets.ask_text(
                root,
                _("Duplicar snippet"),
                _("Trigger da cópia de {trigger}").format(trigger=source_key),
                validate=new_trigger_problem,
                primary_label=_("Duplicar"),
            )
            if destination is None:
                return
            try:
                result = manager_duplicate_static(
                    self._manager_static_projection(), self.library_metadata, source_key, destination,
                    dynamic_triggers=self._manager_dynamic_triggers(),
                )
                if not self._persist_manager_static_action(result):
                    manager_action_failed(_("Duplicar"))
                    return
            except (KeyError, ValueError, MetadataReadOnlyError) as error:
                self.logger.warning(f"Manager duplicate failed: {error}")
                manager_action_failed(_("Duplicar"))
                return
            except Exception:
                self.logger.exception("Manager duplicate failed unexpectedly")
                manager_action_failed(_("Duplicar"))
                return
            load_item(destination)
            if destination in static_snips:
                tree.selection_set(destination)
                tree.focus(destination)
                tree.see(destination)
            self.receipt(N_("Duplicado às {time}"), destination, key=f"duplicate-static:{destination}")

        def on_rename():
            old_trigger = session.ref
            projection = self._manager_static_projection()
            if old_trigger not in projection:
                ui_widgets.alert(root, _("Renomear snippet"), _("Selecione um snippet salvo para renomear."))
                return
            if callable(projection[old_trigger]):
                ui_widgets.alert(
                    root, _("Renomear snippet"),
                    _("'{old_trigger}' é um snippet dinâmico. Renomeie-o em Ações dinâmicas.").format(old_trigger=old_trigger),
                )
                return
            new_trigger = ui_widgets.ask_text(
                root,
                _("Renomear snippet"),
                _("Novo trigger de {trigger}").format(trigger=old_trigger),
                old_trigger,
                validate=lambda value: new_trigger_problem(value, old_trigger),
                primary_label=_("Renomear"),
            )
            if new_trigger is None or new_trigger == old_trigger:
                return
            warnings = self._validate_trigger_warnings(new_trigger)
            if warnings and not ui_widgets.confirm(
                root,
                _("Confirmar trigger"),
                _("Avisos sobre este trigger:\n\n• {warnings}").format(
                    warnings="\n• ".join(warnings)
                ),
                _("Renomear mesmo assim"),
            ):
                return
            field_followed = trigger_var.get().strip() == old_trigger

            def follow(ref):
                # The editor, draft and all, follows the rename before the
                # lists refresh, so the refresh does not read it as deleted.
                session.retarget(ref, ref)
                if field_followed:
                    trigger_var.set(ref)

            try:
                result = manager_rename_static(
                    self._manager_static_projection(),
                    self.library_metadata,
                    old_trigger,
                    new_trigger,
                    dynamic_triggers=self._manager_dynamic_triggers(),
                )
                follow(new_trigger)
                if not self._persist_manager_static_action(result):
                    follow(old_trigger)
                    ui_widgets.alert(
                        root, _("Erro ao salvar"), _("Não foi possível gravar snippets.json."),
                        tone="danger",
                    )
                    return
            except (KeyError, ValueError, MetadataReadOnlyError) as error:
                if session.ref == new_trigger:
                    follow(old_trigger)
                self.logger.warning(f"Manager rename failed: {error}")
                ui_widgets.alert(root, _("Renomear snippet"), str(error))
                return
            except Exception:
                if session.ref == new_trigger:
                    follow(old_trigger)
                self.logger.exception("Manager rename failed unexpectedly")
                manager_action_failed(_("Renomear"))
                return
            if new_trigger in static_snips:
                tree.see(new_trigger)
            self.receipt(N_("Renomeado às {time}"), new_trigger, key=f"rename-static:{new_trigger}")

        editor = self._editor_handle(
            root, header,
            is_dirty=is_dirty,
            save=on_save,
            revert=revert_draft,
            question=draft_question,
            target=lambda: SnippetRef("static", session.ref) if session.ref else None,
        )
        self._register_manager_editor(editor)
        self._register_manager_commands(
            parent, search_entry, tree, new=on_new, save=on_save, delete=on_delete,
            search_key="static",
            duplicate=on_duplicate, rename=on_rename,
            escape=lambda: self._escape_manager_editor(root, search_var, is_dirty, draft_question, revert_draft),
        )
        self._manager_commands[str(parent)]["kind"] = "static"
        for control, hint in (
            (btn_new, _("Ctrl+N — Novo com a busca")), (page_new, _("Ctrl+N — Novo com a busca")),
            (btn_save, _("Ctrl+S — Salvar")), (btn_duplicate, _("Ctrl+D — Duplicar item salvo")),
            (btn_rename, _("F2 — Renomear")), (btn_delete, _("Delete na lista — Excluir · Desfazer disponível")),
            (search_entry, _("Ctrl+F: busca · ↓/Enter: lista\nEsc: limpar · Ctrl+N: novo com busca")),
            (tree, _("F2: renomear · Ctrl+D: duplicar\nDelete: excluir · Desfazer disponível")),
            (text_value, _("Tab/Shift+Tab: navegar · Ctrl+Tab: tabulação\nEsc: descartar com confirmação")),
        ):
            self._shortcut_hint(control, receipt, hint)

        tree.bind("<<TreeviewSelect>>", on_tree_select, add="+")
        btn_new.configure(command=on_new)
        page_new.configure(command=on_new)
        btn_save.configure(command=on_save)
        btn_duplicate.configure(command=on_duplicate)
        btn_rename.configure(command=on_rename)
        btn_delete.configure(command=on_delete)
        item_group_combo.bind("<<ComboboxSelected>>", on_group_assignment)
        search_var.trace_add("write", lambda *_: self._schedule_manager_search(
            root, "static", lambda: refresh_listbox(keep_view=False)))
        filter_var.trace_add("write", lambda *_: refresh_listbox(keep_view=False))
        group_var.trace_add("write", lambda *_: refresh_listbox(keep_view=False))
        trigger_var.trace_add("write", lambda *_: request_editor_update())
        # Ctrl+S saves the current static snippet from anywhere in the editor.
        for widget in (entry_trigger, text_value, tree):
            widget.bind("<Control-s>", lambda _event: (on_save(), "break")[1])

        def refresh_static_tab():
            refresh_group_menu()
            refresh_metadata_controls()
            refresh_listbox()
            reconcile_editor()

        refresh_static_tab()
        self._register_manager_refresher(refresh_static_tab)
        def capture_view():
            focused = root.focus_get()
            target = {"kind": "static", "key": session.ref} if session.ref else None
            return {"query": search_var.get(), "filter": filter_var.get(), "group": group_var.get(),
                    "selection": next(iter(tree.selection()), ""), "row_focus": tree.focus(),
                    **capture_tree_scroll(tree), "target": target,
                    "focus": "search" if focused is search_entry else "list" if focused is tree
                    else "editor" if focused in (entry_trigger, text_value) else ""}
        def restore_view(state):
            search_var.set(state.get("query", ""))
            filter_var.set(state.get("filter", FILTER_ALL))
            group_var.set(state.get("group", ""))
            refresh_listbox(keep_view=False)
            target = state.get("target", {})
            key = target.get("key")
            if target.get("kind") == "static" and key in static_rows_by_key:
                load_item(key)
            selection = state.get("selection")
            if selection in static_snips:
                tree.selection_set(selection)
            focus = state.get("row_focus")
            if focus in static_snips:
                tree.focus(focus)
            restore_tree_scroll(tree, state)
            render_editor()
            focused = {"search": search_entry, "list": tree, "editor": text_value}.get(state.get("focus"))
            if focused is not None:
                focused.focus_set()
        self._manager_views["static"] = (capture_view, restore_view)
        search_entry.focus_set()

    def _create_dynamic_mappings_tab(self, parent, root, set_count=None):
        """Build the dynamic mappings UI with customizable types.

        ``set_count`` receives the visible item count of the selected mapping
        type whenever the list is rebuilt.
        """
        ui = ui_theme.theme()

        main = tk.Frame(
            ui_widgets.page_viewport(parent), bg=ui.surface, padx=ui.space_lg, pady=ui.space_lg
        )
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        mapping_type = tk.StringVar(value="_cpf_numbers")

        def get_mappings_info():
            examples = {
                "_cpf_numbers": "cpffulano -> 123.456.789-00",
                "_cnpj_numbers": "cnpjempresa1 -> 12.345.678/0001-90",
            }
            return {
                key: {**info, "example": examples.get(
                    key, f"{info['prefix']}exemplo -> valor")}  # i18n: not ui (persisted in the library)
                for key, info in mapping_types(self.snippets).items()
            }

        mappings_info = get_mappings_info()

        def update_example_label():
            info = mappings_info.get(mapping_type.get(), {})
            prefix = info.get("prefix", "")
            example = info.get("example", "")
            lbl_example.config(text=_("{type} | Prefixo: {prefix} | Exemplo: {example}").format(type=info.get('label', _('Tipo')), prefix=prefix, example=example))

        def refresh_type_list():
            nonlocal mappings_info
            mappings_info = get_mappings_info()

            listbox_types.delete(*listbox_types.get_children())
            type_keys.clear()
            for key, info in sorted(mappings_info.items(), key=lambda item: (not item[1]["builtin"], item[1]["label"])):
                type_keys.append(key)
                listbox_types.insert("", tk.END, iid=key, text=info["label"])
            narrow_types.configure(values=tuple(mappings_info[key]["label"] for key in type_keys))

            if mapping_type.get() not in type_keys and type_keys:
                mapping_type.set(type_keys[0])

            select_type_row(mapping_type.get())
            update_example_label()

        def select_type_row(key):
            if key not in type_keys:
                return
            listbox_types.selection_set(key)
            listbox_types.focus(key)
            listbox_types.see(key)
            narrow_type_var.set(mappings_info[key]["label"])

        def type_label(container):
            info = mappings_info.get(container)
            if info:
                return info["label"]
            # A type the library no longer has, named the way get_mappings_info names it.
            return container[1:].replace("_numbers", "").replace("_codes", "").upper()

        def switch_type(key):
            """Show mapping type ``key``; False when the person kept a draft instead.

            A type change empties the editor, so a draft is settled first.
            """
            if key == mapping_type.get():
                return True
            if not editor.resolve():
                return False
            mapping_type.set(key)
            select_type_row(key)
            return True

        def on_type_select(_event=None):
            selection = listbox_types.selection()
            if not selection:
                return
            if not switch_type(selection[0]):
                select_type_row(mapping_type.get())

        tk.Label(
            main,
            text=_("Mapeamentos"),
            font=ui.title_font(),
            fg=ui.text,
            bg=ui.surface,
        ).grid(row=0, column=0, sticky="w")
        page_new_map = ui_widgets.button(main, text=_("Novo item"), icon="add", variant="accent",
                                         command=lambda: on_new_map())
        page_new_map.grid(row=0, column=0, sticky="e")
        lbl_example = tk.Label(
            main,
            text="",
            font=ui.caption_font(),
            fg=ui.text_muted,
            bg=ui.surface,
        )
        narrow_type_row = tk.Frame(main, bg=ui.surface)
        narrow_type_row.grid(row=1, column=0, sticky="ew", pady=(ui.space_xs, ui.space_sm))
        tk.Label(narrow_type_row, text=_("Tipos"), bg=ui.surface, fg=ui.text,
                 font=ui.font()).pack(side=tk.LEFT, padx=(0, ui.space_sm))
        narrow_type_var = tk.StringVar()
        narrow_types = ui_widgets.combobox(narrow_type_row, textvariable=narrow_type_var, width=18)
        narrow_types.pack(side=tk.LEFT)

        def select_narrow_type(_event=None):
            selected = next((key for key in type_keys if mappings_info[key]["label"] == narrow_type_var.get()), None)
            if selected and not switch_type(selected):
                select_type_row(mapping_type.get())

        narrow_types.bind("<<ComboboxSelected>>", select_narrow_type)
        ui_widgets.button(narrow_type_row, text=_("Novo tipo"), command=lambda: add_new_type(),
                          icon="add").pack(side=tk.LEFT, padx=(ui.space_sm, 0))
        ui_widgets.button(narrow_type_row, text=_("Excluir tipo"), command=lambda: delete_current_type(),
                          variant="danger", icon="delete").pack(side=tk.LEFT)

        content = tk.Frame(main, bg=ui.divider)
        content.grid(row=2, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=0, minsize=140)
        # Items and editor split by weight alone (see the static tab).
        content.grid_columnconfigure(1, weight=2, minsize=270, uniform="panes")
        content.grid_columnconfigure(2, weight=3, minsize=360, uniform="panes")
        content.grid_rowconfigure(0, weight=1)

        def fit_type_pane(_event=None):
            narrow = main.winfo_toplevel().winfo_width() < ui.px(1300)
            if narrow:
                frame_types.grid_remove()
                content.grid_columnconfigure(0, minsize=0)
                narrow_type_row.grid()
            else:
                frame_types.grid()
                content.grid_columnconfigure(0, minsize=ui.px(140))
                narrow_type_row.grid_remove()

        main.bind("<Configure>", fit_type_pane, add="+")

        # Types live in a scrollable vertical list so any number of custom
        # mapping types stays reachable (a horizontal row clipped them).
        frame_types = ui_widgets.flat_pane(content)
        frame_types.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        frame_types.grid_columnconfigure(0, weight=1)
        frame_types.grid_rowconfigure(1, weight=1)

        tk.Label(
            frame_types,
            text=_("Tipos"),
            font=ui.subtitle_font(),
            bg=ui.card,
            fg=ui.text,
        ).grid(row=0, column=0, sticky="w", pady=(0, ui.space_sm))

        types_list_frame = ui_widgets.list_frame(frame_types)
        types_list_frame.grid(row=1, column=0, sticky="nsew")
        types_list_frame.grid_columnconfigure(0, weight=1)
        types_list_frame.grid_rowconfigure(0, weight=1)

        type_keys = []
        listbox_types = ui_widgets.tree_list(types_list_frame)
        listbox_types.column("#0", width=ui.px(120), stretch=True)
        ui_widgets.track_focus(types_list_frame, listbox_types)
        scrollbar_types = ui_widgets.scrollbar(
            types_list_frame,
            command=listbox_types.yview,
        )
        listbox_types.config(yscrollcommand=scrollbar_types.set)
        listbox_types.grid(row=0, column=0, sticky="nsew")
        scrollbar_types.grid(row=0, column=1, sticky="ns")

        btn_types_frame = tk.Frame(frame_types, bg=ui.card)
        btn_types_frame.grid(row=2, column=0, sticky="ew", pady=(ui.space_sm, 0))

        frame_left = ui_widgets.flat_pane(content)
        frame_left.grid(row=0, column=1, sticky="nsew", padx=(0, 1))
        frame_left.grid_columnconfigure(0, weight=1)
        frame_left.grid_rowconfigure(3, weight=1)

        mapping_count_var = tk.StringVar()
        tk.Label(
            frame_left,
            textvariable=mapping_count_var,
            font=ui.caption_font(),
            bg=ui.card,
            fg=ui.text_muted,
        ).grid(row=0, column=0, sticky="w")

        map_search_var = tk.StringVar()
        ui_widgets.button(frame_left, text=_("Limpar"), variant="subtle",
                          command=lambda: map_search_var.set("")).grid(row=0, column=0, sticky="e")
        map_search_entry = ui_widgets.entry(frame_left, textvariable=map_search_var)
        map_search_entry.grid(row=2, column=0, sticky="ew", pady=(ui.space_xs, ui.space_sm))
        ui_widgets.search_hint(map_search_entry, _("Pesquisar itens"))
        self._manager_search_entries[str(parent)] = map_search_entry

        listbox_frame = ui_widgets.list_frame(frame_left)
        listbox_frame.grid(row=3, column=0, sticky="nsew")
        listbox_frame.grid_columnconfigure(0, weight=1)
        listbox_frame.grid_rowconfigure(0, weight=1)

        tree_map = self._create_snippet_tree(
            listbox_frame,
            trigger_heading=_("Identificador"),
            trigger_share=0.5,
        )
        empty_mapping_label = tk.Frame(listbox_frame, bg=ui.card)
        empty_mapping_message = tk.Label(
            empty_mapping_label,
            text=_("Este tipo ainda não tem itens."),
            font=ui.font(),
            bg=ui.card,
            fg=ui.text_muted,
            justify="center",
        )
        empty_mapping_message.pack(pady=(ui.space_lg, ui.space_sm))
        empty_map_new = ui_widgets.button(empty_mapping_label, text=_("Novo item"), command=lambda: on_new_map())
        empty_map_clear = ui_widgets.button(empty_mapping_label, text=_("Limpar busca"),
                                            command=lambda: map_search_var.set(""))
        empty_mapping_label.grid(row=0, column=0, sticky="nsew")

        frame_right = ui_widgets.flat_pane(content)
        frame_right.grid(row=0, column=2, sticky="nsew")
        frame_right.grid_columnconfigure(0, weight=1)
        # Toolbar plus ~4 lines of text: without a floor the fixed rows took
        # every pixel at the minimum window size and the content box vanished.
        frame_right.grid_rowconfigure(5, weight=1, minsize=EDITOR_CONTENT_MIN_HEIGHT)

        # What the editor holds and whether it is saved, as in Textos.
        header = self._editor_header(frame_right, lambda: reveal_mapping())
        header.frame.grid(row=1, column=0, sticky="ew", pady=(ui.space_xs, ui.space_md))
        session = EditorSession("mapping", container=mapping_type.get())
        # Only a duplicated draft carries a form to its future saved identity.
        # No metadata is published until that draft's explicit Save succeeds.
        copied_form = {"value": None}

        tk.Label(
            frame_right,
            text=_("Identificador"),
            font=ui.font(),
            bg=ui.card,
            fg=ui.text_strong,
        ).grid(row=2, column=0, sticky="w")
        mapping_effective_trigger_var = tk.StringVar(value=_("Efetivo: —"))
        tk.Label(
            frame_right,
            textvariable=mapping_effective_trigger_var,
            font=ui.caption_font(),
            bg=ui.card,
            fg=ui.text_muted,
            anchor="e",
        ).grid(row=2, column=0, sticky="e")
        name_var = tk.StringVar(frame_right)
        entry_name = ui_widgets.entry(frame_right, textvariable=name_var)
        entry_name.grid(row=3, column=0, sticky="ew", pady=(ui.space_xs, ui.space_md))

        editor_shell = tk.Frame(frame_right, bg=ui.card)
        editor_shell.grid(row=5, column=0, sticky="nsew", pady=(ui.space_xs, 0))
        editor_shell.grid_columnconfigure(0, weight=1)
        editor_shell.grid_rowconfigure(1, weight=1)

        text_field, text_value = ui_widgets.text_area(
            editor_shell,
            wrap=tk.WORD,
            padx=ui.space_sm,
            pady=ui.space_sm,
        )
        update_format_status, request_editor_update = self._create_formatting_toolbar(
            editor_shell, text_value, on_change=lambda payload: render_editor(payload))
        text_field.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        # The editor's status line: the hint at rest, then the receipt of
        # what was just done (notify_status writes here while the window shows).
        receipt = ui_widgets.ReceiptLine(frame_right, _("Ctrl+S para salvar"))
        receipt.frame.grid(row=6, column=0, sticky="ew", pady=(ui.space_xs, ui.space_sm))
        self._manager_receipts[str(parent)] = receipt

        btn_frame = tk.Frame(frame_right, bg=ui.card)
        btn_frame.grid(row=7, column=0, sticky="ew")
        primary_actions = tk.Frame(btn_frame, bg=ui.card)
        secondary_actions = tk.Frame(btn_frame, bg=ui.card)

        def mapping_button(label, icon, *, variant="standard", parent=primary_actions):
            return ui_widgets.button(parent, text=label, icon=icon, variant=variant)

        btn_new_map = mapping_button(_("Novo"), "add")
        btn_delete_map = mapping_button(_("Excluir"), "delete", variant="danger", parent=secondary_actions)
        btn_save_map = mapping_button(_("Salvar"), "save", variant="accent", parent=secondary_actions)
        btn_new_map.pack(side=tk.LEFT)
        # Face-to-face gaps, as in the static editor's action row.
        btn_delete_map.pack(side=tk.LEFT, padx=(0, ui_widgets.face_gap(btn_frame, ui.space_lg)))
        btn_save_map.pack(side=tk.LEFT)
        layout_wrapping_row(
            btn_frame, primary_actions, secondary_actions,
            ui_widgets.face_gap(btn_frame, ui.space_lg),
            ui_widgets.face_gap(btn_frame, ui.space_sm),
        )
        mapping_metadata_frame = tk.Frame(frame_right, bg=ui.card)
        mapping_metadata_frame.grid(row=4, column=0, sticky="ew", pady=(0, ui.space_sm))
        mapping_favorite_var = tk.BooleanVar(value=False)
        mapping_favorite_check = ui_widgets.checkbox(
            mapping_metadata_frame,
            text=_("Favorito"),
            variable=mapping_favorite_var,
            command=lambda: on_toggle_mapping_favorite(),
        )
        mapping_favorite_check.pack(side=tk.LEFT)
        mapping_form_button = ui_widgets.button(
            mapping_metadata_frame,
            text=_("Formulário"),
            command=lambda: on_edit_mapping_form(),
            variant="subtle",
            icon="form",
        )
        # Same arrangement as the static editor: Favorito left, the item
        # actions right-aligned.
        mapping_preview_button = ui_widgets.button(
            mapping_metadata_frame,
            text=_("Prévia"),
            command=lambda: on_preview_mapping(),
            variant="subtle",
            icon="preview",
        )
        mapping_preview_button.pack(side=tk.RIGHT, padx=(4, 0))
        mapping_form_button.pack(side=tk.RIGHT)
        # The visible type's rows by identifier, for the editor's Efetivo.
        mapping_rows = {}

        def update_total_count():
            """Tab title counts every mapping item, across all types.

            Deliberately not the selected type's visible rows: a tab title that
            changed when you clicked a type or typed in the search box would be
            reporting selection state, not library size.
            """
            if set_count is None:
                return
            total = 0
            for type_key in mappings_info:
                mapping = self.snippets.get(type_key)
                if isinstance(mapping, dict):
                    total += sum(1 for name in mapping if name and name != "__prefix__")
            set_count(total)

        def refresh_mapping_list(*, keep_view=True):
            """Rebuild the visible type's items, keeping the editor's item
            selected, the keyboard focus row and, unless the search changed,
            the scroll position."""
            focus_item = tree_map.focus()
            top = tree_map.yview()[0] if keep_view else 0.0
            attached = tree_map.get_children()
            if attached:
                tree_map.detach(*attached)
            current_type = mapping_type.get()
            query = map_search_var.get()
            mapping = self.snippets.get(current_type, {})
            if not isinstance(mapping, dict):
                mapping = {}
            mapping_rows.clear()
            mapping_rows.update(
                (row.stored_trigger, row)
                for row in self._manager_rows()
                if row.kind == "mapping" and row.container == current_type
            )
            for key in set(tree_map.full_values) - set(mapping_rows):
                tree_map.delete(key)
                del tree_map.full_values[key]
            has_rows = False
            shown = 0
            for key in iter_filtered_mapping_items(mapping, query):
                if not key:
                    continue  # a blank key cannot be a Treeview row iid
                row = mapping_rows.get(key)
                self._insert_snippet_row(tree_map, key, mapping.get(key, ""), row)
                has_rows = True
                shown += 1
            tree_map.fit_cells()
            if has_rows:
                empty_mapping_label.grid_remove()
                tree_map.grid()
            else:
                tree_map.grid_remove()
                empty_mapping_label.grid()
            mapping_count_var.set(_("{shown} de {total}").format(shown=shown, total=len(mapping_rows)))
            empty_map_new.pack_forget()
            empty_map_clear.pack_forget()
            if mapping_rows:
                empty_mapping_message.configure(text=_("Nenhum item corresponde à busca."))
                empty_map_clear.pack()
            else:
                empty_mapping_message.configure(text=_("Este tipo ainda não tem itens."))
                empty_map_new.pack()
            update_total_count()
            update_example_label()
            visible = set(tree_map.get_children())
            if shows_here(session.ref) and session.ref in visible:
                tree_map.selection_set(session.ref)
            if focus_item in visible:
                tree_map.focus(focus_item)
            tree_map.yview_moveto(top)
            render_editor()

        def shows_here(key):
            """Whether ``key`` of the editor's type belongs in the visible list."""
            return key is not None and session.container == mapping_type.get()

        def editor_value():
            return serialize_text_widget_content(text_value)

        def is_dirty():
            return session.is_dirty(name_var.get(), editor_value())

        def stored_value(container, key):
            mapping = self.snippets.get(container)
            if not isinstance(mapping, dict) or key not in mapping:
                return EDITOR_MISSING
            return mapping[key]

        def current_mapping_item():
            """``(type, identifier)`` of the saved item the editor's commands act on, or None."""
            if session.ref is None or stored_value(session.container, session.ref) is EDITOR_MISSING:
                return None
            return session.container, session.ref

        def replaced_name(typed):
            """The other saved item that Salvar would overwrite under ``typed``, or None."""
            container = session.container or mapping_type.get()
            if typed and typed != session.ref and stored_value(container, typed) is not EDITOR_MISSING:
                return typed
            return None

        def mapping_row(container, key):
            return next((candidate for candidate in self._manager_rows()
                         if candidate.kind == "mapping"
                         and candidate.container == container
                         and candidate.stored_trigger == key), None)

        def show_mapping_favorite():
            item = current_mapping_item()
            row = mapping_row(*item) if item else None
            mapping_favorite_var.set(bool(row and row.favorite))

        def render_editor(payload=None):
            """Draw the editor's target, its draft state and the commands that apply."""
            if payload is None:
                payload = editor_value()
            typed = name_var.get().strip()
            dirty = session.is_dirty(typed, payload)
            problem = mapping_draft_problem(typed, extract_plain_text(payload)) if dirty else None
            item = current_mapping_item()
            read_only = bool(getattr(self.library_metadata, "read_only", False))
            _set_enabled(btn_save_map, dirty and problem is None)
            ui_widgets.set_button_variant(btn_save_map, "accent" if dirty and problem is None else "standard", icon="save")
            ui_widgets.set_button_variant(page_new_map, "standard" if dirty and problem is None else "accent", icon="add")
            _set_enabled(btn_delete_map, item is not None)
            _set_enabled(mapping_preview_button, item is not None)
            for widget in (mapping_favorite_check, mapping_form_button):
                _set_enabled(widget, item is not None and not read_only)
            container = session.container or mapping_type.get()
            label = type_label(container)
            hidden = item is not None and shows_here(session.ref) and session.ref not in tree_map.get_children()
            if session.ref is not None:
                target = _("Editando {name} em {type}").format(name=session.ref, type=label)
            elif session.mode == EDITOR_NEW or dirty:
                target = _("Novo item em {type}").format(type=label)
            else:
                target = _("Nenhum item aberto")
            if problem:
                detail = _(problem)
            else:
                notes = []
                if dirty and replaced_name(typed):
                    notes.append(_("Salvar substitui {name}.").format(name=typed))
                elif dirty and item is not None and typed != session.ref:
                    notes.append(_("Salvar cria {name}; {open} continua salvo.").format(
                        name=typed, open=session.ref))
                if hidden:
                    notes.append(_("Oculto pelo filtro atual."))
                if not notes and session.mode == EDITOR_EMPTY and not dirty:
                    notes.append(_("Selecione um item na lista ou clique em Novo."))
                detail = " ".join(notes)
            header.show(target, dirty, detail, hidden)
            row = mapping_rows.get(typed) if shows_here(typed) else None
            prefix = mappings_info.get(container, {}).get("prefix", "")
            effective = row.effective_trigger if row else (prefix + typed if typed else "")
            mapping_effective_trigger_var.set(
                _("Efetivo: {trigger}").format(trigger=effective) if effective else _("Efetivo: —"))
            editor.dirty = dirty
            self._refresh_manager_title()

        def load_item(key):
            """Open item ``key`` of the visible type in the editor."""
            copied_form["value"] = None
            container = mapping_type.get()
            value = stored_value(container, key)
            name_var.set(key)
            load_value_into_text_widget(text_value, "" if value is EDITOR_MISSING else value)
            session.load(key, key, editor_value(), copy.deepcopy(value), container=container)
            show_mapping_favorite()
            header.notice(None)
            update_format_status()

        def clear_editor(*, new=False):
            """Show nothing, or with ``new`` a fresh draft (Novo), in the visible type."""
            copied_form["value"] = None
            name_var.set("")
            load_value_into_text_widget(text_value, "")
            session.reset(new=new, container=mapping_type.get())
            mapping_favorite_var.set(False)
            header.notice(None)
            if tree_map.selection():
                tree_map.selection_remove(tree_map.selection())
            update_format_status()

        def revert_draft():
            """Descartar: the editor shows the saved item again, or nothing."""
            item = current_mapping_item()
            if item is not None and item[0] == mapping_type.get():
                load_item(item[1])
            else:
                clear_editor()

        def draft_question():
            label = type_label(session.container or mapping_type.get())
            if session.ref is not None:
                return _("O item {name} de {type} tem alterações não salvas.").format(
                    name=session.ref, type=label)
            return _("O novo item de {type} tem alterações não salvas.").format(type=label)

        def reconcile_editor():
            """After the library changed: a clean editor follows it; a draft
            is kept and the editor says what changed under it."""
            if session.ref is None:
                render_editor()
                return
            container, name = session.container, session.ref
            outcome = session.reconcile(stored_value(container, name))
            if outcome not in (EDITOR_CHANGED, EDITOR_GONE):
                render_editor()
                return
            if not is_dirty():
                if outcome == EDITOR_GONE or container != mapping_type.get():
                    clear_editor()
                else:
                    load_item(name)
                return

            def use_library():
                if current_mapping_item() == (container, name) and container == mapping_type.get():
                    load_item(name)
                else:
                    clear_editor()

            def keep_draft():
                session.keep_draft(stored_value(container, name))
                header.notice(None)
                refresh_mapping_list()

            self._show_library_conflict(header, outcome, name, use_library, keep_draft)
            render_editor()

        def add_new_type():
            dialog = tk.Toplevel(root)
            dialog.title(_("Novo tipo de mapeamento"))
            dialog.resizable(False, False)
            dialog.transient(root)
            dialog.grab_set()
            dialog.configure(bg=ui.surface)
            self._set_window_icon(dialog)
            ui_theme.prepare_window(dialog, ui)

            body = tk.Frame(dialog, bg=ui.surface, padx=ui.space_xl, pady=ui.space_lg)
            body.pack(fill=tk.BOTH, expand=True)
            tk.Label(body, text=_("Criar novo tipo de mapeamento dinâmico"), font=ui.subtitle_font(), bg=ui.surface, fg=ui.text_native).pack(anchor="w")
            tk.Label(body, text=_("Nome do tipo"), font=ui.font(), bg=ui.surface, fg=ui.text_native).pack(anchor="w", pady=(12, 0))
            entry_type_name = ui_widgets.entry(body)
            entry_type_name.pack(fill=tk.X, pady=(4, 8))
            tk.Label(body, text=_("Prefixo usado no trigger"), font=ui.font(), bg=ui.surface, fg=ui.text_native).pack(anchor="w")
            entry_prefix = ui_widgets.entry(body)
            entry_prefix.pack(fill=tk.X, pady=(4, 8))
            tk.Label(body, text=_("Ex.: tipo 'email' + prefixo 'mail' -> mailtrabalho"), font=ui.caption_font(), fg=ui.text_muted, bg=ui.surface).pack(anchor="w")
            # Present while empty, so an error does not resize the dialog.
            type_error = tk.Label(
                body, text="", font=ui.caption_font(), bg=ui.surface, fg=ui.danger,
                anchor="w", justify=tk.LEFT, wraplength=ui.px(380),
            )
            type_error.pack(fill=tk.X, pady=(ui.space_sm, 0))

            def refuse(message, field):
                type_error.configure(text=message)
                field.focus_set()

            def save_new_type():
                type_name = entry_type_name.get().strip().lower()
                prefix = entry_prefix.get().strip().lower()
                problem = mapping_type_problem(mappings_info, self.snippets, type_name, prefix)
                if problem:
                    field, message = problem
                    refuse(message, entry_type_name if field == "name" else entry_prefix)
                    return

                map_key = mapping_type_key(type_name)
                if not self.create_mapping_type(map_key, prefix):
                    ui_widgets.alert(
                        dialog, _("Erro ao salvar"),
                        _("Não foi possível gravar snippets.json. Verifique os logs; o tipo não foi criado."),
                        tone="danger",
                    )
                    return
                dialog.destroy()
                refresh_type_list()
                self.receipt(N_("Tipo criado às {time}"), type_name, key=f"mapping-type-create:{type_name}")
                # The new type opens unless the person keeps a draft of this one.
                switch_type(map_key)

            # Enter creates and Escape cancels.
            ui_widgets.dialog_footer(
                body, (_("Criar tipo"), save_new_type), dialog.destroy, ui=ui,
            ).pack(fill=tk.X, pady=(ui.space_md, 0))
            center_dialog(dialog, root)
            entry_type_name.focus_set()

        def delete_current_type():
            current_type = mapping_type.get()
            info = mappings_info.get(current_type, {})

            if info.get("builtin", False):
                ui_widgets.alert(root, _("Excluir tipo"), _("Não é possível excluir tipos padrão (CPF, CNPJ)."))
                return
            if current_type not in self.snippets:
                return
            label = info.get("label", current_type)
            items = self.snippets[current_type]
            count = sum(1 for name in items if name != "__prefix__") if isinstance(items, dict) else 0
            # Every item of the type goes with it, so the name has to be typed.
            if not ui_widgets.confirm(
                root,
                _("Excluir tipo"),
                _("O tipo {type} será excluído com todos os itens ({count}).\n\n"
                  "A exclusão não pode ser desfeita aqui; a biblioteca anterior "
                  "continua em Cópias de segurança.").format(type=label, count=count),
                _("Excluir tipo"),
                danger=True,
                typed_word=label,
            ):
                return

            if not self.delete_mapping_type(current_type):
                ui_widgets.alert(
                    root, _("Erro ao salvar"),
                    _("Não foi possível gravar snippets.json. Verifique os logs; o tipo não foi excluído."),
                    tone="danger",
                )
                return

            # The typed confirmation covered the type's items, open draft included.
            clear_editor()
            refresh_type_list()
            available_keys = list(mappings_info.keys())
            if available_keys:
                mapping_type.set(available_keys[0])
                select_type_row(available_keys[0])
            refresh_mapping_list()
            self.receipt(
                N_("Tipo excluído às {time}"), info.get("label", current_type),
                key=f"mapping-type-delete:{current_type}")

        ui_widgets.button(
            btn_types_frame, text=_("Novo tipo"), command=add_new_type, icon="add",
        ).pack(fill=tk.X)
        ui_widgets.button(
            btn_types_frame, text=_("Excluir tipo"), command=delete_current_type,
            variant="danger", icon="delete",
        ).pack(fill=tk.X, pady=(6, 0))

        listbox_types.bind("<<TreeviewSelect>>", on_type_select, add="+")
        self._bind_mousewheel(listbox_types, listbox_types)
        self._bind_mousewheel(text_value, text_value)

        def on_tree_select(_event=None):
            selection = tree_map.selection()
            if not selection or (shows_here(session.ref) and selection[0] == session.ref):
                # The list re-selecting the open item after a rebuild, or a
                # search hiding it: the editor keeps what it shows.
                return
            key = selection[0]
            if not editor.resolve():
                # Cancelar: the list goes back to what the editor still shows.
                if shows_here(session.ref) and session.ref in tree_map.get_children():
                    tree_map.selection_set(session.ref)
                    tree_map.focus(session.ref)
                elif key in tree_map.get_children():
                    tree_map.selection_remove(key)
                return
            load_item(key)
            if key in tree_map.get_children():
                tree_map.selection_set(key)
                tree_map.focus(key)

        def reveal_mapping():
            """Mostrar na lista: clear the search that hides the open item and select it."""
            map_search_var.set("")
            refresh_mapping_list()
            if shows_here(session.ref) and session.ref in tree_map.get_children():
                tree_map.selection_set(session.ref)
                tree_map.focus(session.ref)
                tree_map.see(session.ref)
            tree_map.focus_set()

        def select_mapping_target(descriptor):
            if descriptor.kind != "mapping" or descriptor.container not in type_keys:
                return False
            key = descriptor.stored_trigger
            opened = session.container == descriptor.container and session.ref == key
            if not opened and not editor.resolve():
                # The person kept the draft; there is nothing to report.
                return True
            select_type_row(descriptor.container)
            mapping_type.set(descriptor.container)
            map_search_var.set("")
            refresh_mapping_list()
            if key not in tree_map.get_children():
                return False
            try:
                if self._manager_notebook is not None:
                    self._manager_notebook.select(parent)
            except Exception:
                pass
            if not opened:
                load_item(key)
            tree_map.selection_set(key)
            tree_map.focus(key)
            tree_map.see(key)
            return True

        self._manager_tab_selectors["mapping"] = select_mapping_target

        def on_toggle_mapping_favorite():
            item = current_mapping_item()
            if item is None:
                return
            current_type, key = item
            try:
                result = manager_toggle_mapping_favorite(
                    self.snippets, self.library_metadata, current_type, key,
                    mapping_favorite_var.get(),
                )
                if not self._persist_manager_action(result):
                    show_mapping_favorite()
                    ui_widgets.alert(root, _("Favorito"), _("Não foi possível salvar a alteração."), tone="danger")
            except (KeyError, ValueError, MetadataReadOnlyError) as error:
                show_mapping_favorite()
                self.logger.warning(f"Mapping favorite update failed: {error}")
                ui_widgets.alert(
                    root, _("Favorito"),
                    _("Os metadados da biblioteca são somente leitura nesta versão.") if getattr(self.library_metadata, "read_only", False) else str(error),
                )
            except Exception:
                show_mapping_favorite()
                self.logger.exception("Mapping favorite update failed unexpectedly")
                ui_widgets.alert(root, _("Favorito"), _("Não foi possível salvar a alteração."), tone="danger")

        def on_edit_mapping_form():
            item = current_mapping_item()
            if item is None:
                return
            current_type, key = item
            mapping = self.snippets[current_type]
            from form_editor_dialog import run_form_editor
            definition = self._mapping_form_metadata(current_type, key)
            form = run_form_editor(
                root,
                definition,
                self.snippets,
                template=extract_plain_text(mapping[key]),
                title=_("Editar formulário do mapeamento"),
            )
            if form is None:
                return
            try:
                result = manager_set_mapping_form(
                    self.snippets,
                    self.library_metadata,
                    current_type,
                    key,
                    form,
                    dynamic_triggers=self._manager_dynamic_triggers(),
                )
                if not self._persist_manager_action(result):
                    ui_widgets.alert(
                        root, _("Formulário"), _("Não foi possível salvar a alteração."), tone="danger",
                    )
            except (KeyError, ValueError, MetadataReadOnlyError) as error:
                self.logger.warning(f"Mapping form update failed: {error}")
                ui_widgets.alert(
                    root, _("Formulário"),
                    _("Os metadados da biblioteca são somente leitura nesta versão.")
                    if getattr(self.library_metadata, "read_only", False)
                    else str(error),
                )
            except Exception:
                self.logger.exception("Mapping form update failed unexpectedly")
                ui_widgets.alert(root, _("Formulário"), _("Não foi possível salvar a alteração."), tone="danger")

        def on_preview_mapping():
            item = current_mapping_item()
            if item is None:
                return
            current_type, key = item
            result = resolve_preview(
                self.snippets[current_type][key],
                self.snippets,
                self._mapping_form_metadata(current_type, key),
            )
            controller = getattr(self, "_manager_preview_controller", None)
            if controller is None or controller.shared_root is not root:
                controller = PreviewDialogController(root)
                self._manager_preview_controller = controller
            controller.show(result, title=_("Prévia — {key}").format(key=key))

        def on_type_changed(*args):
            refresh_mapping_list(keep_view=False)
            if is_dirty():
                # Type changes the person makes settle the draft first, so
                # only a refresh that dropped the draft's type gets here; the
                # draft stays and reconcile_editor says why.
                render_editor()
                return
            clear_editor()

        def on_new_map():
            if not editor.resolve():
                return
            clear_editor(new=True)
            name_var.set(map_search_var.get().strip())
            entry_name.focus_set()

        def on_duplicate_map():
            if not editor.resolve():
                return
            item = current_mapping_item()
            if item is None:
                ui_widgets.alert(root, _("Duplicar"), _("Selecione um item."))
                return
            container, key = item
            value = copy.deepcopy(stored_value(container, key))
            form = copy.deepcopy(self._mapping_form_metadata(container, key))
            clear_editor(new=True)
            load_value_into_text_widget(text_value, value)
            copied_form["value"] = form
            update_format_status()
            entry_name.focus_set()

        def on_save_map():
            """Salvar and Ctrl+S. True when nothing is left unsaved."""
            name = name_var.get().strip()
            value = editor_value()
            if not session.is_dirty(name, value):
                return True
            problem = mapping_draft_problem(name, extract_plain_text(value))
            if problem:
                ui_widgets.alert(root, _("Salvar item"), _(problem))
                return False
            # The item goes where the draft belongs, which is the visible type
            # unless the library dropped that type under a kept draft.
            current_type = session.container or mapping_type.get()
            # The editor names one item, but the identifier field can point at
            # another saved one; writing over it must be a choice.
            if replaced_name(name) and not ui_widgets.confirm(
                root,
                _("Substituir item"),
                _("O item {name} de {type} já existe. Salvar troca o texto dele pelo que está no editor.").format(
                    name=name, type=type_label(current_type)),
                _("Substituir"),
                danger=True,
            ):
                return False

            metadata = None
            if copied_form["value"] is not None:
                previous_mapping = self.snippets.get(current_type)
                try:
                    proposed = {**self.snippets, current_type: {
                        **(previous_mapping if isinstance(previous_mapping, dict) else {}), name: value,
                    }}
                    metadata = manager_set_mapping_form(
                        proposed, self.library_metadata, current_type, name, copied_form["value"],
                        dynamic_triggers=self._manager_dynamic_triggers(),
                    ).metadata
                except (KeyError, ValueError, MetadataReadOnlyError) as error:
                    ui_widgets.alert(root, _("Formulário"), str(error), tone="danger")
                    return False
            if not self.save_mapping_item(current_type, name, value, metadata=metadata):
                ui_widgets.alert(
                    root, _("Erro ao salvar"),
                    _("Não foi possível gravar snippets.json, então nada foi salvo. O rascunho "
                      "continua no editor; verifique os logs e tente de novo."),
                    tone="danger",
                )
                return False
            session.mark_saved(name, name, value, copy.deepcopy(value), container=current_type)
            copied_form["value"] = None
            header.notice(None)
            self.receipt(
                N_("Salvo às {time}"), _("{name} em {type}").format(name=name, type=type_label(current_type)),
                key=f"save-map:{current_type}:{name}")
            refresh_type_list()
            refresh_mapping_list()
            if shows_here(name) and name in tree_map.get_children():
                tree_map.see(name)
            update_format_status()
            _move_focus_off(btn_save_map, text_value)
            return True

        def on_delete_map():
            if not editor.resolve():
                return
            item = current_mapping_item()
            if item is None:
                ui_widgets.alert(root, _("Excluir item"), _("Selecione um item."))
                return
            current_type, name = item
            # Deleting is reversible for a while (Desfazer), so it asks
            # nothing; the value and its metadata are kept until then.
            item_metadata = mapping_item_metadata(self.library_metadata, current_type, name)
            removed_value = self.snippets[current_type][name]
            if not self.delete_mapping_item(current_type, name):
                ui_widgets.alert(
                    root, _("Erro ao salvar"),
                    _("Não foi possível gravar snippets.json. Verifique os logs; a exclusão não foi salva."),
                    tone="danger",
                )
                return
            clear_editor()
            refresh_mapping_list()

            def undo():
                try:
                    restored = manager_restore_mapping_item(
                        self.snippets, self.library_metadata, current_type, name,
                        removed_value, item_metadata,
                        dynamic_triggers=self._manager_dynamic_triggers(),
                    )
                    if not self._persist_manager_action(restored):
                        ui_widgets.alert(
                            root, _("Desfazer exclusão"), _("Não foi possível salvar a alteração."),
                            tone="danger",
                        )
                        return
                except (KeyError, ValueError, MetadataReadOnlyError) as error:
                    self.logger.warning(f"Mapping item restore failed: {error}")
                    ui_widgets.alert(
                        root, _("Desfazer exclusão"),
                        _("Não foi possível restaurar {name}: {error}").format(name=name, error=error),
                    )
                    return
                except Exception:
                    self.logger.exception("Mapping item restore failed unexpectedly")
                    ui_widgets.alert(
                        root, _("Desfazer exclusão"), _("Não foi possível salvar a alteração."),
                        tone="danger",
                    )
                    return
                # The editor opens the item again unless it holds a draft by now.
                descriptor = self._manager_target(SnippetRef("mapping", name, current_type))
                if descriptor is not None and not is_dirty() and select_mapping_target(descriptor):
                    tree_map.focus_set()
                receipt.show(_("Restaurado às {time} · {name}").format(
                    time=time_format.clock(datetime.now()), name=name))

            receipt.show(
                _("Excluído às {time} · {name}").format(time=time_format.clock(datetime.now()), name=name),
                _("Desfazer"), undo,
            )

        def mapping_target():
            if session.ref is None:
                return None
            return SnippetRef("mapping", session.ref, session.container)

        editor = self._editor_handle(
            root, header,
            is_dirty=is_dirty,
            save=on_save_map,
            revert=revert_draft,
            question=draft_question,
            target=mapping_target,
        )
        self._register_manager_editor(editor)
        self._register_manager_commands(
            parent, map_search_entry, tree_map, new=on_new_map, save=on_save_map, delete=on_delete_map,
            search_key="mapping",
            duplicate=on_duplicate_map,
            rename=lambda: (entry_name.focus_set(), entry_name.selection_range(0, tk.END)),
            escape=lambda: self._escape_manager_editor(root, map_search_var, is_dirty, draft_question, revert_draft),
        )
        for control, hint in (
            (btn_new_map, _("Ctrl+N — Novo com a busca")), (btn_save_map, _("Ctrl+S — Salvar")),
            (btn_delete_map, _("Delete na lista — Excluir · Desfazer disponível")),
            (entry_name, _("F2: identificador · Ctrl+D: duplicar\nCtrl+S: salvar")),
            (map_search_entry, _("Ctrl+F: busca · ↓/Enter: lista\nEsc: limpar · Ctrl+N: novo com busca")),
            (tree_map, _("F2: identificador · Ctrl+D: duplicar\nDelete: excluir · Desfazer disponível")),
            (text_value, _("Tab/Shift+Tab: navegar · Ctrl+Tab: tabulação\nEsc: descartar com confirmação")),
        ):
            self._shortcut_hint(control, receipt, hint)

        mapping_type.trace_add("write", lambda *_: on_type_changed())
        tree_map.bind("<<TreeviewSelect>>", on_tree_select, add="+")
        btn_new_map.configure(command=on_new_map)
        btn_save_map.configure(command=on_save_map)
        btn_delete_map.configure(command=on_delete_map)
        map_search_var.trace_add("write", lambda *_: self._schedule_manager_search(
            root, "mapping", lambda: refresh_mapping_list(keep_view=False)))
        name_var.trace_add("write", lambda *_: request_editor_update())
        for widget in (entry_name, text_value, tree_map):
            widget.bind("<Control-s>", lambda _event: (on_save_map(), "break")[1])

        def refresh_all_mappings():
            # A restore/import can drop the selected type entirely, so the type
            # list has to be rebuilt before the items are.
            refresh_type_list()
            refresh_mapping_list()
            reconcile_editor()

        refresh_all_mappings()
        self._register_manager_refresher(refresh_all_mappings)
        def capture_view():
            focused = root.focus_get()
            target = {"kind": "mapping", "key": session.ref, "container": session.container} if session.ref else None
            return {"query": map_search_var.get(), "container": mapping_type.get(),
                    "selection": next(iter(tree_map.selection()), ""), "row_focus": tree_map.focus(),
                    **capture_tree_scroll(tree_map), "target": target,
                    "focus": "search" if focused is map_search_entry else "list" if focused is tree_map
                    else "editor" if focused in (entry_name, text_value) else ""}
        def restore_view(state):
            container = state.get("container")
            if container in mappings_info:
                # Construction queues a default-type selection event. Align
                # both selectors before restoring the model/editor so that
                # queued event observes the restored type instead.
                select_type_row(container)
                mapping_type.set(container)
            map_search_var.set(state.get("query", ""))
            refresh_mapping_list(keep_view=False)
            target = state.get("target", {})
            key = target.get("key")
            if target.get("container") == mapping_type.get() and key in mapping_rows:
                load_item(key)
            visible = set(tree_map.get_children())
            if state.get("selection") in visible:
                tree_map.selection_set(state["selection"])
            if state.get("row_focus") in visible:
                tree_map.focus(state["row_focus"])
            restore_tree_scroll(tree_map, state)
            render_editor()
            focused = {"search": map_search_entry, "list": tree_map, "editor": text_value}.get(state.get("focus"))
            if focused is not None:
                focused.focus_set()
        self._manager_views["mapping"] = (capture_view, restore_view)

    def _create_reference_tab(
        self, parent, root, section_title, subtitle, sections, footer_text
    ):
        ui = ui_theme.theme()
        self._page_receipt(parent)
        main = tk.Frame(
            parent, bg=ui.surface, padx=ui.space_lg, pady=ui.space_lg
        )
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        tk.Label(
            main,
            text=section_title,
            font=ui.title_font(),
            bg=ui.surface,
            fg=ui.text,
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            main,
            text=subtitle,
            font=ui.caption_font(),
            bg=ui.surface,
            fg=ui.text_muted,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(ui.space_xs, ui.space_md),
        )

        content = tk.Frame(main, bg=ui.surface)
        content.grid(row=2, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        canvas = tk.Canvas(content, bg=ui.surface, highlightthickness=0)
        scrollbar = ui_widgets.scrollbar(content, command=canvas.yview)
        inner = tk.Frame(canvas, bg=ui.surface)
        inner.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(canvas_window, width=event.width),
        )

        dynamic_rows = {}

        def populate():
            dynamic_rows.clear()
            for child in inner.winfo_children():
                child.destroy()
            grouped = reference_entries_by_category(self.dynamic_registry)
            for title, category_key in sections:
                entries = grouped.get(category_key, [])
                section = ui_widgets.card(inner, padding=(ui.space_lg, ui.space_md))
                section.pack(fill=tk.X, expand=True, pady=(0, ui.space_md))
                tk.Label(
                    section,
                    text=title,
                    font=ui.subtitle_font(),
                    bg=ui.card,
                    fg=ui.text,
                ).pack(anchor="w", pady=(0, ui.space_sm))
                for key, trigger, desc, enabled in entries:
                    row = tk.Frame(section, bg=ui.card)
                    row.pack(fill=tk.X, pady=ui.space_xs)
                    var = tk.BooleanVar(value=enabled)
                    # The switch writes by stable key, not by the (renameable) trigger.
                    ui_widgets.switch(
                        row,
                        text=_("Ativo"),
                        variable=var,
                        command=lambda k=key, v=var: self._on_registry_checkbox(k, v, root),
                    ).pack(side=tk.LEFT)
                    trigger_label = tk.Label(
                        row,
                        text=key if key == trigger else f"{key} → {trigger}",
                        font=ui.mono_font(10, "bold"),
                        fg=ui.link,
                        bg=ui.card,
                        width=24,
                        anchor="w",
                    )
                    trigger_label.pack(side=tk.LEFT)
                    dynamic_rows[key] = (row, trigger_label)
                    rename = (
                        lambda event=None, k=key, t=trigger:
                        self._rename_registry_entry_dialog(root, k, t, populate)
                    )
                    trigger_label.bind("<Double-Button-1>", rename)
                    ui_widgets.button(
                        row, text=_("Renomear"), command=rename,
                        variant="subtle", icon="rename",
                    ).pack(side=tk.RIGHT)
                    tk.Label(
                        row,
                        text=_(desc),
                        font=ui.font(9),
                        bg=ui.card,
                        fg=ui.text_native,
                        anchor="w",
                    ).pack(
                        side=tk.LEFT,
                        padx=(ui.space_md, ui.space_sm),
                        fill=tk.X,
                        expand=True,
                    )
            self._bind_mousewheel_descendants(inner, canvas)

        populate()
        self._register_manager_refresher(populate)

        tk.Label(
            main,
            text=footer_text,
            font=ui.caption_font(),
            fg=ui.text_muted,
            bg=ui.surface,
        ).grid(row=3, column=0, sticky="w", pady=(ui.space_md, 0))

        self._bind_mousewheel(canvas, canvas)

        def select_dynamic_target(descriptor):
            if descriptor.kind != "dynamic":
                return False
            widgets = dynamic_rows.get(descriptor.stored_trigger)
            if widgets is None:
                return False
            row, trigger_label = widgets
            try:
                if self._manager_notebook is not None:
                    self._manager_notebook.select(parent)
            except Exception:
                pass
            row.configure(highlightbackground=ui.focus_ring, highlightthickness=1)
            trigger_label.focus_set()
            return True

        self._manager_tab_selectors["dynamic"] = select_dynamic_target

    def _on_registry_checkbox(self, key, var, parent=None):
        """Apply a checkbox toggle, snapping the box back when it is refused."""
        enabled = var.get()
        if not self._toggle_registry_entry(key, enabled, parent=parent):
            var.set(not enabled)

    def _toggle_registry_entry(self, key, enabled, *, parent=None):
        """Enable/disable a dynamic trigger, persisting to the user override file.

        Keyed by the stable registry id so a renamed trigger still writes the
        right override entry. Returns True when the change was applied.
        """
        if enabled and not self._confirm_dynamic_shadows_static(key, parent=parent):
            return False

        try:
            if os.path.exists(self.dynamic_registry_file):
                user_override = load_json_file(self.dynamic_registry_file)
                if not isinstance(user_override, dict):
                    user_override = {}
            else:
                user_override = {}
            # Store a minimal per-field override so future bundled changes to other
            # fields of this trigger still reach the user.
            existing = user_override.get(key)
            entry = dict(existing) if isinstance(existing, dict) else {}
            entry["enabled"] = enabled
            user_override[key] = entry
            write_json_atomic(self.dynamic_registry_file, user_override)
        except Exception as e:
            self.logger.error(f"Falha ao salvar registro dinâmico: {e}")
            self.notify_error(_("Falha ao salvar alteração do snippet dinâmico."), key="registry-save")
            return False

        self.dynamic_registry = load_registry(
            self.resolve_resource_path("dynamic_snippets.json"),
            self.dynamic_registry_file,
            logger=self.logger,
        )
        self.reload_snippets_from_disk()
        if getattr(self, "manager_window", None) is not None:
            self.gui.submit(self._refresh_manager_lists)
        self.export_sync_bundle()
        trigger = effective_trigger(key, self.dynamic_registry.get(key, {}))
        self.receipt(
            N_("Ativado às {time}") if enabled else N_("Desativado às {time}"),
            trigger, key=f"registry-toggle:{key}")
        return True

    def _confirm_dynamic_shadows_static(self, key, *, parent=None):
        """Ask before enabling a dynamic trigger that shadows an existing trigger.

        ``validate_rename`` blocks both collisions when they come from a rename;
        the enable toggle reaches the same state, so it needs the same check.
        Enabling is allowed with confirmation: the shadowed value stays on disk
        (a static snippet in ``snippets.json``, or the mapping container a
        composed trigger like ``cpffulano`` is built from), and the dynamic
        snippet is what expands. ``parent`` is the window that owns the question.
        """
        trigger = effective_trigger(key, self.dynamic_registry.get(key, {}))
        if trigger.startswith("_"):
            return True

        static_snippets = build_saveable_snippets(
            self.snippets,
            self.shadowed_static_snippets,
        )
        static_row = next(
            (
                row
                for row in build_manager_rows(
                    static_snippets,
                    self.library_metadata,
                    self.dynamic_registry,
                )
                if row.kind == "static" and row.effective_trigger == trigger
            ),
            None,
        )
        if static_row is not None:
            self.logger.warning(
                f"Ativar o snippet dinâmico '{trigger}' sobrepõe o snippet estático de mesmo nome."
            )
            return ui_widgets.confirm(
                parent,
                _("Trigger em conflito"),
                _("Já existe um snippet estático com o trigger '{trigger}'.\n\nAo ativar o "
                  "dinâmico, é ele que passa a expandir. O texto estático continua salvo em "
                  "snippets.json, mas deixa de ser acionado.").format(trigger=trigger),
                _("Ativar mesmo assim"),
            ) == ui_widgets.PRIMARY

        # A mapping-composed trigger (e.g. ``cpffulano`` from the ``_cpf_numbers``
        # container) is never a direct key in ``self.snippets`` — it resolves via
        # ``check_dynamic_pattern`` against the ``_``-prefixed container — so the
        # direct lookup above misses it. Enabling the dynamic entry still changes
        # what the user's typing expands to, so it needs the same confirmation.
        if trigger in composed_mapping_triggers(self.snippets):
            self.logger.warning(
                f"Ativar o snippet dinâmico '{trigger}' sobrepõe um mapeamento dinâmico de mesmo nome."
            )
            return ui_widgets.confirm(
                parent,
                _("Trigger em conflito"),
                _("Já existe um mapeamento dinâmico com o trigger '{trigger}'.\n\nAo ativar o "
                  "snippet dinâmico, é ele que passa a expandir. O valor mapeado continua "
                  "salvo no container de mapeamento, mas deixa de ser acionado.").format(trigger=trigger),
                _("Ativar mesmo assim"),
            ) == ui_widgets.PRIMARY

        return True

    def _create_dynamic_snippets_tab(self, parent, root):
        """Build the single tab listing every built-in dynamic snippet."""
        ui = ui_theme.theme()
        self._page_receipt(parent)
        main = tk.Frame(ui_widgets.page_viewport(parent), bg=ui.surface, padx=ui.space_lg, pady=ui.space_lg)
        main.pack(fill=tk.BOTH, expand=True)
        tk.Label(main, text=_("Snippets dinâmicos integrados"), font=ui.title_font(),
                 bg=ui.surface, fg=ui.text).pack(anchor="w")
        search_row = tk.Frame(main, bg=ui.surface)
        search_row.pack(fill=tk.X, pady=ui.space_md)
        tk.Label(search_row, text=_("Buscar"), font=ui.font(), bg=ui.surface,
                 fg=ui.text).pack(side=tk.LEFT, padx=(0, ui.space_sm))
        query = tk.StringVar(main)
        search = ui_widgets.entry(search_row, textvariable=query)
        search.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._manager_search_entries[str(parent)] = search
        count = tk.StringVar(main)
        tk.Label(search_row, textvariable=count, font=ui.caption_font(),
                 bg=ui.surface, fg=ui.text_muted).pack(side=tk.RIGHT, padx=ui.space_sm)
        commands = tk.Frame(main, bg=ui.surface)
        commands.pack(fill=tk.X, pady=(0, ui.space_sm))
        shell = ui_widgets.list_frame(main)
        shell.pack(fill=tk.BOTH, expand=True)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)
        tree = ui_widgets.tree_list(shell, columns=("state", "trigger", "description"), headings=True)
        tree.column("#0", width=ui.px(22), stretch=False)
        for column, label, width in (("state", _("Ativo"), 90),
                                     ("trigger", "Trigger", 220),
                                     ("description", _("Descrição"), 350)):
            tree.heading(column, text=label, anchor="w")
            tree.column(column, width=ui.px(width), minwidth=ui.px(60),
                        stretch=column == "description", anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ui_widgets.scrollbar(shell, command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        self._bind_mousewheel(tree, tree)
        row_keys = {}
        categories = {
            "datetime": _("Data e Hora"),
            "economy": _("Indicadores Econômicos (Banco Central)"),
            "stock": _("Ações (B3 e US)"),
            "whatsapp": "WhatsApp",
        }
        def selected_key():
            return row_keys.get(next(iter(tree.selection()), ""))
        def selection_changed(_event=None):
            key = selected_key()
            enabled = key is not None
            toggle.configure(state=tk.NORMAL if enabled else tk.DISABLED,
                             text=_("Desativar") if enabled and is_enabled(self.dynamic_registry[key])
                             else _("Ativar"))
            rename.configure(state=tk.NORMAL if enabled else tk.DISABLED)
        def populate(*_args):
            selected = selected_key()
            scroll = tree.yview()
            for group in tree.get_children():
                children = tree.get_children(group)
                if children:
                    tree.detach(*children)
                tree.detach(group)
            tree.selection_remove(tree.selection())
            row_keys.clear()
            needle = query.get().strip().casefold()
            total = shown = 0
            for category, entries in reference_entries_by_category(self.dynamic_registry).items():
                title = categories.get(category, category)
                matches = []
                for key, trigger, description, enabled in entries:
                    total += 1
                    desc = _(description)
                    if not needle or needle in " ".join((title, key, trigger, desc)).casefold():
                        matches.append((key, trigger, desc, enabled))
                if not matches:
                    continue
                group = "category:" + category
                if tree.exists(group):
                    tree.item(group, values=("", "", title))
                    tree.move(group, "", tk.END)
                else:
                    tree.insert("", tk.END, iid=group, values=("", "", title), open=True)
                for key, trigger, description, enabled in matches:
                    row = "action:" + key
                    values = (
                        _("Ativo") if enabled else _("Inativo"),
                        key if key == trigger else f"{key} → {trigger}", description)
                    if tree.exists(row):
                        tree.item(row, values=values)
                        tree.move(row, group, tk.END)
                    else:
                        tree.insert(group, tk.END, iid=row, values=values)
                    row_keys[row] = key
                    shown += 1
                    if key == selected:
                        tree.selection_set(row)
                        tree.focus(row)
            count.set(_("{shown} de {total}").format(shown=shown, total=total))
            if scroll:
                tree.yview_moveto(scroll[0])
            selection_changed()
        def toggle_selected(_event=None):
            key = selected_key()
            if key is not None and self._toggle_registry_entry(
                    key, not is_enabled(self.dynamic_registry[key]), parent=root):
                populate()
            return "break"
        def rename_selected(_event=None):
            key = selected_key()
            if key is not None:
                self._rename_registry_entry_dialog(root, key,
                    effective_trigger(key, self.dynamic_registry[key]), populate)
            return "break"
        toggle = ui_widgets.button(commands, text=_("Ativar"), command=toggle_selected)
        toggle.pack(side=tk.LEFT)
        rename = ui_widgets.button(commands, text=_("Renomear"), command=rename_selected)
        rename.pack(side=tk.LEFT, padx=ui.space_sm)
        tree.bind("<<TreeviewSelect>>", selection_changed, add="+")
        tree.bind("<space>", toggle_selected)
        tree.bind("<F2>", rename_selected)
        def double_click(event):
            row = tree.identify_row(event.y)
            if row in row_keys:
                tree.selection_set(row)
                return toggle_selected()
        tree.bind("<Double-Button-1>", double_click)
        self._manager_commands[str(parent)] = {
            "search": search, "tree": tree, "rename": rename_selected,
            "escape": lambda: query.set(""),
        }
        def enter_list(_event):
            self._flush_manager_search("dynamic")
            row = next(iter(row_keys), None)
            if row is not None:
                tree.selection_set(row)
                tree.focus(row)
                tree.see(row)
                tree.focus_set()
            return "break"
        search.bind("<Return>", enter_list)
        search.bind("<Down>", enter_list)
        query.trace_add("write", lambda *_: self._schedule_manager_search(root, "dynamic", populate))
        self._register_manager_refresher(populate)
        def select_dynamic_target(descriptor):
            if descriptor.kind != "dynamic":
                return False
            query.set("")
            populate()
            row = next((row for row, key in row_keys.items()
                        if key == descriptor.stored_trigger), None)
            if row is None:
                return False
            if self._manager_notebook is not None:
                self._manager_notebook.select(parent)
            tree.selection_set(row)
            tree.focus(row)
            tree.see(row)
            tree.focus_set()
            return True
        self._manager_tab_selectors["dynamic"] = select_dynamic_target
        populate()
        def capture_view():
            return {"query": query.get(), "selection": selected_key() or "",
                    **capture_tree_scroll(tree, expanded_tree_rows(tree)),
                    "row_focus": tree.focus(),
                    "focus": "search" if root.focus_get() is search else "list" if root.focus_get() is tree else ""}
        def restore_view(state):
            query.set(state.get("query", ""))
            populate()
            selected = "action:" + state.get("selection", "")
            if selected in row_keys:
                tree.selection_set(selected)
                tree.focus(selected)
            focused_row = state.get("row_focus")
            if focused_row in row_keys or focused_row in tree.get_children():
                tree.focus(focused_row)
            restore_tree_scroll(tree, state, expanded_tree_rows(tree))
            focused = {"search": search, "list": tree}.get(state.get("focus"))
            if focused is not None:
                focused.focus_set()
        self._manager_views["dynamic"] = (capture_view, restore_view)

    def _rename_registry_entry_dialog(self, root, key, current_trigger, refresh):
        """Ask for a new trigger name, validate it, then persist and refresh."""
        static_snippets = build_saveable_snippets(
            self.snippets,
            self.shadowed_static_snippets,
        )
        found = {}

        def problem(value):
            if not value:
                return _("Informe um trigger.")
            if value == current_trigger:
                return None
            errors, warnings = validate_rename(
                self.dynamic_registry,
                key,
                value,
                static_snippets,
                self.library_metadata,
            )
            found["warnings"] = warnings
            return "\n".join(errors) or None

        new_trigger = ui_widgets.ask_text(
            root,
            _("Renomear trigger"),
            _("Identificador armazenado: {key}\nTrigger efetivo atual: "
              "{current_trigger}\n\nNovo trigger efetivo:").format(key=key, current_trigger=current_trigger),
            current_trigger,
            validate=problem,
            primary_label=_("Renomear"),
        )
        if new_trigger is None or new_trigger == current_trigger:
            return
        warnings = found.get("warnings")
        if warnings and not ui_widgets.confirm(
            root,
            _("Confirmar trigger"),
            "\n".join(warnings),
            _("Renomear mesmo assim"),
        ):
            return

        if self._rename_registry_entry(key, new_trigger):
            refresh()

    def _rename_registry_entry(self, key, new_trigger):
        """Persist a trigger rename to the user override file. Returns success."""
        try:
            if os.path.exists(self.dynamic_registry_file):
                user_override = load_json_file(self.dynamic_registry_file)
                if not isinstance(user_override, dict):
                    user_override = {}
            else:
                user_override = {}
            existing = user_override.get(key)
            entry = dict(existing) if isinstance(existing, dict) else {}
            if new_trigger == key:
                # Back to the bundled name: drop the override field entirely.
                entry.pop("trigger", None)
            else:
                entry["trigger"] = new_trigger
            if entry:
                user_override[key] = entry
            else:
                user_override.pop(key, None)
            write_json_atomic(self.dynamic_registry_file, user_override)
        except Exception as e:
            self.logger.error(f"Falha ao renomear trigger dinâmico: {e}")
            self.notify_error(_("Falha ao salvar o novo nome do snippet dinâmico."), key="registry-save")
            return False

        self.dynamic_registry = load_registry(
            self.resolve_resource_path("dynamic_snippets.json"),
            self.dynamic_registry_file,
            logger=self.logger,
        )
        self.reload_snippets_from_disk()
        self.export_sync_bundle()
        self.receipt(N_("Renomeado às {time}"), new_trigger, key=f"registry-rename:{key}")
        return True

    # =====================================================================
    # UI / SYSTEM TRAY
    # =====================================================================

    def create_icon_image(self):
        """The tray icon drawn from scratch, for a build without ``sniptype.ico``."""
        size = 64
        ring_color = (38, 92, 255, 255)
        accent_color = (27, 43, 65, 255)
        mark_color = (255, 255, 255, 255)

        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        dc = ImageDraw.Draw(image)

        # Outer rounded tile for better legibility at small tray sizes.
        dc.rounded_rectangle((8, 8, 56, 56), radius=16, fill=ring_color)
        dc.rounded_rectangle((13, 13, 51, 51), radius=12, fill=accent_color)

        # Stylized expansion mark: a stem plus three offset rails.
        dc.rounded_rectangle((20, 17, 27, 47), radius=4, fill=mark_color)
        dc.rounded_rectangle((29, 17, 44, 24), radius=4, fill=mark_color)
        dc.rounded_rectangle((29, 29, 44, 36), radius=4, fill=mark_color)
        dc.rounded_rectangle((29, 41, 40, 48), radius=4, fill=mark_color)

        return image

    def load_tray_icon(self):
        """The tray icon for the current expansion state.

        The shipped ICO (better tray compatibility) while expansion is on;
        while it is paused or the capture failed, the same icon with a state
        badge drawn at runtime (tray_support), so no asset ships per state.
        """
        base = None
        icon_path = self.resolve_resource_path("sniptype.ico")
        if icon_path:
            try:
                with Image.open(icon_path) as image:
                    base = image.copy()
            except Exception as e:
                self.logger.warning(f"Falha ao carregar icone do tray: {e}")
        if base is None:
            base = self.create_icon_image()
        return tray_support.state_icon(base, self._expansion_state())

    def _expansion_state(self):
        """``ok``, ``paused`` or ``down`` (health_support.expansion_state)."""
        return health_support.expansion_state(self.enabled, self.capture_error)

    def _apply_tray_state(self, _root=None):
        """Draw the tray icon, tooltip and menu for the current state.

        Redrawn only when the state changes (toggle, capture failure), never
        on a timer. ``_root`` is the arg the GuiThread pump passes.
        """
        icon = self.icon
        if icon is None:
            return
        try:
            icon.icon = self.load_tray_icon()
            icon.title = tray_support.tooltip(APP_DISPLAY_NAME, self._expansion_state())
        except Exception as e:
            self.logger.warning(f"Falha ao atualizar o ícone da bandeja: {e}")
        self._update_tray_menu()

    def refresh_tray_state(self):
        """Show the current expansion state in the tray, from any thread.

        macOS may only touch its status item on the main thread, so there the
        redraw goes through the GuiThread pump, as ``refresh_tray_menu`` does.
        """
        if not self.icon:
            return
        if platform_support.tray_menu_updates_on_gui_thread():
            self.gui.submit(self._apply_tray_state)
            return
        self._apply_tray_state()

    def tray_toggle_label(self, item=None):
        """The first tray line: "Expansão ativa", with the native check as its
        only mark (unchecked is paused), or "Captura falhou"."""
        down = self._expansion_state() == health_support.EXPANSION_DOWN
        return health_support.expansion_label(
            health_support.EXPANSION_DOWN if down else health_support.EXPANSION_OK)

    def tray_toggle_checked(self, item=None):
        return self._expansion_state() == health_support.EXPANSION_OK

    def tray_toggle_enabled(self, item=None):
        # Nothing resumes a failed capture; the line only reports it.
        return self.capture_error is None

    def toggle_enabled(self, icon, item, *, in_manager=False):
        """Pause or resume snippet expansion.

        The tray menu and the hotkey call it with pystray's ``(icon, item)``.
        ``in_manager`` says the person did it in the window, whose receipt
        replaces the status line at once: a pause and the resume that follows
        within the toast cooldown must both be written, or the line keeps
        saying "pausada" over a sidebar that says "ativa".
        """
        if not self.enabled and self.capture_error is not None:
            # No listener runs after a capture failure, so "Expansão ativa"
            # would claim an expansion that cannot happen.
            self.notify_error(
                _("A captura de teclado falhou, então a expansão não pode ser "
                  "retomada. Reinicie o SnipType."),
                key="toggle-enabled-capture-error",
            )
            return
        # A partial trigger typed before the toggle must not complete after it.
        self.typed_text = ""
        self.enabled = not self.enabled
        self.refresh_tray_state()
        self.receipt(
            N_("Expansão retomada às {time}") if self.enabled else N_("Expansão pausada às {time}"),
            key="toggle-enabled", in_manager=in_manager)
        self.gui.submit(self._refresh_manager_status)

    def _refresh_manager_status(self, _root=None):
        """Refresh the visible manager state on the GUI thread.

        The sidebar names the expansion state in one of three ways (health
        support): a quiet dot with a muted word while it is on, and a toned
        icon with a bold written state while it is paused or the capture
        failed. The InfoBar above the pages carries the same news with its
        recovery action.
        """
        status = self._manager_status_var
        button = self._manager_toggle_button
        if status is None or button is None:
            return
        ui = ui_theme.theme()
        state = self._expansion_state()
        status.set(health_support.expansion_label(state))
        label, icon = self._manager_status_label, self._manager_status_icon
        if state == health_support.EXPANSION_DOWN:
            tone, glyph, weight = ui.danger, "error", "bold"
            button.configure(text=_("Reinicie o SnipType"), state=tk.DISABLED)
            ui_widgets.set_icon(button, "refresh")
        elif state == health_support.EXPANSION_PAUSED:
            tone, glyph, weight = ui.warning, "pause", "bold"
            button.configure(text=_("Retomar expansão"))
            ui_widgets.set_icon(button, "play")
        else:
            tone, glyph, weight = ui.text_muted, None, None
            button.configure(text=_("Pausar expansão"))
            ui_widgets.set_icon(button, "pause")
        if label is not None:
            label.configure(
                fg=tone, font=ui.font(ui_theme.BODY_FONT_SIZE, weight))
        if icon is not None:
            # The quiet state is the dot in the success tone, whose word stays muted.
            picture = ui_widgets.signal_image(
                icon, ui.success if glyph is None else tone, glyph, ui=ui)
            icon.configure(image=picture)
            icon.image = picture
        self._refresh_manager_health()

    def _install_callback_hook(self, root):
        """Make an exception in any Tk callback visible instead of lost. GUI thread.

        Tk prints it to stderr, which the windowed build never shows, so a
        failing button would simply do nothing.
        """
        root.report_callback_exception = self._report_callback_exception

    def _report_callback_exception(self, exc_type, exc, tb):
        """A Tk callback raised: keep the traceback in the log and tell the person."""
        self.logger.error(
            "Exceção em um callback da GUI:\n"
            + "".join(traceback.format_exception(exc_type, exc, tb)))
        self.notify_error(
            _("Erro inesperado: {error}").format(error=exc),
            key="gui-callback-error",
            cooldown_seconds=5,
        )

    def _health_facts(self):
        """What the health projection reads, from the state the app holds."""
        metadata = self.library_metadata
        return health_support.HealthFacts(
            enabled=self.enabled,
            capture_error=self.capture_error,
            library_recovery=self.library_recovery,
            metadata_read_only=bool(getattr(metadata, "read_only", False)),
            metadata_malformed=bool(getattr(metadata, "malformed", False)),
            shadowed=tuple(sorted(self.shadowed_static_snippets)),
            last_save_error=self.last_save_error,
            last_mirror=self.last_mirror,
            last_sync=self.last_sync,
        )

    def _manager_issues(self):
        """The open issues the person has not dismissed, most severe first."""
        return [
            issue for issue in health_support.build_health(self._health_facts())
            if issue.id not in self._dismissed_health
        ]

    def _refresh_manager_health(self, _root=None):
        """Redraw the InfoBar, and the Dados card's lines, for what is open now. GUI thread."""
        bar = self._manager_health
        if bar is None:
            return
        if self._manager_data_refresh is not None:
            self._manager_data_refresh()
        tones = {
            health_support.ERROR: "danger",
            health_support.WARNING: "warning",
            health_support.INFO: "info",
        }
        bar.show([
            ui_widgets.InfoRow(
                tones[issue.severity], issue.title, issue.body,
                (issue.action_label,
                 lambda action=issue.action_id: self._run_health_action(action)
                 ) if issue.action_id else None,
                (lambda issue_id=issue.id: self._dismiss_health(issue_id))
                if issue.dismissible else None,
            )
            for issue in self._manager_issues()
        ])

    def _request_health_refresh(self):
        """Redraw an open manager's InfoBar; safe from any thread, a no-op when closed."""
        if self._manager_health is not None:
            self.gui.submit(self._refresh_manager_health)

    def _library_replaced(self):
        """Another library is in place (recovery, restore, import). Any thread.

        The InfoBar reads the new state, and every status line returns to rest:
        a receipt describes what the person did to the library that was there,
        and would otherwise keep naming an item that may no longer exist, or
        offer Desfazer on it.
        """
        self._request_health_refresh()
        if self._manager_receipts:
            self.gui.submit(self._reset_manager_receipts)

    def _reset_manager_receipts(self, _root=None):
        """Return every status line of the open manager to its resting text. GUI thread."""
        for receipt in self._manager_receipts.values():
            receipt.reset()

    def _dismiss_health(self, issue_id):
        """Hide an info issue for the rest of the session."""
        self._dismissed_health.add(issue_id)
        self._refresh_manager_health()

    def _show_manager_page(self, name):
        notebook, page = self._manager_notebook, self._manager_pages.get(name)
        if notebook is not None and page is not None:
            notebook.select(page)

    def _run_health_action(self, action_id):
        """The one recovery action an issue offers. GUI thread."""
        if action_id == health_support.RESUME:
            self.toggle_enabled(self.icon, None, in_manager=True)
        elif action_id == health_support.OPEN_BACKUPS:
            self._show_manager_page("backups")
        elif action_id == health_support.OPEN_DYNAMIC:
            self._show_manager_page("dynamic")
        elif action_id == health_support.OPEN_FOLDER:
            self.open_data_folder()
        elif action_id == health_support.OPEN_LOG:
            self.open_log()
        elif action_id == health_support.RETRY_SYNC:
            self.retry_sync()
            self._refresh_manager_health()
        else:
            raise ValueError(f"unknown health action: {action_id!r}")

    def _track_manager_visibility(self, window):
        """Keep ``_manager_visible`` true exactly while ``window`` is mapped.

        Receipts are written on the status line only while the person can see
        it; a minimized or closed manager leaves them to the tray.
        """
        def set_visible(visible):
            def handler(event):
                if event.widget is window:
                    self._manager_visible = visible
                    if visible:
                        self._cancel_manager_search(window)
                        self._flush_manager_search()
                        self._start_system_appearance_poll(window)
                    else:
                        self._stop_system_appearance_poll(window)
                        self._cancel_manager_search(window)
            return handler

        window.bind("<Map>", set_visible(True), add="+")
        window.bind("<Unmap>", set_visible(False), add="+")
        self._manager_visible = False

    def edit_last_snippet(self, icon=None, item=None):
        """Queue the manager at the most recently successful snippet."""
        self._dispatch_hotkey_action("edit_last")
    
    
    def reload_snippets(self, icon, item):
        """Tray Atualizar biblioteca: read the library from disk again."""
        if self.manager_window is not None:
            # An open manager may hold drafts; it settles them on the GUI
            # thread, never from a tray callback (see gui_thread).
            self.gui.submit(self._reload_snippets_in_manager)
            return
        if self._reload_snippets() and self.manager_window is not None:
            # The manager opened while the library was being read and shows
            # the snapshot from before; its refresh reconciles any draft.
            self.gui.submit(self._refresh_manager_lists)

    def _reload_snippets_in_manager(self, _root=None):
        """Atualizar biblioteca with the manager open. GUI thread."""
        window = self.manager_window
        if window is not None and not self._resolve_manager_drafts(window):
            return
        self._reload_snippets(refresh_manager=True)

    def _reload_snippets(self, *, refresh_manager=False):
        """Read the library again. True when it was read."""
        try:
            self.snippets = self.load_snippets()
            self.refresh_runtime_indexes()
        except Exception as e:
            self.notify_error(
                _("Erro ao atualizar a biblioteca: {error}").format(error=e),
                key="reload-snippets-error",
                cooldown_seconds=5,
            )
            return False
        if refresh_manager:
            self._refresh_manager_lists()
        self.notify_status(_("Biblioteca atualizada."), key="reload-snippets")
        return True

    def tray_backup_now(self, icon, item):
        """Tray action: create an immediate backup of the library."""
        created = self.backup_now()
        if created:
            self.notify_status(_("Backup criado: {name}").format(name=os.path.basename(created)), key="manual-backup")
        else:
            self.notify_error(_("Falha ao criar backup. Verifique os logs."), key="manual-backup")

    def autostart_is_enabled(self, item=None):
        """Menu state for the autostart toggle: a cache read, never a disk read."""
        return self._autostart_state == AUTOSTART_CURRENT

    def autostart_menu_label(self, item=None):
        # The ellipsis says the click opens Windows Settings instead of toggling.
        if self._autostart_state == AUTOSTART_MANAGED:
            return _("Iniciar com o sistema…")
        return _("Iniciar com o sistema")

    def resolve_autostart_state(self):
        """Classify the autostart entry once at startup and repair a dead one.

        Worker-thread only: reading a Windows ``.lnk`` shells out to PowerShell.

        Repair is deliberately narrow. An entry whose target no longer exists (a
        deleted ``dist`` folder, a removed venv or checkout) is dead at login and nobody
        meant to keep it, so rewrite it to the running copy. An entry pointing at
        a *different but installed* copy is left alone: a source checkout and the
        packaged release legitimately coexist, and clobbering the release's
        shortcut on every dev run would be its own bug. It shows as unchecked —
        the toggle repoints it here when the user asks for that.
        """
        if not self._autostart_lock.acquire(blocking=False):
            return
        try:
            if is_msix_packaged():
                # Never read or "repair" a Startup shortcut here: a packaged
                # process's AppData writes are virtualized and its path moves on
                # every Store update. The manifest's startup task owns autostart.
                self._autostart_state = AUTOSTART_MANAGED
                return
            existing = read_autostart_command(APP_NAME)
            state = classify_autostart(existing)
            if state == AUTOSTART_STALE and not autostart_target_exists(existing):
                state = self._repair_autostart(existing)
            elif state == AUTOSTART_STALE:
                self.logger.info(
                    "Inicialização automática aponta para outra instalação: "
                    f"{existing[0]}"
                )
            self._autostart_state = state
        except Exception as e:
            # Unreadable or unparseable entry (PowerShell failure, corrupt
            # plist/desktop file): report it unchecked rather than claim it
            # works. Broad on purpose — task_runner threads have no wrapper,
            # so anything escaping here would die invisibly under pythonw.
            self.logger.warning(f"Falha ao verificar inicialização automática: {e}")
            self._autostart_state = AUTOSTART_STALE
        finally:
            self._autostart_lock.release()
            self.refresh_tray_menu()

    def _repair_autostart(self, existing):
        """Rewrite an autostart entry whose target is gone. Caller holds the lock."""
        dead = existing[0] if existing else "(vazio)"  # i18n: not ui
        try:
            path = install_autostart(APP_NAME)
        except OSError as e:
            self.logger.error(f"Falha ao corrigir inicialização automática: {e}")
            return AUTOSTART_STALE
        self.logger.info(
            f"Inicialização automática apontava para um alvo inexistente ({dead}); "
            f"atualizada para esta instalação: {path}"
        )
        return AUTOSTART_CURRENT

    # =====================================================================
    # MACOS PERMISSIONS (TCC)
    # =====================================================================

    def macos_permissions_pending(self, item=None):
        """Menu state for the permission entry: a cache read, never a probe."""
        return bool(macos_permissions.denied_permissions(self._macos_permission_status))

    def resolve_macos_permissions(self):
        """Probe the macOS grants once at startup and onboard when one is missing.

        Worker-thread only. This is the app's only chance to notice: pynput's
        darwin backend does not raise when untrusted, it just never delivers a
        key, so without this probe a denied Mac looks like an app that runs and
        silently does nothing (issue #24 field notes).
        """
        if not IS_MAC:
            return

        try:
            status = macos_permissions.check_permissions()
        except Exception as e:
            # Broad on purpose: task_runner threads have no wrapper, and an
            # escape here would die invisibly under pythonw.
            self.logger.warning(f"Falha ao verificar permissões do macOS: {e}")
            return

        self._macos_permission_status = status
        self.logger.info(f"Permissões do macOS: {macos_permissions.describe_status(status)}")

        unknown = macos_permissions.unknown_permissions(status)
        if unknown:
            names = ", ".join(macos_permissions.PERMISSION_LABELS[name] for name in unknown)
            # Not a prompt: a grant we cannot read is a state we cannot tell the
            # user to fix, so it is logged and the app carries on.
            self.logger.warning(f"Permissões do macOS não verificáveis: {names}")

        if not macos_permissions.needs_onboarding(status):
            self.logger.info("Permissões do macOS concedidas.")
            return

        denied = ", ".join(
            macos_permissions.PERMISSION_LABELS[name]
            for name in macos_permissions.denied_permissions(status)
        )
        self.logger.error(f"Permissões do macOS ausentes: {denied}. A expansão não vai funcionar.")
        self.notify_error(
            macos_permissions.build_tray_message(status),
            key="macos-permissions",
            cooldown_seconds=60,
        )
        self.refresh_tray_menu()
        self.open_macos_permission_window()

    def tray_macos_permissions(self, icon, item):
        """Tray action: re-open the permission window."""
        self.open_macos_permission_window()

    def open_macos_permission_window(self):
        """Show the permission window on the GUI thread. Never blocks the caller."""
        try:
            self.gui.submit(self._show_macos_permission_window)
        except Exception as e:
            self.logger.error(f"Erro ao abrir a janela de permissões do macOS: {e}")

    def _show_macos_permission_window(self, tk_root):
        """Build the permission window, or raise the one already open. GUI thread only.

        Deliberately modeless: unlike an expansion dialog nothing waits on the
        answer, and the user has to leave the app entirely (System Settings) to
        act on it.
        """
        window = self.macos_permission_window
        try:
            already_open = window is not None and bool(window.winfo_exists())
        except Exception:
            already_open = False

        if already_open:
            window.deiconify()
            window.lift()
            window.focus_force()
            return

        ui = ui_theme.bind(tk_root)
        status = dict(self._macos_permission_status)
        window = tk.Toplevel(tk_root)
        self.macos_permission_window = window
        window.title(_("Permissões do macOS"))
        window.resizable(False, False)
        window.configure(bg=ui.surface)
        window.attributes("-topmost", True)
        self._set_window_icon(window)
        ui_theme.prepare_window(window, ui)

        container = tk.Frame(window, bg=ui.surface, padx=18, pady=18)
        container.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            container,
            text=_("Permissões necessárias"),
            font=ui.subtitle_font(),
            bg=ui.surface,
            fg=ui.text,
        ).pack(anchor="w")

        body = tk.Label(
            container,
            text=macos_permissions.build_prompt_message(status),
            justify=tk.LEFT,
            font=ui.font(10),
            bg=ui.surface,
            fg=ui.text,
        )
        body.pack(anchor="w", pady=(8, 12))

        feedback = tk.Label(
            container,
            text="",
            justify=tk.LEFT,
            wraplength=420,
            font=ui.font(10),
            bg=ui.surface,
            fg=ui.warning,
        )
        feedback.pack(anchor="w", pady=(0, 10))

        panes = tk.Frame(container, bg=ui.surface)
        panes.pack(fill=tk.X)
        for name in macos_permissions.denied_permissions(status):
            ui_widgets.button(
                panes,
                text=_("Abrir {permission}").format(permission=_(macos_permissions.PERMISSION_LABELS[name])),
                command=lambda permission=name: self._open_macos_settings_pane(permission),
            ).pack(side=tk.LEFT, padx=(0, 8))

        buttons = tk.Frame(container, bg=ui.surface)
        buttons.pack(fill=tk.X, pady=(14, 0))

        def on_close():
            self.macos_permission_window = None
            window.destroy()

        def on_recheck():
            feedback.config(text=_("Verificando…"), fg=ui.text_muted)
            self.task_runner.start(
                lambda: self._recheck_macos_permissions(status, window, feedback),
                name="macos-permissions-recheck",
            )

        ui_widgets.button(buttons, text=_("Fechar"), width=10, command=on_close).pack(side=tk.RIGHT, padx=(6, 0))
        ui_widgets.button(
            buttons, text=_("Verificar novamente"), command=on_recheck, variant="accent",
        ).pack(side=tk.RIGHT)

        window.protocol("WM_DELETE_WINDOW", on_close)
        center_on_screen(window)
        window.lift()
        window.focus_force()

    def _open_macos_settings_pane(self, permission):
        """Deep-link System Settings to one pane. GUI thread; `open` returns at once."""
        label = _(macos_permissions.PERMISSION_LABELS.get(permission, permission))
        if macos_permissions.open_settings_pane(permission):
            self.logger.info(f"Painel de permissão aberto: {label}")
            return
        self.logger.error(f"Falha ao abrir o painel de permissão: {label}")
        self.notify_error(
            _("Não foi possível abrir o painel {label}. Abra Ajustes do Sistema › "
              "Privacidade e Segurança manualmente.").format(label=label),
            key="macos-permissions-pane",
        )

    def _recheck_macos_permissions(self, previous, window, feedback):
        """Worker: re-probe after the user visited System Settings and report honestly.

        A grant never reactivates this process — the frameworks read TCC at
        startup — so the only truthful success message asks for a restart.
        """
        # Attribute reads on the cached theme only; safe off the GUI thread.
        ui = ui_theme.theme()
        try:
            current = macos_permissions.check_permissions()
        except Exception as e:
            self.logger.warning(f"Falha ao reverificar permissões do macOS: {e}")
            self._update_permission_feedback(window, feedback, _("Não foi possível verificar agora."), ui.warning)
            return

        self._macos_permission_status = current
        state, message = macos_permissions.recheck_outcome(previous, current)
        self.logger.info(
            f"Reverificação de permissões do macOS ({state}): "
            f"{macos_permissions.describe_status(current)}"
        )
        self.refresh_tray_menu()
        color = ui.success if state == macos_permissions.RECHECK_RESOLVED else ui.warning
        self._update_permission_feedback(window, feedback, message, color)

    def _update_permission_feedback(self, window, feedback, message, color):
        """Write the re-check result back onto the window from a worker thread."""

        def apply(_root):
            # The user can close the window while the re-check is in flight;
            # a destroyed widget raises from Tcl rather than answering False.
            try:
                if not window.winfo_exists():
                    return
                feedback.config(text=message, fg=color)
            except tk.TclError:
                pass

        try:
            self.gui.submit(apply)
        except Exception as e:
            self.logger.warning(f"Falha ao atualizar a janela de permissões: {e}")

    def toggle_autostart(self, icon, item):
        """Tray action: install/remove the per-user autostart entry.

        The Windows backend shells out to PowerShell, so the work goes to a
        worker thread; doing it inline would freeze the tray menu for as long as
        PowerShell takes to start.
        """
        self.task_runner.start(self._apply_autostart_toggle, name="autostart-toggle")

    def _apply_autostart_toggle(self):
        # A toggle now outlives the click, so clicks arriving mid-flight are
        # refused instead of racing an install against a remove — but say so:
        # the startup resolve can hold the lock for a PowerShell round-trip,
        # and a silently dropped click reads as a broken toggle.
        if not self._autostart_lock.acquire(blocking=False):
            self.notify_status(
                _("Alteração de início automático em andamento; aguarde."),
                key="autostart-busy",
            )
            return
        try:
            if self._autostart_state == AUTOSTART_MANAGED:
                open_startup_settings()
                return
            # Direction follows the cached state, so a stale entry (shown
            # unchecked) is overwritten by the install branch rather than removed.
            if self._autostart_state == AUTOSTART_CURRENT:
                remove_autostart(APP_NAME)
                self._autostart_state = AUTOSTART_ABSENT
                self.notify_status(_("Início automático desativado."), key="autostart")
            else:
                path = install_autostart(APP_NAME)
                self._autostart_state = AUTOSTART_CURRENT
                self.logger.info(f"Inicialização automática instalada: {path}")
                self.notify_status(_("Início automático ativado."), key="autostart")
        except Exception as e:
            # Broad for the same reason as resolve_autostart_state: an escape
            # here dies invisibly on the worker thread and eats the click.
            self.logger.error(f"Falha ao alterar inicialização automática: {e}")
            self.notify_error(
                _("Falha ao alterar início automático: {e}").format(e=e),
                key="autostart-error",
            )
        finally:
            self._autostart_lock.release()
            self.refresh_tray_menu()

    def refresh_tray_menu(self):
        """Re-render the tray menu so check states reflect a background change.

        Callers are worker threads (autostart/permission resolves). On macOS
        pystray's ``update_menu`` mutates AppKit (NSMenu/``setMenu_``) on the
        calling thread, and AppKit may only be touched from the main thread —
        so the update is routed through the GuiThread pump, which runs it on the
        main thread from inside the Tk loop. That is AppKit-from-Tk-pump, the
        opposite of the forbidden Tcl-from-Cocoa direction (issue #53), so it is
        safe. ``submit`` queues rather than running inline even if the caller is
        already the GUI thread, so this never deadlocks. Windows/Linux post an
        internal message and call it directly, unchanged.
        """
        if not self.icon:
            return
        if platform_support.tray_menu_updates_on_gui_thread():
            self.gui.submit(self._update_tray_menu)
            return
        self._update_tray_menu()

    def _update_tray_menu(self, _root=None):
        """Rebuild the tray menu. ``_root`` is the arg the GuiThread pump passes."""
        try:
            self.icon.update_menu()
        except Exception as e:
            self.logger.warning(f"Falha ao atualizar o menu da bandeja: {e}")

    def tray_open_data_folder(self, icon, item):
        """Tray action: open the user data folder."""
        self.open_data_folder()

    def quit_app(self, icon, item):
        """Quit the application."""
        # A macOS tray callback is a Cocoa frame: queue all Tk work, then stop
        # the loop from a worker so Windows never joins its own GUI thread.
        if self.manager_window is not None:
            self.gui.submit(lambda _root: self._quit_with_manager(icon))
            return
        self._finish_quit(icon)

    def _quit_with_manager(self, icon):
        window = self.manager_window
        if window is not None:
            if not self._resolve_manager_drafts(window):
                return
            if not self._persist_settings({"manager_view": self._capture_manager_view(window)}):
                ui_widgets.alert(window, _("Não foi possível salvar a visualização"),
                                 _("A janela continua aberta. Verifique os logs e tente de novo."), tone="danger")
                return
            self._release_manager_ui_refs()
            window.destroy()
            gc.collect()
        self.task_runner.start(self._finish_quit, icon, name="quit-app")

    def _finish_quit(self, icon):
        self.enabled = False
        process = getattr(self, "_manager_process", None)
        if process is not None:
            process.close()
        if self.listener:
            self.listener.stop()
        self.gui.stop()
        icon.stop()
    
    def run_keyboard_listener(self):
        """Run the keyboard listener in a separate thread."""
        options = {}
        if platform_support.IS_WINDOWS:
            # Our own erase/paste keys must not re-enter the trigger buffer or
            # the hotkey router: a late Ctrl+V landing mid-word would break the
            # user's next trigger.
            options["win32_event_filter"] = win_input.listener_event_filter
        try:
            # Establish click observation before accepting the first trigger.
            self.mouse_monitor.start()
            self.listener = keyboard.Listener(
                on_press=self.on_press,
                on_release=self.on_release,
                **options,
            )
            self.listener.start()
            self.listener.join()
        except Exception as error:
            self.capture_error = error
            self.enabled = False
            self.logger.error(f"Input capture failed: {error}")
            self.notify_error(
                _("Não foi possível iniciar a captura de entrada. Reinicie o "
                  "Sniptype. Detalhes: {e}").format(e=error),
                key="input-capture-error",
            )
            # The tray says it too; one built after this point reads the state.
            self.refresh_tray_state()
            # A manager built after this check reads capture_error right after
            # it creates the status variable, so it cannot miss the failure.
            if self._manager_status_var is not None:
                self.gui.submit(self._refresh_manager_status)
        finally:
            try:
                if self.listener is not None:
                    self.listener.stop()
            except Exception as error:
                self.logger.error(f"Keyboard input shutdown failed: {error}")
            try:
                self.mouse_monitor.stop()
            except Exception as error:
                self.logger.error(f"Mouse input shutdown failed: {error}")
    
    def run(self, *, show_manager=False):
        """Start the program with the system tray."""
        print("=" * 60)
        print("               SNIPTYPE - EXPANSOR DE SNIPPETS")
        print("=" * 60)
        
        if self.is_admin():
            print("\n✓ Executando como ADMINISTRADOR")
        else:
            print("\n⚠ Executando SEM privilégios de administrador")
            print("  Funcionará na maioria dos aplicativos comuns")
        
        static_count = sum(
            1
            for trigger, value in self.snippets.items()
            if not trigger.startswith("_") and not callable(value)
        )
        print(f"\n📝 Snippets carregados (estáticos, não-callable): {static_count}")
        
        dynamic_count = sum(1 for v in self.snippets.values() if callable(v))
        print(f"\n📊 Snippets dinâmicos: {dynamic_count}")
        print(f"   (xhj, xdolar, xcot, xfund, etc.)")
        
        print("\n✓ Ícone adicionado à bandeja do sistema")
        print("  Clique com botão direito no ícone para opções")
        print("=" * 60)
        
        # Bring the shared Tk root up before the tray, so the first dialog does
        # not pay interpreter startup while the user waits on an expansion.
        # Where Tk owns the main thread (macOS) this is also what creates the
        # process's NSApplication, which the tray then has to be handed.
        gui_started = False
        try:
            if platform_support.tk_runs_on_main_thread():
                gui_started = self.gui.adopt_main_thread()
            else:
                gui_started = self.gui.ensure_started()
        except Exception as e:
            self.logger.error(f"Falha ao iniciar a thread de GUI: {e}")

        if platform_support.tk_runs_on_main_thread() and not gui_started:
            # Windows can still run a tray with no dialogs, because pystray owns
            # its own loop there. Here the Tk loop *is* the loop the tray rides,
            # so without a root there is nothing left to start.
            self.logger.error("Sem root do Tk na thread principal: a bandeja não tem loop para rodar.")
            return

        if platform_support.tk_runs_on_main_thread() and not platform_support.hide_dock_icon():
            # Cosmetic only: the tray still works, the app just also sits in the
            # Dock. Logged rather than raised for exactly that reason.
            self.logger.warning("Não foi possível ocultar o ícone do Dock.")

        if gui_started:
            self.gui.submit(self._install_callback_hook)

        if gui_started and IS_WINDOWS:
            # Default icon for every window, including a dialog opened before
            # the manager (which otherwise sets it) ever has been.
            self.gui.submit(self._set_window_icon)

        if show_manager:
            # Reuse the tray action so the manager is always marshaled through
            # GuiThread.submit. In main-thread mode this queues work for the
            # Tk pump and never calls Tcl from the Cocoa startup frame.
            self.manage_snippets_gui(None, None)

        self.task_runner.start(self.run_keyboard_listener, name="keyboard-listener")

        menu = pystray.Menu(
            pystray.MenuItem(
                self.tray_toggle_label,
                self.toggle_enabled,
                checked=self.tray_toggle_checked,
                enabled=self.tray_toggle_enabled,
            ),
            pystray.MenuItem(
                lazy("⚠ Permissões do macOS"),
                self.tray_macos_permissions,
                visible=self.macos_permissions_pending,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lazy("Gerenciar snippets"), self.manage_snippets_gui, default=True),
            pystray.MenuItem(lazy("Editar último snippet"), self.edit_last_snippet,
                            enabled=lambda _item: self._manager_target(self.workflow_state.last_successful_item) is not None),
            pystray.MenuItem(lazy("Configurar atalhos"), self.configure_hotkeys),
            pystray.MenuItem(lazy("Atualizar biblioteca"), self.reload_snippets),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lazy("Backup agora"), self.tray_backup_now),
            pystray.MenuItem(lazy("Abrir pasta de dados"), self.tray_open_data_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self.autostart_menu_label,
                self.toggle_autostart,
                checked=self.autostart_is_enabled,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                APP_DISPLAY_NAME,
                lambda icon, item: None,
                enabled=False,
            ),
            pystray.MenuItem(lazy("Sair"), self.quit_app)
        )

        
        self.icon = pystray.Icon(
            "sniptype",
            self.load_tray_icon(),
            tray_support.tooltip(APP_DISPLAY_NAME, self._expansion_state()),
            menu,
            **platform_support.tray_icon_options()
        )

        if platform_support.tk_runs_on_main_thread():
            # Two frameworks, one main thread: the tray attaches to the
            # NSApplication the Tk root already created and rides the loop
            # mainloop() drives, instead of starting a second one it cannot
            # have. run_detached() returns immediately; mainloop() blocks here
            # exactly as icon.run() does on Windows.
            self.icon.run_detached(setup=self.on_tray_ready)
            self.gui.run_mainloop()
        else:
            self.icon.run(setup=self.on_tray_ready)


def set_dpi_awareness():
    """Make Tk render crisply on high-DPI displays (per-monitor v2, best effort)."""
    if not IS_WINDOWS:
        return

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_context = user32.SetProcessDpiAwarenessContext
        # The API takes a pointer-sized context and returns a four-byte Win32 BOOL.
        # ctypes' default int conversion can truncate this pseudo-handle on 64-bit Windows.
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = ctypes.c_int32
        ctypes.set_last_error(0)
        if set_context(ctypes.c_void_p(-4)):
            return
        if ctypes.get_last_error() == 5:  # ERROR_ACCESS_DENIED: a manifest/process already chose.
            return
    except (AttributeError, OSError):
        pass

    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        set_awareness = shcore.SetProcessDpiAwareness
        set_awareness.argtypes = [ctypes.c_int]
        set_awareness.restype = ctypes.c_int32  # HRESULT is a signed 32-bit value.
        result = set_awareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        if result == 0 or result & 0xFFFFFFFF == 0x80070005:  # S_OK or E_ACCESSDENIED
            return
    except (AttributeError, OSError):
        pass

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_legacy = user32.SetProcessDPIAware
        set_legacy.argtypes = []
        set_legacy.restype = ctypes.c_int32
        if set_legacy():
            return
    except (AttributeError, OSError):
        pass


def main():
    """Main entry point."""
    # Windows keeps its named mutex; other platforms use a PID lockfile.
    lock_path = None
    if IS_WINDOWS:
        acquired = acquire_single_instance_mutex()
    else:
        lock_path = os.path.join(ensure_data_dir(), "sniptype.lock")
        acquired = acquire_lockfile(lock_path)
    if not acquired:
        # The running instance owns the app; this one only needs the user's
        # language for the one message it shows.
        i18n.set_language(load_settings(get_settings_path()).get("language"))
        show_already_running_message()
        return

    set_dpi_awareness()
    try:
        expander = Sniptype()
        expander.run(show_manager="--show-manager" in sys.argv[1:])
    finally:
        if lock_path is not None:
            release_lockfile(lock_path)


if __name__ == "__main__":
    main()
