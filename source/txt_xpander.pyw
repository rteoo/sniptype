"""
Txt Xpander - Windows system tray snippet expander.
Version: 3.3.0
Channel: beta

IMPORTANT: This program captures keyboard input only to expand text
snippets (shortcuts), similar to TextExpander. It does not store,
transmit, or log keystrokes. All processing is local.

Libraries used:
- pynput (open source, LGPL)
- pystray (open source, LGPL)
- pillow (open source, PIL License)
- yfinance (open source, Apache 2.0)
"""

import time
import threading
import os
import sys
import shutil
import ctypes
import webbrowser

import platform_support

# Must run before ``import pystray``: it reads PYSTRAY_BACKEND at import time.
platform_support.pin_tray_backend()

from pynput import keyboard
from pynput.keyboard import Controller, Key
import pystray
from PIL import Image, ImageDraw, ImageFont

from bcb_consultor import BCBConsultor
from yf_stocks import B3FundamentosConsultor
from snippet_utils import (
    build_saveable_snippets,
    calculate_max_trigger_length_with_mappings,
    find_shadowed_statics,
    get_default_snippets as get_static_default_snippets,
    get_dynamic_prefixes,
    load_json_file,
    merge_snippets,
    validate_static_snippets,
    write_json_atomic,
    check_dynamic_pattern as resolve_dynamic_pattern,
)
from trigger_index import compile_trigger_index, find_direct_trigger, find_dynamic_trigger
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
    NOTIFICATION_HISTORY_LIMIT,
)
from backup_support import (
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
from settings_support import load_settings
from validation_support import validate_trigger
import macos_permissions
import ui_theme
from platform_support import (
    APP_NAME,
    AUTOSTART_ABSENT,
    AUTOSTART_CURRENT,
    AUTOSTART_STALE,
    IS_MAC,
    IS_WINDOWS,
    acquire_lockfile,
    autostart_target_exists,
    classify_autostart,
    install_autostart,
    insertion_timings,
    invalid_timing_overrides,
    read_autostart_command,
    release_lockfile,
    remove_autostart,
)
from dynamic_registry import (
    build_dynamic_snippets,
    composed_mapping_triggers,
    effective_trigger,
    load_registry,
    reference_entries_by_category,
    validate_rename,
)
from sync_export import STATE_FILENAME as SYNC_STATE_FILENAME, export_bundle
from whatsapp_support import normalize_phone_number
from whatsapp_runtime_support import execute_whatsapp_action
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
    find_variable_names,
    resolve_form_variables,
    resolve_inline,
)
from gui_support import (
    center_dialog,
    center_on_screen,
    filter_static_snippets,
    focus_modal_input,
    iter_filtered_mapping_items,
    snippet_row_values,
)
from gui_thread import GuiThread

# GUI for managing snippets
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog, font as tkfont


def _read_release_metadata():
    """Read the app version and release channel from this module's docstring.

    Derived rather than duplicated: the docstring and installer/txt_xpander.iss are
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


def format_app_version(version, channel="stable"):
    """Return the user-visible app name, version and non-stable channel."""
    if version:
        channel_suffix = f" {channel}" if channel and channel != "stable" else ""
        return f"{APP_NAME} v{version}{channel_suffix}"
    return f"{APP_NAME} — versão desconhecida"


APP_DISPLAY_NAME = format_app_version(APP_VERSION, RELEASE_CHANNEL)


APP_MUTEX_NAME = r"Local\TxtXpanderSingleton"
APP_MUTEX_HANDLE = None
ERROR_ALREADY_EXISTS = 183
MB_ICONINFORMATION = 0x40

# Extra headroom on the typed-text buffer beyond the longest known trigger, so a
# newly added long mapping item is never truncated out before its index rebuild.
TRIGGER_BUFFER_MARGIN = 8

# Characters that end a word for opt-in terminator-gated expansion.
TERMINATOR_CHARS = frozenset(" \t\n\r.,;:!?)]}\"'")


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
    """Keep only one Txt Xpander process running at a time."""
    global APP_MUTEX_HANDLE

    mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
    if not mutex_handle:
        return True

    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        ctypes.windll.kernel32.CloseHandle(mutex_handle)
        return False

    APP_MUTEX_HANDLE = mutex_handle
    return True


def show_already_running_message():
    message = "Txt Xpander já está em execução."
    if IS_WINDOWS:
        ctypes.windll.user32.MessageBoxW(0, message, "Txt Xpander", MB_ICONINFORMATION)
    else:
        print(message)


class TextExpander:
    def __init__(self, snippets_file: str = 'snippets.json'):
        self.keyboard_controller = Controller()
        self.typed_text = ""
        self.expansion_failed = False
        self.last_expansion_time = 0
        self.enabled = True
        self.icon = None
        self.listener = None
        self.logger = AppLogger()
        self.task_runner = BackgroundTaskRunner()
        # One hidden Tk root for the whole process; every window is a Toplevel
        # of it, marshaled onto its thread. Started in run().
        self.gui = GuiThread(logger=self.logger)
        self.manager_window = None
        self.macos_permission_window = None
        # Cached macOS TCC probe. Like the autostart cache, the tray menu only
        # ever reads this: pystray re-evaluates `visible=` on every render and
        # the probe is a TCC round-trip. Empty (all unknown) off macOS.
        self._macos_permission_status = {}
        # List-rebuild callbacks registered by the manager tabs, replayed after
        # a restore/import swaps the whole library out from under them.
        self._manager_refreshers = []
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

        # User data lives in a stable per-user dir (~/.txt_xpander), never inside
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
        self.settings = load_settings(self.settings_file)
        # Opt-in: expand only after a terminator (space/punctuation). Default off
        # to preserve the existing expand-on-last-character muscle memory.
        self.terminator_mode = bool(self.settings.get("terminator_mode", False))
        # Clipboard/erase delays: per-OS defaults, overridable per key from
        # settings.json. Resolved once — they are read on the listener thread.
        timings = insertion_timings(self.settings)
        self.erase_key_delay = timings["erase_key_delay"]
        self.text_inserter = TextInserter(
            self.keyboard_controller,
            logger=self.logger,
            settle_delay=timings["clipboard_settle_delay"],
            restore_delay=timings["paste_restore_delay"],
            notify=self.notify_error,
        )
        configure_logging(self.logs_dir)
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
            f"Dados movidos para {self.data_dir}. O arquivo antigo foi mantido como cópia.",
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

        if os.path.exists(self.snippets_file):
            try:
                static_snippets = validate_static_snippets(load_json_file(self.snippets_file))
                if static_snippets is None:
                    self.logger.warning("⚠ Formato inesperado em snippets.json; tentando restaurar.")
                    static_snippets = self.recover_snippets_file("formato inválido")
                else:
                    self.logger.info(f"✓ Snippets carregados do arquivo: {len(static_snippets)} snippets")
            except Exception as e:
                self.logger.error(f"⚠ Erro ao carregar snippets: {e}")
                static_snippets = self.recover_snippets_file(str(e))
        else:
            self.logger.info("ℹ Primeira execução: criando arquivo de snippets padrão")
            static_snippets = self.get_default_snippets()
            self.save_snippets(static_snippets)

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
                f"Trigger(s) em conflito com snippets dinâmicos: {names}. O dinâmico é que expande.",
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
        try:
            quarantined = quarantine_corrupt_file(self.snippets_file)
            self.logger.error(f"⚠ snippets.json corrompido ({reason}); movido para {quarantined}")
        except OSError as e:
            self.logger.error(f"⚠ Não foi possível isolar snippets.json corrompido: {e}")

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
                self.notify_error(
                    f"snippets.json estava corrompido; restaurado do backup {backup_name}.",
                    key="snippets-restored",
                )
                return data

        self.logger.warning("⚠ Sem backup válido; usando snippets de exemplo.")
        self.notify_error(
            "snippets.json estava corrompido e não havia backup; usando snippets de exemplo.",
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

    def save_snippets(self, snippets: dict) -> bool:
        """Save static snippets to disk, backing up the previous copy first.

        Returns True on success, False on failure. A rotating backup of the
        pre-write file is taken before the atomic replace so no save can lose an
        earlier state.
        """
        saveable = build_saveable_snippets(snippets, self.shadowed_static_snippets)
        try:
            # Only back up a valid prior file, so a corrupt on-disk copy can never
            # become the newest backup and defeat recovery.
            if self.snippets_file_is_valid():
                create_backup(self.snippets_file, self.backups_dir)
                prune_backups(self.backups_dir)
        except OSError as e:
            self.logger.warning(f"Falha ao criar backup antes de salvar: {e}")

        try:
            write_json_atomic(self.snippets_file, saveable)
            self.logger.info("✓ snippets.json salvo com sucesso.")
        except Exception as e:
            self.logger.error(f"Erro ao salvar snippets: {e}")
            return False

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
            return
        try:
            os.makedirs(mirror_dir, exist_ok=True)
            shutil.copyfile(self.snippets_file, os.path.join(mirror_dir, "snippets.json"))
        except Exception as e:
            # Broad guard: a bad mirror_dir value (e.g. hand-edited to a non-path)
            # must not disturb the already-successful save.
            self.logger.warning(f"Falha ao espelhar snippets para {mirror_dir}: {e}")

    def export_sync_bundle(self):
        """Write the compiled mobile bundle when ``sync_export_dir`` is configured.

        Both inputs are re-read from disk rather than taken from ``self``. That is
        not symmetry: ``self.snippets`` holds bound callables and no registry
        metadata, it does not exist yet when ``load_snippets`` saves on first run,
        and it is stale between a restore/import write and the reload that follows.
        ``self.dynamic_registry`` is likewise reassigned only *after* the registry
        writers persist, so reading it here would compile the pre-toggle state.

        Best-effort: any failure logs and returns, never turning a persisted save
        into a reported failure.
        """
        export_dir = self.settings.get("sync_export_dir")
        if not export_dir:
            return

        try:
            static_snippets = validate_static_snippets(load_json_file(self.snippets_file))
        except Exception as e:
            self.logger.warning(f"Bundle de sincronização ignorado: falha ao ler snippets.json ({e}).")
            return
        if static_snippets is None:
            self.logger.warning("Bundle de sincronização ignorado: snippets.json com formato inválido.")
            return

        try:
            registry = load_registry(
                self.resolve_resource_path("dynamic_snippets.json"),
                self.dynamic_registry_file,
                logger=self.logger,
            )
            export_bundle(
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

    # =====================================================================
    # BACKUP / RESTORE / EXPORT / IMPORT
    # =====================================================================

    def reload_snippets_from_disk(self):
        """Reload the static library from disk and rebuild runtime indexes."""
        self.snippets = self.load_snippets()
        self.refresh_runtime_indexes()

    def _backup_current_library(self):
        """Force a backup of the current file before a destructive operation."""
        try:
            if self.snippets_file_is_valid() and create_backup(
                self.snippets_file, self.backups_dir, force=True
            ):
                prune_backups(self.backups_dir)
        except OSError as e:
            self.logger.warning(f"Falha ao criar backup de segurança: {e}")

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

    def restore_backup(self, backup_path):
        """Replace the live library with a backup (current file backed up first).

        Returns (ok, error_message).
        """
        try:
            data = validate_static_snippets(load_json_file(backup_path))
        except Exception as e:
            return False, f"Backup inválido: {e}"
        if data is None:
            return False, "Backup inválido: formato inesperado."

        self._backup_current_library()
        try:
            shutil.copyfile(backup_path, self.snippets_file)
        except OSError as e:
            return False, f"Falha ao restaurar: {e}"

        self.mirror_snippets_file()
        self.export_sync_bundle()
        self.reload_snippets_from_disk()
        return True, None

    def export_library(self, dest_path):
        """Copy the current library to dest_path. Returns (ok, error_message)."""
        try:
            shutil.copyfile(self.snippets_file, dest_path)
            return True, None
        except OSError as e:
            return False, str(e)

    def import_library(self, src_path, mode="replace"):
        """Import a library file (mode 'replace' or 'merge').

        Validates the source is a JSON object, backs up the current library,
        applies the change, mirrors and reloads. Returns (ok, error_message).
        """
        try:
            data = validate_static_snippets(load_json_file(src_path))
        except Exception as e:
            return False, f"Arquivo inválido: {e}"
        if data is None:
            return False, "Arquivo inválido: o JSON precisa ser um objeto."

        self._backup_current_library()
        if mode == "merge":
            merged = {**build_saveable_snippets(self.snippets, self.shadowed_static_snippets), **data}
        else:
            merged = data

        try:
            write_json_atomic(self.snippets_file, merged)
        except Exception as e:
            return False, f"Falha ao importar: {e}"

        self.mirror_snippets_file()
        self.export_sync_bundle()
        self.reload_snippets_from_disk()
        return True, None

    def open_data_folder(self):
        """Open the user data directory in the OS file manager."""
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            # ceiling: Windows-only shell open; a platform adapter replaces this in
            # the cross-platform phase (audit §6). Broad guard so a click never
            # raises out of the GUI/tray callback on other OSes.
            os.startfile(self.data_dir)  # noqa: WPS421
        except Exception as e:
            self.logger.error(f"Falha ao abrir a pasta de dados: {e}")

    # =====================================================================
    # DATE / TEXT / INPUT UTILITIES
    # =====================================================================

    def data_extenso(self):
        """Return the date written out in Portuguese."""
        dias = ['segunda-feira', 'terça-feira', 'quarta-feira', 
                'quinta-feira', 'sexta-feira', 'sábado', 'domingo']
        meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
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
                "Outro diálogo já está aberto; conclua-o primeiro.",
                key="dialog-busy",
            )
            return on_busy
        try:
            restore_state = {}

            def build_and_restore_focus(root):
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
            dialog.title(prompt_title)
            dialog.resizable(False, False)
            dialog.configure(bg=ui.surface)
            self._set_window_icon(dialog)

            container = tk.Frame(dialog, bg=ui.surface, padx=18, pady=18)
            container.pack(fill=tk.BOTH, expand=True)

            tk.Label(
                container,
                text="Digite o ticker:",
                font=ui.font(10, "bold"),
                bg=ui.surface,
                fg=ui.text,
            ).pack(anchor="w")
            tk.Label(
                container,
                text="Ex: PETR4, AAPL, MSFT",
                font=ui.font(9),
                bg=ui.surface,
                fg=ui.text_muted,
            ).pack(anchor="w", pady=(2, 8))

            entry = tk.Entry(container, font=ui.font(10), width=28, **ui.entry_colors())
            entry.pack(fill=tk.X, pady=(0, 12))

            buttons = tk.Frame(container, bg=ui.surface)
            buttons.pack(fill=tk.X)

            def on_cancel(_event=None):
                dialog.destroy()  # result stays None

            def on_ok(_event=None):
                ticker = entry.get().strip().upper()
                result[0] = ticker or None
                dialog.destroy()

            tk.Button(buttons, text="Cancelar", width=ui.button_width(12), command=on_cancel).pack(side=tk.RIGHT, padx=(6, 0))
            tk.Button(buttons, text="OK", width=ui.button_width(12), command=on_ok).pack(side=tk.RIGHT)

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
                f"Erro ao abrir diálogo de ticker: {e}",
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
            dialog.title("Abrir WhatsApp")
            dialog.resizable(False, False)
            dialog.configure(bg=ui.surface)
            self._set_window_icon(dialog)

            container = tk.Frame(dialog, bg=ui.surface, padx=18, pady=18)
            container.pack(fill=tk.BOTH, expand=True)
            container.grid_columnconfigure(0, weight=1)

            tk.Label(
                container,
                text="Abrir conversa no WhatsApp",
                font=ui.font(11, "bold"),
                bg=ui.surface,
                fg=ui.text,
            ).grid(row=0, column=0, sticky="w")

            tk.Label(
                container,
                text="Informe o telefone com DDD ou código do país. Se faltar o país, será usado +55.",
                font=ui.font(9),
                bg=ui.surface,
                fg=ui.text_muted,
                wraplength=380,
                justify=tk.LEFT,
            ).grid(row=1, column=0, sticky="w", pady=(6, 12))

            tk.Label(container, text="Telefone", font=ui.font(9), bg=ui.surface, fg=ui.text_native).grid(row=2, column=0, sticky="w")
            entry_phone = tk.Entry(container, font=ui.font(10), width=42, **ui.entry_colors())
            entry_phone.grid(row=3, column=0, sticky="ew", pady=(4, 10))
            if initial_phone:
                entry_phone.insert(0, initial_phone)

            tk.Label(container, text="Mensagem", font=ui.font(9), bg=ui.surface, fg=ui.text_native).grid(row=4, column=0, sticky="w")
            text_message = tk.Text(container, font=ui.font(10), width=42, height=5, **ui.text_colors())
            text_message.grid(row=5, column=0, sticky="ew", pady=(4, 12))
            if initial_message:
                text_message.insert("1.0", initial_message)

            buttons = tk.Frame(container, bg=ui.surface)
            buttons.grid(row=6, column=0, sticky="e")

            def cancel_dialog(_event=None):
                dialog.destroy()  # result stays empty

            def submit_dialog(event=None):
                phone_text = entry_phone.get().strip()
                message_text = text_message.get("1.0", tk.END).rstrip("\n")
                normalized_phone = normalize_phone_number(phone_text)

                if not normalized_phone:
                    messagebox.showwarning(
                        "Telefone inválido",
                        "Informe um telefone com DDD ou código do país em um formato válido.",
                        parent=dialog,
                    )
                    entry_phone.focus_set()
                    return

                result["phone"] = normalized_phone
                result["message"] = message_text
                dialog.destroy()

            btn_cancel = tk.Button(buttons, text="Cancelar", width=ui.button_width(12), command=cancel_dialog)
            btn_open = tk.Button(buttons, text="Abrir WhatsApp", width=ui.button_width(14), command=submit_dialog)
            btn_cancel.pack(side=tk.LEFT, padx=(0, 6))
            btn_open.pack(side=tk.LEFT)

            entry_phone.bind("<Return>", submit_dialog)
            dialog.bind("<Escape>", cancel_dialog)
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
                f"Erro ao abrir diálogo do WhatsApp: {e}",
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
        snippets, slow_triggers = build_dynamic_snippets(
            self.dynamic_registry, self, logger=self.logger
        )
        self.slow_snippets = slow_triggers
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

    def get_all_dynamic_prefixes(self):
        """Return all dynamic mapping prefixes (built-in + custom)."""
        return get_dynamic_prefixes(self.snippets)

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
            snippet, _ = self.check_dynamic_pattern(trigger)
        
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
                self.text_inserter.insert_text(snippet)

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
                        f"Falha ao expandir snippet {trigger}: {e}",
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
                func, _ = self.check_dynamic_pattern(trigger)
            if func is None:
                return False

            if not callable(func):
                # Non-callable snippet routed here because it has form-fill variables.
                raw = func
                plain = extract_plain_text(raw)
                prefixes = self.trigger_index["dynamic_prefixes"]
                plain = resolve_inline(
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
                if form_names:
                    form_data = self._show_form_dialog(form_names)
                    if form_data is None:
                        return False  # user cancelled — nothing inserted
                result = resolve_form_variables(plain, form_data)
                if is_rich_text_payload(raw):
                    result = rebuild_rich_text(raw, result)
                time.sleep(0.05)
                self.text_inserter.insert_text(result)
                return True

            result = func()
            if not result:
                return False
            self.notify_snippet_failure(trigger, result)
            time.sleep(0.05)
            self.text_inserter.insert_text(result)
            if trigger == "xlwapp":
                Clipboard.set_content(result)
            return True
        except Exception as e:
            self.logger.error(f"Erro ao executar snippet lento {trigger}: {e}")
            self.notify_error(
                f"Falha ao executar snippet {trigger}: {e}",
                key=f"slow-snippet-error:{trigger}",
                cooldown_seconds=5,
            )
            return False
    
    def _show_form_dialog(self, field_names):
        """
        Show a modal dialog for form-fill variables.
        Called from a worker thread; the dialog is built on the shared GUI
        thread and this call blocks until it closes.
        Returns {field_name: value} or None if the user cancels.
        """
        def build(root):
            ui = ui_theme.bind(root)
            result = [None]
            entries = {}

            dialog = tk.Toplevel(root)
            dialog.withdraw()
            dialog.title("Preencher campos")
            dialog.resizable(False, False)
            dialog.configure(bg=ui.surface)
            self._set_window_icon(dialog)

            tk.Label(
                dialog,
                text="Preencha os campos do snippet:",
                font=ui.font(9, "bold"),
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
                    font=ui.font(9),
                    bg=ui.surface,
                    fg=ui.text_strong,
                ).grid(row=i * 2, column=0, sticky="w", pady=(6, 0))
                entry = tk.Entry(
                    frame,
                    font=ui.font(10),
                    width=42,
                    relief=tk.FLAT,
                    highlightthickness=1,
                    highlightbackground=ui.border,
                    **ui.entry_colors(),
                )
                entry.grid(row=i * 2 + 1, column=0, sticky="ew", pady=(2, 0))
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

            tk.Button(
                btn_frame,
                text="Cancelar",
                font=ui.font(9),
                width=10,
                command=on_cancel,
                relief=tk.FLAT,
                cursor="hand2",
                **ui.button_colors(),
            ).pack(side=tk.RIGHT, padx=(4, 0))
            tk.Button(
                btn_frame,
                text="OK",
                font=ui.font(9),
                width=10,
                command=on_ok,
                relief=tk.FLAT,
                cursor="hand2",
                **ui.button_colors(accent=True),
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
            return self._run_modal_dialog(build, None, f"campos ({', '.join(field_names)})")
        except Exception as e:
            self.logger.error(f"Erro no diálogo de campos: {e}")
            self.notify_error(
                f"Erro ao abrir diálogo de campos: {e}",
                key="form-dialog-error",
                cooldown_seconds=5,
            )
            return None

    def rebuild_trigger_index(self):
        """Rebuild compiled trigger metadata after snippet changes."""
        self.trigger_index = compile_trigger_index(self.snippets, self.slow_snippets)

    def _validate_trigger_warnings(self, trigger):
        """Return save-time warnings for a proposed static trigger."""
        static_triggers = {
            key for key, value in self.snippets.items()
            if not key.startswith("_") and not callable(value)
        }
        dynamic_names = {key for key, value in self.snippets.items() if callable(value)}
        prefixes = get_dynamic_prefixes(self.snippets)
        for prefix, mapping_key in prefixes.items():
            mapping = self.snippets.get(mapping_key, {})
            if isinstance(mapping, dict):
                for name in mapping:
                    if name != "__prefix__":
                        static_triggers.add(prefix + name)
        existing = static_triggers - {trigger}
        return validate_trigger(trigger, existing, dynamic_names)

    def refresh_runtime_indexes(self):
        """Refresh max trigger length and compiled trigger metadata.

        The buffer is always sized to include composed dynamic mapping triggers
        (prefix + item name) plus a small safety margin, so a long mapping item
        can never be truncated out of the typed-text buffer and fail to match.
        """
        self.max_trigger_length = calculate_max_trigger_length_with_mappings(self.snippets) + TRIGGER_BUFFER_MARGIN
        self.rebuild_trigger_index()

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

    def _delete_static_snippet(self, trigger, confirm):
        """Delete a static snippet by trigger, guarding shadowed dynamics.

        ``confirm`` is called (returning a bool) only once the delete is
        eligible. Returns one of ``"missing"``, ``"dynamic"`` (a dynamic trigger
        owns the name — refused so the preserved static is not lost, and the
        caller directs the user to the Snippets Dinâmicos tab), ``"cancelled"``,
        ``"error"`` (save failed, in-memory state rolled back) or ``"ok"``.
        """
        if trigger not in self.snippets:
            return "missing"
        if callable(self.snippets[trigger]):
            return "dynamic"
        if not confirm():
            return "cancelled"
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

    def notify(self, message: str, title: str = "Text Expander", key: str = None, cooldown_seconds: float = 0, kind: str = "info"):
        """Send a tray notification when the icon is available, with optional cooldown.

        The cooldown check and the history append are done under
        ``_notification_lock`` so concurrent callers (listener + workers) cannot
        lose an update or both pass the same cooldown window. The disk write and
        the tray call run outside the lock, against a snapshot taken inside it,
        so the lock is never held across I/O.
        """
        if not self.icon:
            return False

        text = truncate_notification_text(message)
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "title": title,
            "message": text,
            "kind": kind,
        }

        with self._notification_lock:
            if key:
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

        try:
            self.icon.notify(text, title)
            return True
        except Exception as e:
            self.logger.warning(f"Falha ao exibir notificação: {e}")
            return False

    def notify_status(self, message: str, key: str = None):
        return self.notify(message, key=key, cooldown_seconds=2, kind="status")

    def _notify_or_queue(self, message: str, key: str, kind: str, cooldown_seconds: float):
        """Notify now, or queue for tray startup when the icon is not up yet."""
        if not self.icon:
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
        self.icon = icon
        icon.visible = True
        self.task_runner.start(self.notify_launch_ready, name="startup-notify")
        self.task_runner.start(self.resolve_autostart_state, name="autostart-state")
        # After the icon exists, so the denied state can be notified rather than
        # queued, and the window opens over an app that is already up.
        self.task_runner.start(self.resolve_macos_permissions, name="macos-permissions")

    def notify_launch_ready(self, icon=None):
        if icon is not None:
            self.icon = icon
        time.sleep(0.75)
        self.notify_status("Text Expander iniciado com sucesso.", key="startup")
        pending, self.pending_notifications = self.pending_notifications, []
        for message, key, kind, cooldown in pending:
            self.notify(message, key=key, cooldown_seconds=cooldown, kind=kind)

    # =====================================================================
    # KEYBOARD LISTENER
    # =====================================================================
    def on_press(self, key):
        """Detect a trigger on the listener thread; expand on a worker thread.

        The listener must stay fast and unkillable: it only appends the keystroke,
        matches a trigger, erases the typed trigger, and hands all real work
        (callables, network, dialogs, clipboard, paste) to a background thread.
        """
        try:
            if hasattr(key, 'char') and key.char:
                self._handle_char(key.char)
            elif key == Key.enter:
                # ceiling: terminator mode does not gate on Enter (re-typing it could
                # double-submit); Enter always just resets the buffer. Extend to Enter
                # if a safe re-emit strategy is needed.
                self.typed_text = ""
            elif key == Key.backspace and self.typed_text:
                self.typed_text = self.typed_text[:-1]
        except Exception as e:
            # A detection error must never stop the global keyboard listener.
            self.typed_text = ""
            self.logger.error(f"Erro no listener de teclado: {e}")
            self.notify_error(
                f"Erro ao detectar snippet: {e}",
                key="listener-error",
                cooldown_seconds=10,
            )

    def _handle_char(self, char):
        """Append a typed character and run trigger detection."""
        self.typed_text += char
        if len(self.typed_text) > self.max_trigger_length:
            self.typed_text = self.typed_text[-self.max_trigger_length:]

        if self.terminator_mode:
            if char in TERMINATOR_CHARS:
                self._detect_terminated(char)
            return

        self._detect_immediate()

    def _detect_immediate(self):
        """Immediate mode: expand as soon as a trigger suffix matches."""
        trigger = find_direct_trigger(self.typed_text, self.trigger_index)
        if trigger:
            self._dispatch_expansion(trigger, len(trigger))
            return
        potential_trigger, result = find_dynamic_trigger(self.snippets, self.typed_text, self.trigger_index)
        if result is not None:
            self._dispatch_expansion(potential_trigger, len(potential_trigger))

    def _detect_terminated(self, terminator_char):
        """Terminator mode: expand only when a word-ending char follows a trigger."""
        body = self.typed_text[:-1]  # drop the terminator just typed
        trigger = find_direct_trigger(body, self.trigger_index)
        if trigger:
            self._dispatch_expansion(trigger, len(trigger) + 1, append_text=terminator_char)
            return
        potential_trigger, result = find_dynamic_trigger(self.snippets, body, self.trigger_index)
        if result is not None:
            self._dispatch_expansion(potential_trigger, len(potential_trigger) + 1, append_text=terminator_char)

    def _dispatch_expansion(self, trigger, erase_length, append_text=""):
        """Erase the typed trigger and run the expansion on a worker thread."""
        if self._secure_input_blocks_expansion():
            self.typed_text = ""
            return
        self._erase_chars(erase_length)
        self.typed_text = ""
        self.task_runner.start(self._run_expansion, trigger, append_text, name="expand")

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
        # Notify off the listener thread: notify() writes the history JSON to
        # disk and calls into the tray, neither of which may run on the keyboard
        # listener (it must stay fast and unkillable). The 60s cooldown is
        # enforced inside notify() under its lock, so racing triggers that each
        # spawn a worker still produce exactly one notification.
        self.task_runner.start(
            self.notify,
            macos_permissions.SECURE_INPUT_MESSAGE,
            key="secure-input",
            cooldown_seconds=60,
            name="secure-input-notify",
        )
        return True

    def _erase_chars(self, count):
        """Backspace over ``count`` characters on the listener thread."""
        # ceiling: the per-char sleep keeps the erase reliable across apps; with
        # expansion now off-thread this only adds latency proportional to trigger
        # length, not to network work (audit 2.6).
        for _ in range(count):
            self.keyboard_controller.press(Key.backspace)
            self.keyboard_controller.release(Key.backspace)
            time.sleep(self.erase_key_delay)

    def _run_expansion(self, trigger, append_text=""):
        """Worker entry point: produce and insert the expansion for a trigger.

        The trigger text is already erased. This is wrapped so no expansion error
        (including a raising callable) can ever propagate to the listener thread.
        """
        if not self.enabled:
            return
        try:
            if trigger in self.trigger_index["slow_triggers"] or trigger in self.trigger_index["form_triggers"]:
                inserted = self.run_slow_snippet(trigger)
            else:
                inserted = self.expand_snippet(trigger)
            # Only re-emit the terminator when text was actually inserted, so a
            # cancelled form dialog or a failed paste does not leave a stray char.
            if append_text and inserted:
                self.keyboard_controller.type(append_text)
        except Exception as e:
            self.logger.error(f"Erro na expansão de {trigger}: {e}")
            self.notify_error(
                f"Falha ao expandir {trigger}: {e}",
                key=f"expand-error:{trigger}",
                cooldown_seconds=5,
            )

    # =====================================================================
    # SNIPPET MANAGEMENT GUI
    # =====================================================================

    def manage_snippets_gui(self, icon, item):
        """Open (or re-focus) the snippet manager window."""
        try:
            self.gui.submit(self._show_manager_window)
        except Exception as e:
            self.logger.error(f"Erro ao abrir gerenciador: {e}")
            self.notify_error(
                f"Erro ao abrir gerenciador: {e}",
                key="gui-open-error",
                cooldown_seconds=5,
            )

    def _show_manager_window(self, tk_root):
        """Build the manager window, or raise the one already open.

        GUI thread only. In-process window tracking replaces the old Win32
        FindWindowW lookup now that every window hangs off the shared root.
        """
        window = self.manager_window
        try:
            already_open = window is not None and bool(window.winfo_exists())
        except Exception:
            already_open = False

        if already_open:
            window.deiconify()
            window.lift()
            window.focus_force()
            return

        self.manager_window = None
        self._build_manager_window(tk_root)

    def _build_manager_window(self, tk_root):
        """Construct the management window as a Toplevel of the shared root."""
        try:
            # Re-resolved per window so reopening the manager picks up a system
            # appearance the user changed while it was closed.
            ui = ui_theme.bind(tk_root)
            root = tk.Toplevel(tk_root)
            root.title(f"{APP_DISPLAY_NAME} - Gerenciador de Snippets")
            geometry, min_width, min_height = ui.manager_window_size
            root.geometry(geometry)
            root.minsize(min_width, min_height)
            root.resizable(True, True)
            root.configure(bg=ui.surface)
            self._set_window_icon(root)
            self._configure_manager_styles(root)

            root.grid_columnconfigure(0, weight=1)
            root.grid_rowconfigure(1, weight=1)

            header = tk.Frame(root, bg=ui.surface, padx=12, pady=10)
            header.grid(row=0, column=0, sticky="ew")
            header.grid_columnconfigure(0, weight=1)

            tk.Label(
                header,
                text="Gerenciador de Snippets",
                font=ui.font(12, "bold"),
                bg=ui.surface,
                fg=ui.text,
            ).grid(row=0, column=0, sticky="w")
            tk.Label(
                header,
                text="Edite snippets, mapeamentos e consulte notificações recentes.",
                font=ui.font(9),
                bg=ui.surface,
                fg=ui.text_muted,
            ).grid(row=1, column=0, sticky="w", pady=(2, 0))

            bell_button = tk.Button(
                header,
                text="🔔",
                font=ui.emoji_font(12),
                width=3,
                relief=tk.FLAT,
                bd=0,
                cursor="hand2",
                **ui.button_colors(),
                command=lambda: self._open_notification_history(root),
            )
            bell_button.grid(row=0, column=1, rowspan=2, sticky="e")

            notebook = ttk.Notebook(root, style="Manager.TNotebook")
            notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

            tab_static = tk.Frame(notebook, bg=ui.surface)
            notebook.add(tab_static, text="Snippets Estáticos")

            tab_dynamic = tk.Frame(notebook, bg=ui.surface)
            notebook.add(tab_dynamic, text="Mapeamentos Dinâmicos")

            tab_builtin = tk.Frame(notebook, bg=ui.surface)
            notebook.add(tab_builtin, text="Snippets Dinâmicos")

            tab_backups = tk.Frame(notebook, bg=ui.surface)
            notebook.add(tab_backups, text="Backups")

            def tab_counter(tab, label):
                return lambda count: notebook.tab(tab, text=f"{label} ({count})")

            # Tabs are rebuilt with the window; drop the previous window's
            # callbacks so they can't fire against destroyed widgets.
            self._manager_refreshers = []
            self._create_static_snippets_tab(
                tab_static, root, set_count=tab_counter(tab_static, "Snippets Estáticos"))
            self._create_dynamic_mappings_tab(
                tab_dynamic, root, set_count=tab_counter(tab_dynamic, "Mapeamentos Dinâmicos"))
            self._create_dynamic_snippets_tab(tab_builtin, root)
            self._create_backups_tab(tab_backups, root)

            def on_close():
                self.manager_window = None
                root.destroy()

            root.protocol("WM_DELETE_WINDOW", on_close)
            self.manager_window = root
            root.lift()
            root.focus_force()

        except Exception as e:
            self.manager_window = None
            self.logger.error(f"Erro na GUI de gerenciamento: {e}")
            self.notify_error(
                f"Erro ao abrir gerenciador: {e}",
                key="gui-open-error",
                cooldown_seconds=5,
            )

    def _create_backups_tab(self, parent, root):
        """Backups tab: list backups and expose restore/export/import actions."""
        ui = ui_theme.theme()
        main = tk.Frame(parent, bg=ui.surface, padx=14, pady=14)
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        tk.Label(
            main,
            text="Backups da biblioteca",
            font=ui.font(11, "bold"),
            bg=ui.surface,
            fg=ui.text,
        ).grid(row=0, column=0, sticky="w")
        path_label = tk.Label(
            main,
            text=f"Pasta de dados: {self.data_dir}",
            font=ui.font(8),
            bg=ui.surface,
            fg=ui.text_muted,
        )
        path_label.grid(row=1, column=0, sticky="w", pady=(2, 10))

        columns = ("backup", "size", "count")
        tree = ttk.Treeview(main, columns=columns, show="headings", height=12)
        tree.heading("backup", text="Backup")
        tree.heading("size", text="Tamanho")
        tree.heading("count", text="Snippets")
        tree.column("backup", width=260, anchor="w")
        tree.column("size", width=90, anchor="e")
        tree.column("count", width=90, anchor="e")
        tree.grid(row=2, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(main, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=2, column=1, sticky="ns")

        # Maps tree row id -> backup path.
        row_paths = {}

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
                    count = len(data) if isinstance(data, dict) else "?"
                except Exception:
                    count = "inválido"
                row = tree.insert(
                    "",
                    tk.END,
                    values=(os.path.basename(path), human_size(size_bytes), count),
                )
                row_paths[row] = path

        def selected_backup():
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("Backups", "Selecione um backup na lista.", parent=root)
                return None
            return row_paths.get(selection[0])

        def on_restore():
            path = selected_backup()
            if not path:
                return
            name = os.path.basename(path)
            if not messagebox.askyesno(
                "Restaurar backup",
                f"Restaurar '{name}'? A biblioteca atual será salva como backup antes.",
                parent=root,
            ):
                return
            ok, error = self.restore_backup(path)
            if ok:
                self.notify_status(f"Backup restaurado: {name}", key="restore-backup")
                messagebox.showinfo("Backups", f"Backup '{name}' restaurado.", parent=root)
                refresh_backups()
                self._refresh_manager_lists()
            else:
                messagebox.showerror("Backups", f"Falha ao restaurar: {error}", parent=root)

        def on_export():
            dest = filedialog.asksaveasfilename(
                parent=root,
                title="Exportar biblioteca",
                defaultextension=".json",
                initialfile="snippets-export.json",
                filetypes=[("JSON", "*.json"), ("Todos", "*.*")],
            )
            if not dest:
                return
            ok, error = self.export_library(dest)
            if ok:
                messagebox.showinfo("Backups", "Biblioteca exportada com sucesso.", parent=root)
            else:
                messagebox.showerror("Backups", f"Falha ao exportar: {error}", parent=root)

        def on_import():
            src = filedialog.askopenfilename(
                parent=root,
                title="Importar biblioteca",
                filetypes=[("JSON", "*.json"), ("Todos", "*.*")],
            )
            if not src:
                return
            merge = messagebox.askyesno(
                "Importar biblioteca",
                "Mesclar com a biblioteca atual?\n\nSim = mesclar (entradas importadas têm prioridade)\n"
                "Não = substituir tudo.\n\nA biblioteca atual será salva como backup antes.",
                parent=root,
            )
            ok, error = self.import_library(src, mode="merge" if merge else "replace")
            if ok:
                self.notify_status("Biblioteca importada.", key="import-library")
                messagebox.showinfo("Backups", "Biblioteca importada com sucesso.", parent=root)
                refresh_backups()
                self._refresh_manager_lists()
            else:
                messagebox.showerror("Backups", f"Falha ao importar: {error}", parent=root)

        def on_backup_now():
            created = self.backup_now()
            if created:
                messagebox.showinfo("Backups", f"Backup criado: {os.path.basename(created)}", parent=root)
                refresh_backups()
            else:
                messagebox.showerror("Backups", "Falha ao criar backup. Verifique os logs.", parent=root)

        buttons = tk.Frame(main, bg=ui.surface)
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        tk.Button(buttons, text="Backup agora", width=ui.button_width(14), command=on_backup_now).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(buttons, text="Restaurar", width=ui.button_width(12), command=on_restore).pack(side=tk.LEFT, padx=6)
        tk.Button(buttons, text="Exportar…", width=ui.button_width(12), command=on_export).pack(side=tk.LEFT, padx=6)
        tk.Button(buttons, text="Importar…", width=ui.button_width(12), command=on_import).pack(side=tk.LEFT, padx=6)
        tk.Button(buttons, text="Abrir pasta", width=ui.button_width(12), command=self.open_data_folder).pack(side=tk.LEFT, padx=6)
        tk.Button(buttons, text="Atualizar", width=ui.button_width(10), command=refresh_backups).pack(side=tk.RIGHT)

        refresh_backups()

    def _set_window_icon(self, window):
        icon_path = self.resolve_resource_path("txt_xpander.ico")
        if not icon_path:
            return
        try:
            window.iconbitmap(icon_path)
        except Exception:
            pass

    def _configure_manager_styles(self, root):
        ui = ui_theme.theme()
        style = ttk.Style(root)
        # "vista" only exists on Windows; elsewhere this picked whatever theme
        # happened to be active and then painted Windows colors over it.
        theme_name = ui_theme.apply_ttk_theme(style)

        style.configure("Manager.TNotebook", background=ui.surface, borderwidth=0)
        style.configure("Manager.TNotebook.Tab", padding=(14, 8), font=ui.font(9))
        if theme_name != "aqua":
            # Aqua draws the tab strip natively and already follows the system
            # appearance; overriding its colors is what made the labels
            # unreadable in dark mode.
            style.map(
                "Manager.TNotebook.Tab",
                background=[("selected", ui.card), ("!selected", ui.surface_alt)],
                foreground=[("selected", ui.text), ("!selected", ui.tab_unselected_fg)],
            )
        style.configure(
            "Manager.Treeview",
            background=ui.card,
            fieldbackground=ui.card,
            foreground=ui.text,
            font=ui.font(10),
            borderwidth=0,
            rowheight=22,
        )
        style.configure("Manager.Treeview.Heading", font=ui.font(9), padding=(6, 4))
        style.layout("Manager.Treeview", style.layout("Treeview"))

    def _create_snippet_tree(self, shell, trigger_heading="Trigger",
                             trigger_width=104, preview_width=186):
        """Build the trigger/preview/markers Treeview used by the snippet lists.

        ``shell`` must be a grid container whose row 0 / column 0 expands.
        Widths are per-tab because the mappings tab splits the same row three
        ways and has far less to spare.
        """
        columns = ("trigger", "preview", "markers")
        tree = ttk.Treeview(
            shell,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Manager.Treeview",
        )
        tree.heading("trigger", text=trigger_heading, anchor="w")
        tree.heading("preview", text="Valor", anchor="w")
        tree.heading("markers", text="", anchor="center")
        # Widths are deliberately tight: the list shares the tab with the editor
        # pane, whose button row and format status get clipped if this grows.
        tree.column("trigger", width=trigger_width, minwidth=76, anchor="w", stretch=False)
        tree.column("preview", width=preview_width, minwidth=100, anchor="w", stretch=True)
        tree.column("markers", width=46, minwidth=46, anchor="center", stretch=False)
        tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(shell, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._bind_mousewheel(tree, tree)
        return tree

    def _register_manager_refresher(self, refresher):
        """Register a list-rebuild callback invoked after restore/import.

        Those operations rebind ``self.snippets`` wholesale, so every tab that
        renders it must repopulate or it silently shows the old library.
        """
        self._manager_refreshers.append(refresher)

    def _refresh_manager_lists(self):
        for refresher in list(self._manager_refreshers):
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
        history_window.title("Histórico de Notificações")
        history_window.geometry("680x360")
        history_window.minsize(560, 280)
        history_window.configure(bg=ui.surface)
        history_window.transient(root)
        self._set_window_icon(history_window)

        outer = tk.Frame(history_window, bg=ui.surface, padx=14, pady=14)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        tk.Label(
            outer,
            text="Últimas notificações",
            font=ui.font(11, "bold"),
            bg=ui.surface,
            fg=ui.text,
        ).grid(row=0, column=0, sticky="w")

        frame = tk.Frame(outer, bg=ui.card, highlightbackground=ui.border, highlightthickness=1)
        frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        columns = ("time", "kind", "message")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        tree.heading("time", text="Hora")
        tree.heading("kind", text="Tipo")
        tree.heading("message", text="Mensagem")
        tree.column("time", width=90, anchor="center", stretch=False)
        tree.column("kind", width=110, anchor="center", stretch=False)
        tree.column("message", width=440, anchor="w")

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        entries = list(reversed(self.notification_history))
        if not entries:
            tree.insert("", tk.END, values=("--:--:--", "status", "Nenhuma notificação registrada ainda."))
        else:
            for entry in entries:
                tree.insert(
                    "",
                    tk.END,
                    values=(entry.get("time", "--:--:--"), entry.get("kind", "info"), entry.get("message", "")),
                )

        self._bind_mousewheel(tree, tree)
        center_dialog(history_window, root)

    def _create_formatting_toolbar(self, parent, text_widget):
        """Add basic rich-text controls above a Tk text editor."""
        configure_rich_text_widget(text_widget)

        ui = ui_theme.theme()
        toolbar = tk.Frame(parent, **ui.toolbar_frame_colors())
        toolbar.pack(fill=tk.X, pady=(0, 6))
        # Where the buttons alone fill the row, the status gets its own line
        # below rather than pushing the last button off the pane.
        status_row = tk.Frame(parent, **ui.toolbar_frame_colors()) if ui.stacked_toolbar_status else toolbar
        if status_row is not toolbar:
            status_row.pack(fill=tk.X, pady=(0, 4))

        status_var = tk.StringVar(value="Formato: texto simples")

        def update_status(*_):
            payload = serialize_text_widget_content(text_widget)
            if isinstance(payload, dict):
                status_var.set("Formato: HTML + RTF")
            else:
                status_var.set("Formato: texto simples")

        def apply_style(style_name):
            if not toggle_text_style(text_widget, style_name):
                messagebox.showinfo("Formatação", "Selecione um trecho para formatar.")
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

        def add_toolbar_button(label, handler, width, padx, tooltip, font_key):
            button = tk.Button(
                toolbar,
                text=label,
                width=ui.button_width(width),
                takefocus=0,
                font=icon_fonts[font_key],
                relief=tk.FLAT,
                bd=0,
                padx=0,
                pady=0,
                highlightthickness=0,
                **ui.toolbar_button_colors(toolbar_bg),
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

        add_toolbar_button("B", lambda: apply_style("bold"), 2, (0, 3), "Formato: negrito", "bold")
        add_toolbar_button("I", lambda: apply_style("italic"), 2, 3, "Formato: itálico", "italic")
        add_toolbar_button("U", lambda: apply_style("underline"), 2, 3, "Formato: sublinhado", "underline")
        add_toolbar_button("S", lambda: apply_style("strike"), 2, 3, "Formato: tachado", "strike")
        add_toolbar_button("<>", lambda: apply_style("code"), 3, 6, "Formato: código monoespaçado", "code")
        add_toolbar_button("⌫", clear_styles_handler, 2, 3, "Formato: limpar estilos", "clear")

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
            picker.title("Inserir referência de snippet")
            picker.geometry("300x380")
            picker.resizable(False, True)
            picker.transient(parent_win)
            picker.grab_set()

            picker.configure(bg=ui.surface)

            search_var = tk.StringVar()
            tk.Entry(
                picker, textvariable=search_var, font=ui.font(10),
                relief=tk.FLAT, highlightthickness=1, highlightbackground=ui.border,
                **ui.entry_colors(),
            ).pack(fill=tk.X, padx=8, pady=8)

            lf = tk.Frame(picker, bg=ui.surface)
            lf.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
            lf.grid_columnconfigure(0, weight=1)
            lf.grid_rowconfigure(0, weight=1)

            listbox = tk.Listbox(lf, font=ui.font(10), selectmode=tk.SINGLE,
                                 relief=tk.FLAT, borderwidth=0, activestyle="none",
                                 **ui.listbox_colors())
            scrollbar = tk.Scrollbar(lf, orient=tk.VERTICAL, command=listbox.yview)
            listbox.config(yscrollcommand=scrollbar.set)
            listbox.grid(row=0, column=0, sticky="nsew")
            scrollbar.grid(row=0, column=1, sticky="ns")

            displayed = list(choices)

            def refresh_list(*_):
                nonlocal displayed
                query = search_var.get().strip().lower()
                displayed = [c for c in choices if query in c.lower()] if query else list(choices)
                listbox.delete(0, tk.END)
                for c in displayed:
                    listbox.insert(tk.END, c)

            search_var.trace_add("write", refresh_list)
            refresh_list()
            if displayed:
                listbox.selection_set(0)

            def confirm(*_):
                sel = listbox.curselection()
                if not sel:
                    return
                chosen = displayed[sel[0]]
                picker.destroy()
                _insert_variable_text(chosen)

            listbox.bind("<Double-Button-1>", confirm)
            listbox.bind("<Return>", confirm)
            tk.Button(picker, text="Inserir", command=confirm,
                      font=ui.font(9), relief=tk.FLAT, cursor="hand2",
                      **ui.button_colors(accent=True)).pack(pady=(0, 8))

            center_dialog(picker, parent_win)
            picker.focus_set()

        def insert_snippet_ref():
            # Every snippet kind is referenceable: static, runtime dynamic and
            # composed mapping triggers.
            names = {k for k in self.snippets if not k.startswith("_")}
            names |= composed_mapping_triggers(self.snippets)
            choices = sorted(names)
            if not choices:
                messagebox.showinfo("Variáveis", "Nenhum snippet disponível.",
                                    parent=text_widget.winfo_toplevel())
                return
            _show_snippet_picker(text_widget.winfo_toplevel(), choices)

        def insert_clipboard_var():
            _insert_variable_text("clipboard-paste")

        def insert_form_field():
            win = text_widget.winfo_toplevel()
            name = simpledialog.askstring("Campo de formulário", "Nome do campo:", parent=win)
            if name and name.strip():
                _insert_variable_text(name.strip().replace(" ", "_"))

        add_toolbar_button("%%s", insert_snippet_ref, 4, 3, "Variável: referenciar snippet (%%trigger%%)", "var")
        add_toolbar_button("%%cb", insert_clipboard_var, 4, 3, "Variável: colar clipboard (%%clipboard-paste%%)", "var")
        add_toolbar_button("%%?", insert_form_field, 4, 3, "Variável: campo de formulário (%%campo%%)", "var")

        tk.Label(status_row, textvariable=status_var, bg=toolbar_bg,
                 **ui.status_label_options()).pack(
                     side=tk.LEFT if status_row is not toolbar else tk.RIGHT)

        bind_shortcut("<Control-b>", "bold")
        bind_shortcut("<Control-i>", "italic")
        bind_shortcut("<Control-u>", "underline")
        text_widget.bind("<Control-Shift-C>", lambda event: (apply_style("code"), "break")[1])
        text_widget.bind("<Control-Shift-S>", lambda event: (apply_style("strike"), "break")[1])
        text_widget.bind("<KeyRelease>", update_status)
        text_widget.bind("<ButtonRelease-1>", update_status)
        update_status()
        return update_status
    def _create_static_snippets_tab(self, parent, root, set_count=None):
        """Build the static snippets tab UI.

        ``set_count`` receives the visible snippet count whenever the list is
        rebuilt, so the notebook tab title can show it.
        """
        ui = ui_theme.theme()

        main = tk.Frame(parent, bg=ui.surface, padx=14, pady=14)
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        frame_left = tk.LabelFrame(main, text="Biblioteca de snippets", font=ui.font(9, "bold"), bg=ui.card, fg=ui.text_native, padx=12, pady=12)
        frame_left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        frame_left.grid_columnconfigure(0, weight=1)
        frame_left.grid_rowconfigure(2, weight=1)

        search_var = tk.StringVar()
        tk.Label(frame_left, text="Buscar", font=ui.font(9), bg=ui.card, fg=ui.text_native).grid(row=0, column=0, sticky="w")
        search_entry = tk.Entry(frame_left, textvariable=search_var, font=ui.font(9), relief=tk.FLAT, highlightthickness=1, highlightbackground=ui.border, **ui.entry_colors())
        search_entry.grid(row=1, column=0, sticky="ew", pady=(4, 10))

        listbox_shell = tk.Frame(frame_left, bg=ui.card, highlightbackground=ui.border, highlightthickness=1)
        listbox_shell.grid(row=2, column=0, sticky="nsew")
        listbox_shell.grid_columnconfigure(0, weight=1)
        listbox_shell.grid_rowconfigure(0, weight=1)

        tree = self._create_snippet_tree(listbox_shell, trigger_heading="Trigger")

        frame_right = tk.LabelFrame(main, text="Editor de snippet", font=ui.font(9, "bold"), bg=ui.card, fg=ui.text_native, padx=12, pady=12)
        frame_right.grid(row=0, column=1, sticky="nsew")
        frame_right.grid_columnconfigure(0, weight=1)
        frame_right.grid_rowconfigure(3, weight=1)

        tk.Label(frame_right, text="Trigger", font=ui.font(9), bg=ui.card, fg=ui.text_native).grid(row=0, column=0, sticky="w")
        entry_trigger = tk.Entry(frame_right, font=ui.font(10), relief=tk.FLAT, highlightthickness=1, highlightbackground=ui.border, **ui.entry_colors())
        entry_trigger.grid(row=1, column=0, sticky="ew", pady=(4, 10))

        tk.Label(frame_right, text="Valor do snippet", font=ui.font(9), bg=ui.card, fg=ui.text_native).grid(row=2, column=0, sticky="w")
        editor_shell = tk.Frame(frame_right, bg=ui.card)
        editor_shell.grid(row=3, column=0, sticky="nsew")
        editor_shell.grid_columnconfigure(0, weight=1)
        editor_shell.grid_rowconfigure(1, weight=1)

        text_value = tk.Text(editor_shell, wrap=tk.WORD, font=ui.font(10), relief=tk.FLAT, highlightthickness=1, highlightbackground=ui.border, **ui.text_colors())
        update_format_status = self._create_formatting_toolbar(editor_shell, text_value)
        text_value.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        tk.Label(
            frame_right,
            text="Texto simples continua funcionando igual. Formatação é opcional.",
            font=ui.font(8),
            fg=ui.text_muted,
            bg=ui.card,
        ).grid(row=4, column=0, sticky="w", pady=(2, 10))

        btn_frame = tk.Frame(frame_right, bg=ui.card)
        btn_frame.grid(row=5, column=0, sticky="e")
        btn_new = tk.Button(btn_frame, text="Novo", width=ui.button_width(10))
        btn_save = tk.Button(btn_frame, text="Salvar", width=ui.button_width(10))
        btn_duplicate = tk.Button(btn_frame, text="Duplicar", width=ui.button_width(10))
        btn_rename = tk.Button(btn_frame, text="Renomear", width=ui.button_width(10))
        btn_delete = tk.Button(btn_frame, text="Excluir", width=ui.button_width(10))
        btn_new.pack(side=tk.LEFT, padx=(0, 6))
        btn_save.pack(side=tk.LEFT, padx=6)
        btn_duplicate.pack(side=tk.LEFT, padx=6)
        btn_rename.pack(side=tk.LEFT, padx=6)
        btn_delete.pack(side=tk.LEFT, padx=(6, 0))

        self._bind_mousewheel(text_value, text_value)

        def get_static_visible_snippets():
            visible = filter_static_snippets(self.snippets, search_var.get())
            # A blank key cannot be a Treeview row iid (or a trigger); hand-
            # edited data must not produce a phantom row or skew the count.
            visible.pop("", None)
            return visible

        static_snips = get_static_visible_snippets()

        def refresh_listbox():
            tree.delete(*tree.get_children())
            static_snips.clear()
            static_snips.update(get_static_visible_snippets())
            for key in sorted(static_snips.keys()):
                tree.insert("", tk.END, iid=key,
                            values=snippet_row_values(key, static_snips[key]))
            if set_count is not None:
                set_count(len(static_snips))

        def load_selected(event=None):
            selection = tree.selection()
            if not selection:
                return
            key = selection[0]
            entry_trigger.delete(0, tk.END)
            entry_trigger.insert(0, key)
            load_value_into_text_widget(text_value, static_snips.get(key, ""))
            update_format_status()

        def on_new():
            entry_trigger.delete(0, tk.END)
            load_value_into_text_widget(text_value, "")
            update_format_status()
            entry_trigger.focus_set()

        def on_save():
            trigger = entry_trigger.get().strip()
            value = serialize_text_widget_content(text_value)

            if not trigger:
                messagebox.showwarning("Aviso", "Informe um trigger.")
                return
            if trigger.startswith("_"):
                messagebox.showwarning("Aviso", "Triggers com '_' são reservados.")
                return
            if not extract_plain_text(value).strip():
                messagebox.showwarning("Aviso", "Informe um valor para o snippet.")
                return

            # "Already in self.snippets" is not the same as "editing an existing
            # static": a dynamic trigger occupies the key too, and that is exactly
            # the collision that needs the warning.
            if trigger not in self.snippets or callable(self.snippets[trigger]):
                warnings = self._validate_trigger_warnings(trigger)
                if warnings and not messagebox.askyesno(
                    "Confirmar trigger",
                    "Avisos sobre este trigger:\n\n• " + "\n• ".join(warnings) + "\n\nSalvar mesmo assim?",
                ):
                    return

            # Saving over a live dynamic trigger records the static for disk but
            # leaves the callable in the merged map, so the trigger keeps
            # expanding as the dynamic snippet this session (see helper).
            self._store_static_snippet(trigger, value)
            if not self.save_snippets(self.snippets):
                messagebox.showerror(
                    "Erro ao salvar",
                    "Não foi possível gravar snippets.json. Verifique os logs; suas edições podem não ter sido salvas.",
                )
                return
            self.refresh_runtime_indexes()
            self.notify_status(f"Snippet '{trigger}' salvo.", key=f"save-static:{trigger}")

            refresh_listbox()
            update_format_status()

        def on_delete():
            trigger = entry_trigger.get().strip()
            if not trigger:
                messagebox.showwarning("Aviso", "Selecione um snippet.")
                return

            result = self._delete_static_snippet(
                trigger,
                lambda: messagebox.askyesno("Confirmar", f"Excluir '{trigger}'?"),
            )
            if result == "dynamic":
                # A dynamic trigger owns the name; the free-text box let the user
                # type it. Deleting would discard the shadowed static from disk,
                # so refuse and point at the tab that manages the dynamic entry.
                messagebox.showwarning(
                    "Aviso",
                    f"'{trigger}' é um snippet dinâmico. Gerencie-o na aba Snippets Dinâmicos.",
                )
                return
            if result == "error":
                messagebox.showerror(
                    "Erro ao salvar",
                    "Não foi possível gravar snippets.json. Verifique os logs; a exclusão pode não ter sido salva.",
                )
                return
            if result != "ok":
                return
            entry_trigger.delete(0, tk.END)
            load_value_into_text_widget(text_value, "")
            update_format_status()
            refresh_listbox()
            self.notify_status(f"Snippet '{trigger}' excluído.", key=f"delete-static:{trigger}")

        def on_duplicate():
            value = serialize_text_widget_content(text_value)
            if not extract_plain_text(value).strip():
                messagebox.showwarning("Aviso", "Nada para duplicar.")
                return
            # Keep the value, clear the trigger so the user names the copy.
            entry_trigger.delete(0, tk.END)
            update_format_status()
            entry_trigger.focus_set()
            messagebox.showinfo("Duplicar", "Informe um novo trigger e clique em Salvar para criar a cópia.")

        def on_rename():
            old_trigger = entry_trigger.get().strip()
            if old_trigger not in self.snippets:
                messagebox.showwarning("Aviso", "Selecione um snippet salvo para renomear.")
                return
            if callable(self.snippets[old_trigger]):
                messagebox.showwarning(
                    "Aviso",
                    f"'{old_trigger}' é um snippet dinâmico. Renomeie-o na aba Snippets Dinâmicos.",
                )
                return
            new_trigger = simpledialog.askstring("Renomear", "Novo trigger:", initialvalue=old_trigger, parent=root)
            if not new_trigger:
                return
            new_trigger = new_trigger.strip()
            if new_trigger == old_trigger:
                return
            if new_trigger.startswith("_"):
                messagebox.showwarning("Aviso", "Triggers com '_' são reservados.")
                return
            if new_trigger in self.snippets:
                messagebox.showwarning("Aviso", f"O trigger '{new_trigger}' já existe.")
                return
            warnings = self._validate_trigger_warnings(new_trigger)
            if warnings and not messagebox.askyesno(
                "Confirmar trigger",
                "Avisos sobre este trigger:\n\n• " + "\n• ".join(warnings) + "\n\nRenomear mesmo assim?",
            ):
                return
            value = self.snippets[old_trigger]
            self.snippets[new_trigger] = value
            del self.snippets[old_trigger]
            shadowed = self.shadowed_static_snippets.pop(old_trigger, None)
            if not self.save_snippets(self.snippets):
                # Roll back the in-memory rename on failure.
                self.snippets[old_trigger] = value
                self.snippets.pop(new_trigger, None)
                if shadowed is not None:
                    self.shadowed_static_snippets[old_trigger] = shadowed
                messagebox.showerror("Erro ao salvar", "Não foi possível gravar snippets.json.")
                return
            self.refresh_runtime_indexes()
            entry_trigger.delete(0, tk.END)
            entry_trigger.insert(0, new_trigger)
            refresh_listbox()
            self.notify_status(f"Snippet renomeado para '{new_trigger}'.", key=f"rename-static:{new_trigger}")

        tree.bind("<<TreeviewSelect>>", load_selected)
        btn_new.configure(command=on_new)
        btn_save.configure(command=on_save)
        btn_duplicate.configure(command=on_duplicate)
        btn_rename.configure(command=on_rename)
        btn_delete.configure(command=on_delete)
        search_var.trace_add("write", lambda *_: refresh_listbox())
        # Ctrl+S saves the current static snippet from anywhere in the editor.
        for widget in (entry_trigger, text_value, tree):
            widget.bind("<Control-s>", lambda _event: (on_save(), "break")[1])

        refresh_listbox()
        self._register_manager_refresher(refresh_listbox)
        search_entry.focus_set()

    def _create_dynamic_mappings_tab(self, parent, root, set_count=None):
        """Build the dynamic mappings UI with customizable types.

        ``set_count`` receives the visible item count of the selected mapping
        type whenever the list is rebuilt.
        """
        ui = ui_theme.theme()

        main = tk.Frame(parent, bg=ui.surface, padx=14, pady=14)
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        mapping_type = tk.StringVar(value="_cpf_numbers")

        def get_mappings_info():
            base = {
                "_cpf_numbers": {"label": "CPF", "prefix": "cpf", "example": "cpffulano -> 123.456.789-00", "builtin": True},
                "_cnpj_numbers": {"label": "CNPJ", "prefix": "cnpj", "example": "cnpjempresa1 -> 12.345.678/0001-90", "builtin": True},
            }

            for key, value in self.snippets.items():
                if key.startswith("_") and key.endswith(("_numbers", "_codes")) and isinstance(value, dict) and key not in base:
                    prefix = value.get("__prefix__") or key[1:].replace("_numbers", "").replace("_codes", "")
                    type_label = key[1:].replace("_numbers", "").replace("_codes", "").upper()
                    base[key] = {
                        "label": type_label,
                        "prefix": prefix,
                        "example": f"{prefix}exemplo -> valor",
                        "builtin": False,
                    }
            return base

        mappings_info = get_mappings_info()

        def update_example_label():
            info = mappings_info.get(mapping_type.get(), {})
            prefix = info.get("prefix", "")
            example = info.get("example", "")
            lbl_example.config(text=f"{info.get('label', 'Tipo')} | Prefixo: {prefix} | Exemplo: {example}")

        def refresh_type_list():
            nonlocal mappings_info
            mappings_info = get_mappings_info()

            listbox_types.delete(0, tk.END)
            type_keys.clear()
            for key, info in sorted(mappings_info.items(), key=lambda item: (not item[1]["builtin"], item[1]["label"])):
                type_keys.append(key)
                listbox_types.insert(tk.END, info["label"])

            if mapping_type.get() not in type_keys and type_keys:
                mapping_type.set(type_keys[0])

            current = mapping_type.get()
            if current in type_keys:
                index = type_keys.index(current)
                listbox_types.selection_clear(0, tk.END)
                listbox_types.selection_set(index)
                listbox_types.see(index)
            update_example_label()

        def on_type_select(_event=None):
            selection = listbox_types.curselection()
            if not selection:
                return
            key = type_keys[selection[0]]
            # Guard the write so the trace only fires on a real change.
            if key != mapping_type.get():
                mapping_type.set(key)

        def ensure_mapping_dict(current_type):
            mapping = self.snippets.get(current_type)
            if not isinstance(mapping, dict):
                mapping = {}
                self.snippets[current_type] = mapping
            return mapping

        lbl_example = tk.Label(main, text="", font=ui.font(8), fg=ui.text_muted, bg=ui.surface)
        lbl_example.grid(row=1, column=0, sticky="w", pady=(0, 10))

        content = tk.Frame(main, bg=ui.surface)
        content.grid(row=2, column=0, sticky="nsew")
        content.grid_columnconfigure(2, weight=1)
        content.grid_rowconfigure(0, weight=1)

        # Types live in a scrollable vertical list so any number of custom
        # mapping types stays reachable (a horizontal row clipped them).
        frame_types = tk.LabelFrame(content, text="Tipos", font=ui.font(9, "bold"), bg=ui.card, fg=ui.text_native, padx=12, pady=12)
        frame_types.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        frame_types.grid_columnconfigure(0, weight=1)
        frame_types.grid_rowconfigure(0, weight=1)

        types_list_frame = tk.Frame(frame_types, bg=ui.card, highlightbackground=ui.border, highlightthickness=1)
        types_list_frame.grid(row=0, column=0, sticky="nsew")
        types_list_frame.grid_columnconfigure(0, weight=1)
        types_list_frame.grid_rowconfigure(0, weight=1)

        type_keys = []
        listbox_types = tk.Listbox(
            types_list_frame,
            font=ui.font(10),
            relief=tk.FLAT,
            borderwidth=0,
            activestyle="none",
            width=16,
            exportselection=False,
            **ui.listbox_colors(),
        )
        scrollbar_types = tk.Scrollbar(types_list_frame, orient=tk.VERTICAL, command=listbox_types.yview)
        listbox_types.config(yscrollcommand=scrollbar_types.set)
        listbox_types.grid(row=0, column=0, sticky="nsew")
        scrollbar_types.grid(row=0, column=1, sticky="ns")

        btn_types_frame = tk.Frame(frame_types, bg=ui.card)
        btn_types_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        frame_left = tk.LabelFrame(content, text="Itens do mapeamento", font=ui.font(9, "bold"), bg=ui.card, fg=ui.text_native, padx=12, pady=12)
        frame_left.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        frame_left.grid_columnconfigure(0, weight=1)
        frame_left.grid_rowconfigure(2, weight=1)

        map_search_var = tk.StringVar()
        tk.Label(frame_left, text="Buscar", font=ui.font(9), bg=ui.card, fg=ui.text_native).grid(row=0, column=0, sticky="w")
        tk.Entry(frame_left, textvariable=map_search_var, font=ui.font(9), relief=tk.FLAT, highlightthickness=1, highlightbackground=ui.border, **ui.entry_colors()).grid(row=1, column=0, sticky="ew", pady=(4, 10))

        listbox_frame = tk.Frame(frame_left, bg=ui.card, highlightbackground=ui.border, highlightthickness=1)
        listbox_frame.grid(row=2, column=0, sticky="nsew")
        listbox_frame.grid_columnconfigure(0, weight=1)
        listbox_frame.grid_rowconfigure(0, weight=1)

        tree_map = self._create_snippet_tree(
            listbox_frame, trigger_heading="Identificador",
            trigger_width=88, preview_width=118)

        frame_right = tk.LabelFrame(content, text="Editor do item", font=ui.font(9, "bold"), bg=ui.card, fg=ui.text_native, padx=12, pady=12)
        frame_right.grid(row=0, column=2, sticky="nsew")
        frame_right.grid_columnconfigure(0, weight=1)
        frame_right.grid_rowconfigure(3, weight=1)

        tk.Label(frame_right, text="Identificador", font=ui.font(9), bg=ui.card, fg=ui.text_native).grid(row=0, column=0, sticky="w")
        entry_name = tk.Entry(frame_right, font=ui.font(10), relief=tk.FLAT, highlightthickness=1, highlightbackground=ui.border, **ui.entry_colors())
        entry_name.grid(row=1, column=0, sticky="ew", pady=(4, 10))

        tk.Label(frame_right, text="Valor", font=ui.font(9), bg=ui.card, fg=ui.text_native).grid(row=2, column=0, sticky="w")
        editor_shell = tk.Frame(frame_right, bg=ui.card)
        editor_shell.grid(row=3, column=0, sticky="nsew")
        editor_shell.grid_columnconfigure(0, weight=1)
        editor_shell.grid_rowconfigure(1, weight=1)

        text_value = tk.Text(editor_shell, wrap=tk.WORD, font=ui.font(10), relief=tk.FLAT, highlightthickness=1, highlightbackground=ui.border, **ui.text_colors())
        update_format_status = self._create_formatting_toolbar(editor_shell, text_value)
        text_value.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        tk.Label(
            frame_right,
            text="Mapeamentos também aceitam formatação opcional.",
            font=ui.font(8),
            fg=ui.text_muted,
            bg=ui.card,
        ).grid(row=4, column=0, sticky="w", pady=(2, 10))

        btn_frame = tk.Frame(frame_right, bg=ui.card)
        btn_frame.grid(row=5, column=0, sticky="e")
        btn_new_map = tk.Button(btn_frame, text="Novo", width=ui.button_width(12))
        btn_save_map = tk.Button(btn_frame, text="Salvar", width=ui.button_width(12))
        btn_delete_map = tk.Button(btn_frame, text="Excluir", width=ui.button_width(12))
        btn_new_map.pack(side=tk.LEFT, padx=(0, 6))
        btn_save_map.pack(side=tk.LEFT, padx=6)
        btn_delete_map.pack(side=tk.LEFT, padx=(6, 0))

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

        def refresh_mapping_list():
            tree_map.delete(*tree_map.get_children())
            current_type = mapping_type.get()
            query = map_search_var.get()
            mapping = self.snippets.get(current_type, {})
            if not isinstance(mapping, dict):
                mapping = {}
            for key in iter_filtered_mapping_items(mapping, query):
                if not key:
                    continue  # a blank key cannot be a Treeview row iid
                tree_map.insert("", tk.END, iid=key,
                                values=snippet_row_values(key, mapping.get(key, "")))
            update_total_count()
            update_example_label()

        def add_new_type():
            dialog = tk.Toplevel(root)
            dialog.title("Novo Tipo de Mapeamento")
            dialog.resizable(False, False)
            dialog.transient(root)
            dialog.grab_set()
            dialog.configure(bg=ui.surface)
            self._set_window_icon(dialog)

            body = tk.Frame(dialog, bg=ui.surface, padx=18, pady=18)
            body.pack(fill=tk.BOTH, expand=True)
            tk.Label(body, text="Criar novo tipo de mapeamento dinâmico", font=ui.font(10, "bold"), bg=ui.surface, fg=ui.text_native).pack(anchor="w")
            tk.Label(body, text="Nome do tipo", font=ui.font(9), bg=ui.surface, fg=ui.text_native).pack(anchor="w", pady=(12, 0))
            entry_type_name = tk.Entry(body, font=ui.font(10), **ui.entry_colors())
            entry_type_name.pack(fill=tk.X, pady=(4, 8))
            tk.Label(body, text="Prefixo usado no trigger", font=ui.font(9), bg=ui.surface, fg=ui.text_native).pack(anchor="w")
            entry_prefix = tk.Entry(body, font=ui.font(10), **ui.entry_colors())
            entry_prefix.pack(fill=tk.X, pady=(4, 8))
            tk.Label(body, text="Ex.: tipo 'email' + prefixo 'mail' -> mailtrabalho", font=ui.font(8), fg=ui.text_muted, bg=ui.surface).pack(anchor="w")

            def save_new_type():
                type_name = entry_type_name.get().strip().lower()
                prefix = entry_prefix.get().strip().lower()

                if not type_name or not prefix:
                    messagebox.showwarning("Aviso", "Preencha todos os campos.", parent=dialog)
                    return
                if not type_name.replace("_", "").isalnum() or not prefix.replace("_", "").isalnum():
                    messagebox.showwarning("Aviso", "Use apenas letras, números e underscores.", parent=dialog)
                    return

                map_key = f"_{type_name}_codes"
                if map_key in self.snippets:
                    messagebox.showwarning("Aviso", f"Tipo '{type_name}' já existe.", parent=dialog)
                    return

                self.snippets[map_key] = {"__prefix__": prefix}
                if not self.save_snippets(self.snippets):
                    del self.snippets[map_key]
                    messagebox.showerror(
                        "Erro ao salvar",
                        "Não foi possível gravar snippets.json. Verifique os logs; o tipo não foi criado.",
                        parent=dialog,
                    )
                    return
                self.refresh_runtime_indexes()
                refresh_type_list()
                mapping_type.set(map_key)
                on_type_changed()
                self.notify_status(f"Tipo '{type_name}' criado.", key=f"mapping-type-create:{type_name}")
                dialog.destroy()

            tk.Button(body, text="Criar Tipo", command=save_new_type, width=ui.button_width(15)).pack(anchor="e", pady=(14, 0))
            center_dialog(dialog, root)
            entry_type_name.focus_set()

        def delete_current_type():
            current_type = mapping_type.get()
            info = mappings_info.get(current_type, {})

            if info.get("builtin", False):
                messagebox.showwarning("Aviso", "Não é possível excluir tipos padrão (CPF, CNPJ).")
                return
            if current_type not in self.snippets:
                return
            if not messagebox.askyesno("Confirmar", f"Excluir o tipo '{info.get('label', current_type)}' e todos os itens?"):
                return

            removed_mapping = self.snippets.pop(current_type)
            if not self.save_snippets(self.snippets):
                self.snippets[current_type] = removed_mapping
                messagebox.showerror(
                    "Erro ao salvar",
                    "Não foi possível gravar snippets.json. Verifique os logs; o tipo não foi excluído.",
                )
                return
            self.refresh_runtime_indexes()

            refresh_type_list()
            available_keys = list(mappings_info.keys())
            if available_keys:
                mapping_type.set(available_keys[0])
            entry_name.delete(0, tk.END)
            load_value_into_text_widget(text_value, "")
            update_format_status()
            refresh_mapping_list()
            self.notify_status(f"Tipo '{info.get('label', current_type)}' excluído.", key=f"mapping-type-delete:{current_type}")

        tk.Button(btn_types_frame, text="Novo Tipo", command=add_new_type).pack(fill=tk.X)
        tk.Button(btn_types_frame, text="Excluir Tipo", command=delete_current_type).pack(fill=tk.X, pady=(6, 0))

        listbox_types.bind("<<ListboxSelect>>", on_type_select)
        self._bind_mousewheel(listbox_types, listbox_types)
        self._bind_mousewheel(text_value, text_value)

        def load_selected_mapping(event=None):
            selection = tree_map.selection()
            if not selection:
                return

            current_type = mapping_type.get()
            key = selection[0]
            mapping = self.snippets.get(current_type, {})

            entry_name.delete(0, tk.END)
            entry_name.insert(0, key)
            load_value_into_text_widget(text_value, mapping.get(key, ""))
            update_format_status()

        def on_type_changed(*args):
            refresh_mapping_list()
            entry_name.delete(0, tk.END)
            load_value_into_text_widget(text_value, "")
            update_format_status()

        def on_new_map():
            entry_name.delete(0, tk.END)
            load_value_into_text_widget(text_value, "")
            update_format_status()
            entry_name.focus_set()

        def on_save_map():
            mappings = get_mappings_info()
            current_type = mapping_type.get()
            name = entry_name.get().strip()
            value = serialize_text_widget_content(text_value)

            if not name:
                messagebox.showwarning("Aviso", "Informe um identificador.")
                return
            if not extract_plain_text(value).strip():
                messagebox.showwarning("Aviso", "Informe um valor.")
                return

            mapping = ensure_mapping_dict(current_type)
            prefix_key = mapping.get("__prefix__")
            existed = name in mapping
            previous_value = mapping.get(name)
            mapping[name] = value
            if prefix_key:
                mapping["__prefix__"] = prefix_key

            if not self.save_snippets(self.snippets):
                if existed:
                    mapping[name] = previous_value
                else:
                    mapping.pop(name, None)
                messagebox.showerror(
                    "Erro ao salvar",
                    "Não foi possível gravar snippets.json. Verifique os logs; o item não foi salvo.",
                )
                return
            self.refresh_runtime_indexes()
            self.notify_status(f"Item '{name}' salvo em {mappings.get(current_type, {}).get('label', current_type)}.", key=f"save-map:{current_type}:{name}")
            refresh_mapping_list()
            update_format_status()

        def on_delete_map():
            current_type = mapping_type.get()
            name = entry_name.get().strip()

            if not name:
                messagebox.showwarning("Aviso", "Selecione um item.")
                return

            mapping = self.snippets.get(current_type, {})
            if isinstance(mapping, dict) and name in mapping and messagebox.askyesno("Confirmar", f"Excluir '{name}'?"):
                removed_value = mapping.pop(name)
                if not self.save_snippets(self.snippets):
                    mapping[name] = removed_value
                    messagebox.showerror(
                        "Erro ao salvar",
                        "Não foi possível gravar snippets.json. Verifique os logs; a exclusão não foi salva.",
                    )
                    return
                self.refresh_runtime_indexes()
                entry_name.delete(0, tk.END)
                load_value_into_text_widget(text_value, "")
                update_format_status()
                refresh_mapping_list()
                self.notify_status(f"Item '{name}' excluído.", key=f"delete-map:{current_type}:{name}")

        refresh_type_list()
        mapping_type.trace_add("write", lambda *_: on_type_changed())
        tree_map.bind("<<TreeviewSelect>>", load_selected_mapping)
        btn_new_map.configure(command=on_new_map)
        btn_save_map.configure(command=on_save_map)
        btn_delete_map.configure(command=on_delete_map)
        map_search_var.trace_add("write", lambda *_: refresh_mapping_list())

        def refresh_all_mappings():
            # A restore/import can drop the selected type entirely, so the type
            # list has to be rebuilt before the items are.
            refresh_type_list()
            refresh_mapping_list()

        refresh_mapping_list()
        self._register_manager_refresher(refresh_all_mappings)

    def _create_reference_tab(self, parent, root, section_title, subtitle, sections, footer_text):
        ui = ui_theme.theme()
        main = tk.Frame(parent, bg=ui.surface, padx=14, pady=14)
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        header_card = tk.Frame(main, bg=ui.card, highlightbackground=ui.border, highlightthickness=1, padx=14, pady=12)
        header_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        tk.Label(header_card, text=section_title, font=ui.font(11, "bold"), bg=ui.card, fg=ui.text).pack(anchor="w")
        tk.Label(header_card, text=subtitle, font=ui.font(9), bg=ui.card, fg=ui.text_muted).pack(anchor="w", pady=(4, 0))

        content = tk.Frame(main, bg=ui.card, highlightbackground=ui.border, highlightthickness=1)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        canvas = tk.Canvas(content, bg=ui.card, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=canvas.yview)
        inner = tk.Frame(canvas, bg=ui.card, padx=12, pady=12)
        inner.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))

        def populate():
            for child in inner.winfo_children():
                child.destroy()
            grouped = reference_entries_by_category(self.dynamic_registry)
            for title, category_key in sections:
                entries = grouped.get(category_key, [])
                section = tk.LabelFrame(inner, text=title, font=ui.font(9, "bold"), bg=ui.card, fg=ui.text_native, padx=12, pady=12)
                section.pack(fill=tk.X, expand=True, pady=(0, 12))
                for key, trigger, desc, enabled in entries:
                    row = tk.Frame(section, bg=ui.card)
                    row.pack(fill=tk.X, pady=2)
                    var = tk.BooleanVar(value=enabled)
                    # The checkbox writes by stable key, not by the (renameable) trigger.
                    tk.Checkbutton(
                        row,
                        variable=var,
                        command=lambda k=key, v=var: self._on_registry_checkbox(k, v),
                        **ui.checkbutton_colors(ui.card),
                    ).pack(side=tk.LEFT)
                    trigger_label = tk.Label(row, text=trigger, font=ui.mono_font(10, "bold"), fg=ui.link, bg=ui.card, width=12, anchor="w")
                    trigger_label.pack(side=tk.LEFT)
                    rename = lambda event=None, k=key, t=trigger: self._rename_registry_entry_dialog(root, k, t, populate)
                    trigger_label.bind("<Double-Button-1>", rename)
                    tk.Button(
                        row,
                        text="✎",
                        font=ui.font(8),
                        bd=0,
                        relief=tk.FLAT,
                        cursor="hand2",
                        command=rename,
                        **ui.glyph_button_colors(ui.card),
                    ).pack(side=tk.LEFT, padx=(0, 4))
                    tk.Label(row, text=desc, font=ui.font(9), bg=ui.card, fg=ui.text_native, anchor="w").pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)
            self._bind_mousewheel_descendants(inner, canvas)

        populate()

        tk.Label(main, text=footer_text, font=ui.font(8), fg=ui.text_muted, bg=ui.surface).grid(row=2, column=0, sticky="w", pady=(10, 0))

        self._bind_mousewheel(canvas, canvas)

    def _on_registry_checkbox(self, key, var):
        """Apply a checkbox toggle, snapping the box back when it is refused."""
        enabled = var.get()
        if not self._toggle_registry_entry(key, enabled):
            var.set(not enabled)

    def _toggle_registry_entry(self, key, enabled):
        """Enable/disable a dynamic trigger, persisting to the user override file.

        Keyed by the stable registry id so a renamed trigger still writes the
        right override entry. Returns True when the change was applied.
        """
        if enabled and not self._confirm_dynamic_shadows_static(key):
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
            self.notify_error("Falha ao salvar alteração do snippet dinâmico.", key="registry-save")
            return False

        self.dynamic_registry = load_registry(
            self.resolve_resource_path("dynamic_snippets.json"),
            self.dynamic_registry_file,
            logger=self.logger,
        )
        self.reload_snippets_from_disk()
        self.export_sync_bundle()
        state = "ativado" if enabled else "desativado"
        trigger = effective_trigger(key, self.dynamic_registry.get(key, {}))
        self.notify_status(f"Snippet dinâmico '{trigger}' {state}.", key=f"registry-toggle:{key}")
        return True

    def _confirm_dynamic_shadows_static(self, key):
        """Ask before enabling a dynamic trigger that shadows an existing trigger.

        ``validate_rename`` blocks both collisions when they come from a rename;
        the enable toggle reaches the same state, so it needs the same check.
        Enabling is allowed with confirmation: the shadowed value stays on disk
        (a static snippet in ``snippets.json``, or the mapping container a
        composed trigger like ``cpffulano`` is built from), and the dynamic
        snippet is what expands.
        """
        trigger = effective_trigger(key, self.dynamic_registry.get(key, {}))
        if trigger.startswith("_"):
            return True

        value = self.snippets.get(trigger)
        if value is not None and not callable(value):
            self.logger.warning(
                f"Ativar o snippet dinâmico '{trigger}' sobrepõe o snippet estático de mesmo nome."
            )
            return messagebox.askyesno(
                "Trigger em conflito",
                f"Já existe um snippet estático com o trigger '{trigger}'.\n\n"
                "Ao ativar o dinâmico, é ele que passa a expandir. O texto estático "
                "continua salvo em snippets.json, mas deixa de ser acionado.\n\nAtivar mesmo assim?",
            )

        # A mapping-composed trigger (e.g. ``cpffulano`` from the ``_cpf_numbers``
        # container) is never a direct key in ``self.snippets`` — it resolves via
        # ``check_dynamic_pattern`` against the ``_``-prefixed container — so the
        # direct lookup above misses it. Enabling the dynamic entry still changes
        # what the user's typing expands to, so it needs the same confirmation.
        if value is None and trigger in composed_mapping_triggers(self.snippets):
            self.logger.warning(
                f"Ativar o snippet dinâmico '{trigger}' sobrepõe um mapeamento dinâmico de mesmo nome."
            )
            return messagebox.askyesno(
                "Trigger em conflito",
                f"Já existe um mapeamento dinâmico com o trigger '{trigger}'.\n\n"
                "Ao ativar o snippet dinâmico, é ele que passa a expandir. O valor mapeado "
                "continua salvo no container de mapeamento, mas deixa de ser acionado.\n\n"
                "Ativar mesmo assim?",
            )

        return True

    def _create_dynamic_snippets_tab(self, parent, root):
        """Build the single tab listing every built-in dynamic snippet."""
        self._create_reference_tab(
            parent,
            root,
            "Snippets dinâmicos integrados",
            "Data/hora local, indicadores do Banco Central, ações e atalhos de WhatsApp.",
            [
                ("Data e Hora", "datetime"),
                ("Indicadores Econômicos (Banco Central)", "economy"),
                ("Ações (B3 e US)", "stock"),
                ("WhatsApp", "whatsapp"),
            ],
            "Use a caixa de seleção para ativar/desativar. Clique em ✎ (ou dê dois cliques no trigger) para renomear.",
        )

    def _rename_registry_entry_dialog(self, root, key, current_trigger, refresh):
        """Ask for a new trigger name, validate it, then persist and refresh."""
        new_trigger = simpledialog.askstring(
            "Renomear trigger",
            f"Novo trigger para '{current_trigger}':",
            initialvalue=current_trigger,
            parent=root,
        )
        if new_trigger is None:
            return
        new_trigger = new_trigger.strip()
        if not new_trigger or new_trigger == current_trigger:
            return

        errors, warnings = validate_rename(self.dynamic_registry, key, new_trigger, self.snippets)
        if errors:
            messagebox.showerror("Trigger inválido", "\n".join(errors), parent=root)
            return
        if warnings:
            proceed = messagebox.askyesno(
                "Confirmar trigger",
                "\n".join(warnings) + "\n\nDeseja continuar mesmo assim?",
                parent=root,
            )
            if not proceed:
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
            self.notify_error("Falha ao salvar o novo nome do snippet dinâmico.", key="registry-save")
            return False

        self.dynamic_registry = load_registry(
            self.resolve_resource_path("dynamic_snippets.json"),
            self.dynamic_registry_file,
            logger=self.logger,
        )
        self.reload_snippets_from_disk()
        self.export_sync_bundle()
        self.notify_status(
            f"Snippet dinâmico renomeado para '{new_trigger}'.",
            key=f"registry-rename:{key}",
        )
        return True

    # =====================================================================
    # UI / SYSTEM TRAY
    # =====================================================================

    def create_icon_image(self):
        """Create a modern icon for the system tray."""
        size = 64

        if self.enabled:
            ring_color = (38, 92, 255, 255)
            accent_color = (27, 43, 65, 255)
            mark_color = (255, 255, 255, 255)
            dot_color = (76, 217, 100, 255)
        else:
            ring_color = (168, 176, 185, 255)
            accent_color = (108, 117, 125, 255)
            mark_color = (243, 245, 247, 255)
            dot_color = (196, 200, 205, 255)

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

        # Small status dot keeps enabled/disabled state obvious.
        dc.ellipse((42, 42, 52, 52), fill=dot_color)

        return image

    def load_tray_icon(self):
        """Prefer the packaged ICO file when available for better tray compatibility."""
        icon_path = self.resolve_resource_path("txt_xpander.ico")
        if icon_path:
            try:
                with Image.open(icon_path) as image:
                    return image.copy()
            except Exception as e:
                self.logger.warning(f"Falha ao carregar icone do tray: {e}")
        return self.create_icon_image()

    def toggle_enabled(self, icon, item):
        """Enable/disable snippet expansion."""
        self.enabled = not self.enabled
        icon.icon = self.load_tray_icon()
        status = "ativada" if self.enabled else "desativada"
        self.notify_status(f"Expansão de snippets {status}.", key="toggle-enabled")
    
    
    def reload_snippets(self, icon, item):
        """Reload snippets from the file."""
        try:
            self.snippets = self.load_snippets()
            self.refresh_runtime_indexes()
            self.notify_status("Snippets recarregados com sucesso.", key="reload-snippets")
        except Exception as e:
            self.notify_error(
                f"Erro ao recarregar snippets: {str(e)}",
                key="reload-snippets-error",
                cooldown_seconds=5,
            )
    def tray_backup_now(self, icon, item):
        """Tray action: create an immediate backup of the library."""
        created = self.backup_now()
        if created:
            self.notify_status(f"Backup criado: {os.path.basename(created)}", key="manual-backup")
        else:
            self.notify_error("Falha ao criar backup. Verifique os logs.", key="manual-backup")

    def autostart_is_enabled(self, item=None):
        """Menu state for the autostart toggle: a cache read, never a disk read."""
        return self._autostart_state == AUTOSTART_CURRENT

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
        dead = existing[0] if existing else "(vazio)"
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
        window.title("Permissões do macOS")
        window.resizable(False, False)
        window.configure(bg=ui.surface)
        window.attributes("-topmost", True)
        self._set_window_icon(window)

        container = tk.Frame(window, bg=ui.surface, padx=18, pady=18)
        container.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            container,
            text="Permissões necessárias",
            font=ui.font(12, "bold"),
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
            tk.Button(
                panes,
                text=f"Abrir {macos_permissions.PERMISSION_LABELS[name]}",
                command=lambda permission=name: self._open_macos_settings_pane(permission),
            ).pack(side=tk.LEFT, padx=(0, 8))

        buttons = tk.Frame(container, bg=ui.surface)
        buttons.pack(fill=tk.X, pady=(14, 0))

        def on_close():
            self.macos_permission_window = None
            window.destroy()

        def on_recheck():
            feedback.config(text="Verificando…", fg=ui.text_muted)
            self.task_runner.start(
                lambda: self._recheck_macos_permissions(status, window, feedback),
                name="macos-permissions-recheck",
            )

        tk.Button(buttons, text="Fechar", width=ui.button_width(12), command=on_close).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(buttons, text="Verificar novamente", command=on_recheck).pack(side=tk.RIGHT)

        window.protocol("WM_DELETE_WINDOW", on_close)
        center_on_screen(window)
        window.lift()
        window.focus_force()

    def _open_macos_settings_pane(self, permission):
        """Deep-link System Settings to one pane. GUI thread; `open` returns at once."""
        label = macos_permissions.PERMISSION_LABELS.get(permission, permission)
        if macos_permissions.open_settings_pane(permission):
            self.logger.info(f"Painel de permissão aberto: {label}")
            return
        self.logger.error(f"Falha ao abrir o painel de permissão: {label}")
        self.notify_error(
            f"Não foi possível abrir o painel {label}. "
            "Abra Ajustes do Sistema › Privacidade e Segurança manualmente.",
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
            self._update_permission_feedback(window, feedback, "Não foi possível verificar agora.", ui.warning)
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
                "Alteração de início automático em andamento; aguarde.",
                key="autostart-busy",
            )
            return
        try:
            # Direction follows the cached state, so a stale entry (shown
            # unchecked) is overwritten by the install branch rather than removed.
            if self._autostart_state == AUTOSTART_CURRENT:
                remove_autostart(APP_NAME)
                self._autostart_state = AUTOSTART_ABSENT
                self.notify_status("Início automático desativado.", key="autostart")
            else:
                path = install_autostart(APP_NAME)
                self._autostart_state = AUTOSTART_CURRENT
                self.logger.info(f"Inicialização automática instalada: {path}")
                self.notify_status("Início automático ativado.", key="autostart")
        except Exception as e:
            # Broad for the same reason as resolve_autostart_state: an escape
            # here dies invisibly on the worker thread and eats the click.
            self.logger.error(f"Falha ao alterar inicialização automática: {e}")
            self.notify_error(
                f"Falha ao alterar início automático: {e}",
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
        self.enabled = False
        if self.listener:
            self.listener.stop()
        self.gui.stop()
        icon.stop()
    
    def run_keyboard_listener(self):
        """Run the keyboard listener in a separate thread."""
        self.listener = keyboard.Listener(on_press=self.on_press)
        self.listener.start()
        self.listener.join()
    
    def run(self):
        """Start the program with the system tray."""
        print("=" * 60)
        print("          TEXT EXPANDER - EXPANSOR DE SNIPPETS")
        print("=" * 60)
        
        if self.is_admin():
            print("\n✓ Executando como ADMINISTRADOR")
        else:
            print("\n⚠ Executando SEM privilégios de administrador")
            print("  Funcionará na maioria dos aplicativos comuns")
        
        print("\n📝 Snippets carregados (estáticos, não-callable):")
        static_count = 0
        for trigger, value in self.snippets.items():
            if trigger.startswith("_") or callable(value):
                continue
            static_count += 1
            if static_count <= 5:
                preview = extract_plain_text(value).replace("\n", " ")[:40]
                print(f"  • {trigger:15s} → {preview}")
        
        if static_count > 5:
            print(f"  ... e mais {static_count - 5} snippets estáticos")
        
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

        self.task_runner.start(self.run_keyboard_listener, name="keyboard-listener")

        menu = pystray.Menu(
            pystray.MenuItem(
                lambda text: f"{'✓' if self.enabled else '✗'} Ativado",
                self.toggle_enabled,
                checked=lambda item: self.enabled
            ),
            pystray.MenuItem(
                "⚠ Permissões do macOS",
                self.tray_macos_permissions,
                visible=self.macos_permissions_pending,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Gerenciar Snippets", self.manage_snippets_gui, default=True),
            pystray.MenuItem("Recarregar Snippets", self.reload_snippets),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Backup agora", self.tray_backup_now),
            pystray.MenuItem("Abrir pasta de dados", self.tray_open_data_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Iniciar com o sistema",
                self.toggle_autostart,
                checked=self.autostart_is_enabled,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                APP_DISPLAY_NAME,
                lambda icon, item: None,
                enabled=False,
            ),
            pystray.MenuItem("Sair", self.quit_app)
        )

        
        self.icon = pystray.Icon(
            "text_expander",
            self.load_tray_icon(),
            APP_DISPLAY_NAME,
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
    try:
        # -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    """Main entry point."""
    # Windows keeps its named mutex; other platforms use a PID lockfile.
    lock_path = None
    if IS_WINDOWS:
        acquired = acquire_single_instance_mutex()
    else:
        lock_path = os.path.join(ensure_data_dir(), "txt_xpander.lock")
        acquired = acquire_lockfile(lock_path)
    if not acquired:
        show_already_running_message()
        return

    set_dpi_awareness()
    try:
        expander = TextExpander()
        expander.run()
    finally:
        if lock_path is not None:
            release_lockfile(lock_path)


if __name__ == "__main__":
    main()
