"""
Txt Xpander - Windows system tray snippet expander.
Version: 2.7

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
import os
import sys
import shutil
import ctypes
import subprocess
import webbrowser

os.environ.setdefault("PYSTRAY_BACKEND", "win32")

from pynput import keyboard
from pynput.keyboard import Controller, Key
import pystray
from PIL import Image, ImageDraw, ImageFont

from bcb_consultor import BCBConsultor
from yf_stocks import B3FundamentosConsultor
from snippet_utils import (
    build_saveable_snippets,
    calculate_max_trigger_length,
    calculate_max_trigger_length_with_mappings,
    get_default_snippets as get_static_default_snippets,
    get_dynamic_prefixes,
    load_json_file,
    merge_snippets,
    validate_static_snippets,
    write_json_atomic,
    check_dynamic_pattern as resolve_dynamic_pattern,
)
from trigger_index import compile_trigger_index, find_direct_trigger, find_dynamic_trigger
from runtime_support import (
    AppLogger,
    BackgroundTaskRunner,
    TextInserter,
    WindowsClipboard,
    build_snippet_failure_notification,
    configure_logging,
    truncate_notification_text,
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
    has_form_variables,
    resolve_form_variables,
    resolve_inline,
)
from gui_support import (
    DATETIME_SNIPPETS,
    ECONOMY_SNIPPETS,
    STOCK_SNIPPETS,
    WHATSAPP_SNIPPETS,
    center_dialog,
    filter_static_snippets,
    iter_filtered_mapping_items,
)

# GUI for managing snippets
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog, font as tkfont


APP_MUTEX_NAME = r"Local\TxtXpanderSingleton"
APP_MUTEX_HANDLE = None
ERROR_ALREADY_EXISTS = 183
MB_ICONINFORMATION = 0x40


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
    ctypes.windll.user32.MessageBoxW(
        0,
        "Txt Xpander já está em execução.",
        "Txt Xpander",
        MB_ICONINFORMATION,
    )


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
        self.text_inserter = TextInserter(self.keyboard_controller, logger=self.logger)
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
        self.settings = load_settings(self.settings_file)
        configure_logging(self.logs_dir)
        self.migrate_legacy_data()
        self.ensure_seed_snippets_file(snippets_file)
        self.logger.info(f"➡ Diretório de dados: {self.data_dir}")
        self.logger.info(f"➡ Arquivo de snippets configurado para: {self.snippets_file}")
        self.backup_on_startup()

        # Initialize the B3/US stock data consultor
        self.b3_consultor = B3FundamentosConsultor(cache_seconds=600)
        
        # Stock snippets (slow: they prompt for a ticker and fetch data)
        self.slow_snippets = {
            "xcot", "xplucro", "xcap", "xpvp", "xdy",
            "xebt", "xmarg", "xroe", "xdivl", "xdivt",
            "xcaixa", "xvol", "xrec", "xbeta", "x52w",
            "xfund", "xwapp", "xlwapp", "xpwapp"
        }

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
        saveable = build_saveable_snippets(snippets)
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

    # =====================================================================
    # BACKUP / RESTORE / EXPORT / IMPORT
    # =====================================================================

    def reload_snippets_from_disk(self):
        """Reload the static library from disk and rebuild runtime indexes."""
        self.snippets = self.load_snippets()
        self.refresh_runtime_indexes(include_dynamic_items=True)

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
            merged = {**build_saveable_snippets(self.snippets), **data}
        else:
            merged = data

        try:
            write_json_atomic(self.snippets_file, merged)
        except Exception as e:
            return False, f"Falha ao importar: {e}"

        self.mirror_snippets_file()
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
    
    def ask_ticker_input(self, prompt_title: str):
        """
        Ask for the ticker using VBScript (native to Windows).
        Runs fine in a separate thread.
        """
        print(f"📊 Abrindo input para {prompt_title}...")
        
        try:
            # VBS script
            vbs_script = f'''userInput = InputBox("Digite o ticker:" & vbCrLf & "Ex: PETR4, AAPL, MSFT", "{prompt_title}", "")
If userInput <> "" Then WScript.Echo userInput'''

            # Try via mshta
            result = subprocess.run(
                ['mshta', 'vbscript:Execute("' + vbs_script.replace('"', '""') + '(Close)")'],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if not result.stdout.strip():
                # Fallback via VBS file + cscript
                vbs_file = os.path.join(os.environ.get('TEMP', '.'), 'txtexp_input.vbs')
                with open(vbs_file, 'w', encoding='utf-8') as f:
                    f.write(vbs_script)
                
                result = subprocess.run(
                    ['cscript', '//nologo', vbs_file],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                
                try:
                    os.remove(vbs_file)
                except Exception:
                    pass
            
            ticker = result.stdout.strip()
            
            if ticker:
                ticker = ticker.upper()
                print(f"✓ Ticker digitado: {ticker}")
                return ticker
            else:
                print("⚠ Cancelado ou vazio")
                return None
                
        except subprocess.TimeoutExpired:
            print("⚠ Timeout no dialog")
            return None
        except Exception as e:
            print(f"⚠ Erro no dialog: {e}")
            return None

    def ask_whatsapp_input(self, initial_phone: str = "", initial_message: str = ""):
        """Show a small modal dialog for manual WhatsApp phone/message input."""
        result = {"phone": None, "message": None}

        try:
            root = tk.Tk()
            root.title("Abrir WhatsApp")
            root.resizable(False, False)
            root.configure(bg="#F4F6FA")
            root.attributes("-topmost", True)
            root.grab_set()
            self._set_window_icon(root)

            container = tk.Frame(root, bg="#F4F6FA", padx=18, pady=18)
            container.pack(fill=tk.BOTH, expand=True)
            container.grid_columnconfigure(0, weight=1)

            tk.Label(
                container,
                text="Abrir conversa no WhatsApp",
                font=("Segoe UI", 11, "bold"),
                bg="#F4F6FA",
                fg="#1F2937",
            ).grid(row=0, column=0, sticky="w")

            tk.Label(
                container,
                text="Informe o telefone com DDD ou código do país. Se faltar o país, será usado +55.",
                font=("Segoe UI", 9),
                bg="#F4F6FA",
                fg="#5B6472",
                wraplength=380,
                justify=tk.LEFT,
            ).grid(row=1, column=0, sticky="w", pady=(6, 12))

            tk.Label(container, text="Telefone", font=("Segoe UI", 9), bg="#F4F6FA").grid(row=2, column=0, sticky="w")
            entry_phone = tk.Entry(container, font=("Segoe UI", 10), width=42)
            entry_phone.grid(row=3, column=0, sticky="ew", pady=(4, 10))
            if initial_phone:
                entry_phone.insert(0, initial_phone)

            tk.Label(container, text="Mensagem", font=("Segoe UI", 9), bg="#F4F6FA").grid(row=4, column=0, sticky="w")
            text_message = tk.Text(container, font=("Segoe UI", 10), width=42, height=5)
            text_message.grid(row=5, column=0, sticky="ew", pady=(4, 12))
            if initial_message:
                text_message.insert("1.0", initial_message)

            buttons = tk.Frame(container, bg="#F4F6FA")
            buttons.grid(row=6, column=0, sticky="e")

            def close_dialog():
                root.grab_release()
                root.destroy()

            def cancel_dialog():
                close_dialog()

            def submit_dialog(event=None):
                phone_text = entry_phone.get().strip()
                message_text = text_message.get("1.0", tk.END).rstrip("\n")
                normalized_phone = normalize_phone_number(phone_text)

                if not normalized_phone:
                    messagebox.showwarning(
                        "Telefone inválido",
                        "Informe um telefone com DDD ou código do país em um formato válido.",
                        parent=root,
                    )
                    entry_phone.focus_set()
                    return

                result["phone"] = normalized_phone
                result["message"] = message_text
                close_dialog()

            btn_cancel = tk.Button(buttons, text="Cancelar", width=12, command=cancel_dialog)
            btn_open = tk.Button(buttons, text="Abrir WhatsApp", width=14, command=submit_dialog)
            btn_cancel.pack(side=tk.LEFT, padx=(0, 6))
            btn_open.pack(side=tk.LEFT)

            entry_phone.bind("<Return>", submit_dialog)
            root.bind("<Escape>", lambda event: cancel_dialog())
            root.protocol("WM_DELETE_WINDOW", cancel_dialog)

            root.update_idletasks()
            width = root.winfo_reqwidth()
            height = root.winfo_reqheight()
            pos_x = (root.winfo_screenwidth() - width) // 2
            pos_y = (root.winfo_screenheight() - height) // 3
            root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
            entry_phone.focus_set()
            root.mainloop()
        except Exception as e:
            self.logger.error(f"Erro ao abrir diálogo do WhatsApp: {e}")
            self.notify_error(
                f"Erro ao abrir diálogo do WhatsApp: {e}",
                key="whatsapp-dialog-error",
                cooldown_seconds=5,
            )
            return None, None

        return result["phone"], result["message"]

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
        """Return dynamic snippets (date/time/BCB/stocks) that are not persisted to JSON."""
        bcb = BCBConsultor(timeout=3, cache_seconds=300)
        
        return {
            # Date and time - expand instantly
            "x-hj": lambda: time.strftime("%Y-%m-%d"),
            "xhj": lambda: time.strftime("%d/%m/%Y"),
            "xhoje": self.data_extenso,
            "xnow": lambda: time.strftime("%H:%M:%S"),
            "xdatahora": lambda: time.strftime("%d/%m/%Y às %H:%M"),
            
            # ceiling: BCB callables are not in slow_snippets, so they run on the keyboard
            # listener thread and block typing for up to ~15s on a cache miss; route them
            # through the background path (plan phase 3, audit 2.1).
            "xdolar": bcb.get_dolar,
            "xselic": bcb.get_selic_meta,
            "xipcam": bcb.get_ipca_mensal,
            "xipca12": bcb.get_ipca_12m,
            "xcdi": bcb.get_cdi,
            "xptax": bcb.get_ptax_sgs,
            "xeconomia": bcb.get_resumo_economico,
            
            # Stock snippets (treated as slow in the listener)
            "xcot": self.snippet_cotacao,
            "xplucro": self.snippet_preco_lucro,
            "xcap": self.snippet_market_cap,
            "xpvp": self.snippet_preco_vp,
            "xdy": self.snippet_dividend_yield,
            "xebt": self.snippet_ebitda,
            "xmarg": self.snippet_margem_liquida,
            "xroe": self.snippet_roe,
            "xdivl": self.snippet_divida_liquida,
            "xdivt": self.snippet_divida_total,
            "xcaixa": self.snippet_caixa,
            "xvol": self.snippet_volume_medio,
            "xrec": self.snippet_receita_liquida,
            "xbeta": self.snippet_beta,
            "x52w": self.snippet_52week,
            "xfund": self.snippet_resumo_fundamentos,
            "xwapp": self.snippet_whatsapp,
            "xlwapp": self.snippet_whatsapp_link,
            "xpwapp": self.snippet_whatsapp_prompt,
        }
    
    # =====================================================================
    # STOCK SNIPPETS (used by the slow path)
    # =====================================================================

    def snippet_cotacao(self):
        print("📊 Snippet xcot acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Cotação")
        if ticker:
            print(f"🔍 Buscando cotação para {ticker}...")
            result = self.b3_consultor.get_cotacao_atual(ticker)
            print(f"✓ Resultado: {result}")
            return result
        return "[Cancelado]"
    
    def snippet_preco_lucro(self):
        print("📊 Snippet xplucro acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("P/L")
        if ticker:
            return self.b3_consultor.get_preco_lucro(ticker)
        return "[Cancelado]"
    
    def snippet_market_cap(self):
        print("📊 Snippet xcap acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Market Cap")
        if ticker:
            return self.b3_consultor.get_market_cap(ticker)
        return "[Cancelado]"
    
    def snippet_preco_vp(self):
        print("📊 Snippet xpvp acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("P/VP")
        if ticker:
            return self.b3_consultor.get_preco_vp(ticker)
        return "[Cancelado]"
    
    def snippet_dividend_yield(self):
        print("📊 Snippet xdy acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Dividend Yield")
        if ticker:
            return self.b3_consultor.get_dividend_yield(ticker)
        return "[Cancelado]"
    
    def snippet_ebitda(self):
        print("📊 Snippet xebt acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("EBITDA")
        if ticker:
            return self.b3_consultor.get_ebitda(ticker)
        return "[Cancelado]"
    
    def snippet_margem_liquida(self):
        print("📊 Snippet xmarg acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Margem Líquida")
        if ticker:
            return self.b3_consultor.get_margem_liquida(ticker)
        return "[Cancelado]"
    
    def snippet_roe(self):
        print("📊 Snippet xroe acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("ROE")
        if ticker:
            return self.b3_consultor.get_roe(ticker)
        return "[Cancelado]"
    
    def snippet_divida_liquida(self):
        print("📊 Snippet xdiv acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Dívida Líquida")
        if ticker:
            result = self.b3_consultor.get_divida_liquida(ticker)
            return result
        return "[Cancelado]"

    def snippet_divida_total(self):
        print("📊 Snippet xdivt acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Dívida Total")
        if ticker:
            result = self.b3_consultor.get_divida_total(ticker)
            return result
        return "[Cancelado]"

    def snippet_caixa(self):
        print("📊 Snippet xcaixa acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Caixa")
        if ticker:
            result = self.b3_consultor.get_caixa(ticker)
            return result
        return "[Cancelado]"
    
    def snippet_volume_medio(self):
        print("📊 Snippet xvol acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Volume Médio")
        if ticker:
            return self.b3_consultor.get_volume_medio(ticker)
        return "[Cancelado]"
    
    def snippet_receita_liquida(self):
        ticker = self.ask_ticker_input("Receita Líquida")
        return self.b3_consultor.get_receita_liquida(ticker) if ticker else "[Cancelado]"

    def snippet_beta(self):
        ticker = self.ask_ticker_input("Beta")
        return self.b3_consultor.get_beta(ticker) if ticker else "[Cancelado]"

    def snippet_52week(self):
        ticker = self.ask_ticker_input("52 Semanas High/Low")
        return self.b3_consultor.get_52week_high_low(ticker) if ticker else "[Cancelado]"
    
    def snippet_resumo_fundamentos(self):
        print("📊 Snippet xfund acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Resumo de Fundamentos")
        if ticker:
            print(f"🔍 Buscando resumo para {ticker}...")
            return self.b3_consultor.get_resumo_fundamentos(ticker)
        return "[Cancelado]"

    def run_whatsapp_action(self, trigger: str):
        """Execute one of the built-in WhatsApp actions."""
        return execute_whatsapp_action(
            trigger,
            get_clipboard_text=WindowsClipboard.get_text,
            ask_input=self.ask_whatsapp_input,
            set_clipboard_content=WindowsClipboard.set_content,
            open_url=self.open_url_in_browser,
            notify_error=self.notify_error,
        )

    def snippet_whatsapp(self):
        """Generate a WhatsApp wa.me link from clipboard or manual input and open it."""
        return self.run_whatsapp_action("xwapp")

    def snippet_whatsapp_link(self):
        """Generate a WhatsApp wa.me link from clipboard or manual input and insert it."""
        return self.run_whatsapp_action("xlwapp")

    def snippet_whatsapp_prompt(self):
        """Prompt immediately for WhatsApp phone/message input, then open the link."""
        return self.run_whatsapp_action("xpwapp")

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
        """
        Expand the snippet matching the trigger.
        Used for "normal" (non-slow) snippets.
        """
        if not self.enabled:
            return False
        
        # Slow snippets are not run here (they go through the thread path)
        if trigger in self.slow_snippets:
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
            resolved_text = resolve_inline(plain_text, self.snippets, WindowsClipboard.get_text, _seen={trigger})
            if resolved_text != plain_text:
                if is_rich_text_payload(snippet):
                    snippet = rebuild_rich_text(snippet, resolved_text)
                else:
                    snippet = resolved_text

            try:
                for _ in range(len(trigger)):
                    self.keyboard_controller.press(Key.backspace)
                    self.keyboard_controller.release(Key.backspace)
                    time.sleep(0.01)

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
        Also handles static snippets with form-fill variables (%%campo%%).
        """
        try:
            func = self.snippets.get(trigger)
            if not callable(func):
                # Static snippet routed here because it has form-fill variables.
                raw = func
                plain = extract_plain_text(raw)
                plain = resolve_inline(plain, self.snippets, WindowsClipboard.get_text, _seen={trigger})
                form_names = [
                    n for n in find_variable_names(plain)
                    if classify_variable(n, self.snippets) == "form_field"
                ]
                form_data = {}
                if form_names:
                    form_data = self._show_form_dialog(form_names)
                    if form_data is None:
                        return  # user cancelled — nothing inserted
                result = resolve_form_variables(plain, form_data)
                if is_rich_text_payload(raw):
                    result = rebuild_rich_text(raw, result)
                time.sleep(0.05)
                self.text_inserter.insert_text(result)
                return

            result = func()
            if not result:
                return
            self.notify_snippet_failure(trigger, result)
            time.sleep(0.05)
            self.text_inserter.insert_text(result)
            if trigger == "xlwapp":
                WindowsClipboard.set_content(result)
        except Exception as e:
            self.logger.error(f"Erro ao executar snippet lento {trigger}: {e}")
            self.notify_error(
                f"Falha ao executar snippet {trigger}: {e}",
                key=f"slow-snippet-error:{trigger}",
                cooldown_seconds=5,
            )
    
    def _show_form_dialog(self, field_names):
        """
        Show a modal dialog for form-fill variables.
        Called from a background thread — creates its own Tk root.
        Returns {field_name: value} or None if the user cancels.
        """
        result = [None]
        entries = {}

        dialog_root = tk.Tk()
        dialog_root.title("Preencher campos")
        dialog_root.resizable(False, False)
        dialog_root.configure(bg="#F4F6FA")
        self._set_window_icon(dialog_root)

        tk.Label(
            dialog_root,
            text="Preencha os campos do snippet:",
            font=("Segoe UI", 9, "bold"),
            bg="#F4F6FA",
            fg="#1F2937",
        ).pack(padx=20, pady=(16, 8), anchor="w")

        frame = tk.Frame(dialog_root, bg="#F4F6FA")
        frame.pack(fill=tk.BOTH, padx=20, pady=(0, 8))
        frame.grid_columnconfigure(0, weight=1)

        first_entry = None
        for i, name in enumerate(field_names):
            label_text = name.replace("_", " ").title()
            tk.Label(
                frame,
                text=label_text + ":",
                font=("Segoe UI", 9),
                bg="#F4F6FA",
                fg="#374151",
            ).grid(row=i * 2, column=0, sticky="w", pady=(6, 0))
            entry = tk.Entry(
                frame,
                font=("Segoe UI", 10),
                width=42,
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground="#D7DEE8",
            )
            entry.grid(row=i * 2 + 1, column=0, sticky="ew", pady=(2, 0))
            entries[name] = entry
            if first_entry is None:
                first_entry = entry

        btn_frame = tk.Frame(dialog_root, bg="#F4F6FA")
        btn_frame.pack(fill=tk.X, padx=20, pady=(12, 16))

        def on_ok(_event=None):
            result[0] = {name: entries[name].get() for name in field_names}
            dialog_root.destroy()

        def on_cancel(_event=None):
            dialog_root.destroy()  # result[0] stays None

        tk.Button(
            btn_frame,
            text="Cancelar",
            font=("Segoe UI", 9),
            width=10,
            command=on_cancel,
            relief=tk.FLAT,
            bg="#E7ECF5",
            activebackground="#D9E2F2",
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(
            btn_frame,
            text="OK",
            font=("Segoe UI", 9),
            width=10,
            command=on_ok,
            relief=tk.FLAT,
            bg="#265CFF",
            fg="white",
            activebackground="#1a4fd4",
            activeforeground="white",
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        dialog_root.bind("<Return>", on_ok)
        dialog_root.bind("<Escape>", on_cancel)

        dialog_root.update_idletasks()
        w = dialog_root.winfo_reqwidth()
        h = dialog_root.winfo_reqheight()
        sw = dialog_root.winfo_screenwidth()
        sh = dialog_root.winfo_screenheight()
        dialog_root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

        dialog_root.lift()
        dialog_root.focus_force()
        if first_entry:
            first_entry.focus_set()

        dialog_root.mainloop()
        return result[0]

    def rebuild_trigger_index(self):
        """Rebuild compiled trigger metadata after snippet changes."""
        self.trigger_index = compile_trigger_index(self.snippets, self.slow_snippets)

    def refresh_runtime_indexes(self, include_dynamic_items: bool = False):
        """Refresh max trigger length and compiled trigger metadata."""
        if include_dynamic_items:
            self.max_trigger_length = calculate_max_trigger_length_with_mappings(self.snippets)
        else:
            self.max_trigger_length = calculate_max_trigger_length(self.snippets)
        self.rebuild_trigger_index()

    def notify(self, message: str, title: str = "Text Expander", key: str = None, cooldown_seconds: float = 0, kind: str = "info"):
        """Send a tray notification when the icon is available, with optional cooldown."""
        if not self.icon:
            return False

        if key:
            now = time.time()
            last_sent = self.notification_timestamps.get(key, 0)
            if (now - last_sent) < cooldown_seconds:
                return False
            self.notification_timestamps[key] = now

        text = truncate_notification_text(message)
        self.notification_history.append(
            {
                "time": time.strftime("%H:%M:%S"),
                "title": title,
                "message": text,
                "kind": kind,
            }
        )
        if len(self.notification_history) > 120:
            self.notification_history = self.notification_history[-120:]

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
        """Callback invoked when a key is pressed."""
        try:
            if hasattr(key, 'char') and key.char:
                self.typed_text += key.char
                
                if len(self.typed_text) > self.max_trigger_length:
                    self.typed_text = self.typed_text[-self.max_trigger_length:]
                
                expanded = False

                # 1) Direct snippets
                trigger = find_direct_trigger(self.typed_text, self.trigger_index)
                if trigger:
                    needs_slow = trigger in self.slow_snippets
                    if not needs_slow:
                        raw_value = self.snippets.get(trigger)
                        if not callable(raw_value):
                            if has_form_variables(extract_plain_text(raw_value), self.snippets):
                                needs_slow = True
                    if needs_slow:
                        for _ in range(len(trigger)):
                            self.keyboard_controller.press(Key.backspace)
                            self.keyboard_controller.release(Key.backspace)
                            time.sleep(0.01)
                        self.typed_text = ""
                        self.task_runner.start(self.run_slow_snippet, trigger, name="slow-snippet")
                        expanded = True
                    else:
                        self.expand_snippet(trigger)
                        self.typed_text = ""
                        expanded = True
                
                # 2) Dynamic patterns (including custom prefixes)
                if not expanded:
                    potential_trigger, result = find_dynamic_trigger(self.snippets, self.typed_text, self.trigger_index)
                    if result is not None:
                        self.expand_snippet(potential_trigger)
                        self.typed_text = ""
                                
        except AttributeError:
            if key == Key.enter:
                self.typed_text = ""
            elif key == Key.backspace and self.typed_text:
                self.typed_text = self.typed_text[:-1]

    # =====================================================================
    # SNIPPET MANAGEMENT GUI
    # =====================================================================

    def manage_snippets_gui(self, icon, item):
        """Open the full GUI for managing static snippets and dynamic mappings."""
        hwnd = ctypes.windll.user32.FindWindowW(None, "Txt Xpander - Gerenciador de Snippets")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return
        self.task_runner.start(self._manage_snippets_gui_thread, name="manage-snippets-gui")

    def _manage_snippets_gui_thread(self):
        """Thread that runs the full management tkinter window."""
        try:
            root = tk.Tk()
            root.title("Txt Xpander - Gerenciador de Snippets")
            root.geometry("960x660")
            root.minsize(820, 540)
            root.resizable(True, True)
            root.configure(bg="#F4F6FA")
            self._set_window_icon(root)
            self._configure_manager_styles(root)

            root.grid_columnconfigure(0, weight=1)
            root.grid_rowconfigure(1, weight=1)

            header = tk.Frame(root, bg="#F4F6FA", padx=12, pady=10)
            header.grid(row=0, column=0, sticky="ew")
            header.grid_columnconfigure(0, weight=1)

            tk.Label(
                header,
                text="Gerenciador de Snippets",
                font=("Segoe UI", 12, "bold"),
                bg="#F4F6FA",
                fg="#1F2937",
            ).grid(row=0, column=0, sticky="w")
            tk.Label(
                header,
                text="Edite snippets, mapeamentos e consulte notificações recentes.",
                font=("Segoe UI", 9),
                bg="#F4F6FA",
                fg="#5B6472",
            ).grid(row=1, column=0, sticky="w", pady=(2, 0))

            bell_button = tk.Button(
                header,
                text="🔔",
                font=("Segoe UI Emoji", 12),
                width=3,
                relief=tk.FLAT,
                bd=0,
                bg="#E7ECF5",
                activebackground="#D9E2F2",
                cursor="hand2",
                command=lambda: self._open_notification_history(root),
            )
            bell_button.grid(row=0, column=1, rowspan=2, sticky="e")

            notebook = ttk.Notebook(root, style="Manager.TNotebook")
            notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

            tab_static = tk.Frame(notebook, bg="#F4F6FA")
            notebook.add(tab_static, text="Snippets Estáticos")

            tab_dynamic = tk.Frame(notebook, bg="#F4F6FA")
            notebook.add(tab_dynamic, text="Mapeamentos Dinâmicos")

            tab_datetime_eco = tk.Frame(notebook, bg="#F4F6FA")
            notebook.add(tab_datetime_eco, text="Data/Hora & Economia")

            tab_stocks = tk.Frame(notebook, bg="#F4F6FA")
            notebook.add(tab_stocks, text="Ações (Stocks)")

            tab_whatsapp = tk.Frame(notebook, bg="#F4F6FA")
            notebook.add(tab_whatsapp, text="WhatsApp")

            tab_backups = tk.Frame(notebook, bg="#F4F6FA")
            notebook.add(tab_backups, text="Backups")

            self._create_static_snippets_tab(tab_static, root)
            self._create_dynamic_mappings_tab(tab_dynamic, root)
            self._create_datetime_eco_tab(tab_datetime_eco)
            self._create_stocks_tab(tab_stocks)
            self._create_whatsapp_tab(tab_whatsapp)
            self._create_backups_tab(tab_backups, root)

            root.mainloop()

        except Exception as e:
            self.logger.error(f"Erro na GUI de gerenciamento: {e}")
            self.notify_error(
                f"Erro ao abrir gerenciador: {e}",
                key="gui-open-error",
                cooldown_seconds=5,
            )

    def _create_backups_tab(self, parent, root):
        """Backups tab: list backups and expose restore/export/import actions."""
        main = tk.Frame(parent, bg="#F4F6FA", padx=14, pady=14)
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        tk.Label(
            main,
            text="Backups da biblioteca",
            font=("Segoe UI", 11, "bold"),
            bg="#F4F6FA",
            fg="#1F2937",
        ).grid(row=0, column=0, sticky="w")
        path_label = tk.Label(
            main,
            text=f"Pasta de dados: {self.data_dir}",
            font=("Segoe UI", 8),
            bg="#F4F6FA",
            fg="#5B6472",
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
            else:
                messagebox.showerror("Backups", f"Falha ao importar: {error}", parent=root)

        def on_backup_now():
            created = self.backup_now()
            if created:
                messagebox.showinfo("Backups", f"Backup criado: {os.path.basename(created)}", parent=root)
                refresh_backups()
            else:
                messagebox.showerror("Backups", "Falha ao criar backup. Verifique os logs.", parent=root)

        buttons = tk.Frame(main, bg="#F4F6FA")
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        tk.Button(buttons, text="Backup agora", width=14, command=on_backup_now).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(buttons, text="Restaurar", width=12, command=on_restore).pack(side=tk.LEFT, padx=6)
        tk.Button(buttons, text="Exportar…", width=12, command=on_export).pack(side=tk.LEFT, padx=6)
        tk.Button(buttons, text="Importar…", width=12, command=on_import).pack(side=tk.LEFT, padx=6)
        tk.Button(buttons, text="Abrir pasta", width=12, command=self.open_data_folder).pack(side=tk.LEFT, padx=6)
        tk.Button(buttons, text="Atualizar", width=10, command=refresh_backups).pack(side=tk.RIGHT)

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
        style = ttk.Style(root)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Manager.TNotebook", background="#F4F6FA", borderwidth=0)
        style.configure("Manager.TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 9))
        style.map(
            "Manager.TNotebook.Tab",
            background=[("selected", "#FFFFFF"), ("!selected", "#E7ECF5")],
            foreground=[("selected", "#1F2937"), ("!selected", "#2F3A4A")],
        )

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
        history_window = tk.Toplevel(root)
        history_window.title("Histórico de Notificações")
        history_window.geometry("680x360")
        history_window.minsize(560, 280)
        history_window.configure(bg="#F4F6FA")
        history_window.transient(root)
        self._set_window_icon(history_window)

        outer = tk.Frame(history_window, bg="#F4F6FA", padx=14, pady=14)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        tk.Label(
            outer,
            text="Últimas notificações",
            font=("Segoe UI", 11, "bold"),
            bg="#F4F6FA",
            fg="#1F2937",
        ).grid(row=0, column=0, sticky="w")

        frame = tk.Frame(outer, bg="#FFFFFF", highlightbackground="#D7DEE8", highlightthickness=1)
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

        toolbar = tk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=(0, 6))

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
        icon_fonts["code"].configure(family="Consolas", weight="bold", size=max(9, button_base_font.cget("size") - 1))
        icon_fonts["strike"].configure(overstrike=1)
        icon_fonts["clear"].configure(family="Segoe UI Symbol", size=max(10, button_base_font.cget("size")))
        icon_fonts["var"] = button_base_font.copy()
        icon_fonts["var"].configure(family="Consolas", size=max(8, button_base_font.cget("size") - 1))

        toolbar_bg = toolbar.cget("bg")

        def add_toolbar_button(label, handler, width, padx, tooltip, font_key):
            button = tk.Button(
                toolbar,
                text=label,
                width=width,
                takefocus=0,
                font=icon_fonts[font_key],
                relief=tk.FLAT,
                bd=0,
                padx=0,
                pady=0,
                bg=toolbar_bg,
                activebackground="#E6E9EF",
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

        add_toolbar_button("B", lambda: apply_style("bold"), 2, (0, 3), "Formato: negrito", "bold")
        add_toolbar_button("I", lambda: apply_style("italic"), 2, 3, "Formato: itálico", "italic")
        add_toolbar_button("U", lambda: apply_style("underline"), 2, 3, "Formato: sublinhado", "underline")
        add_toolbar_button("S", lambda: apply_style("strike"), 2, 3, "Formato: tachado", "strike")
        add_toolbar_button("<>", lambda: apply_style("code"), 3, 6, "Formato: código monoespaçado", "code")
        add_toolbar_button("⌫", clear_styles_handler, 2, 3, "Formato: limpar estilos", "clear")

        # Separator before variable buttons
        tk.Frame(toolbar, width=1, bg="#C8CDD6").pack(side=tk.LEFT, padx=(8, 6), fill=tk.Y, pady=2)

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

            search_var = tk.StringVar()
            tk.Entry(
                picker, textvariable=search_var, font=("Segoe UI", 10),
                relief=tk.FLAT, highlightthickness=1, highlightbackground="#D7DEE8",
            ).pack(fill=tk.X, padx=8, pady=8)

            lf = tk.Frame(picker)
            lf.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
            lf.grid_columnconfigure(0, weight=1)
            lf.grid_rowconfigure(0, weight=1)

            listbox = tk.Listbox(lf, font=("Segoe UI", 10), selectmode=tk.SINGLE,
                                 relief=tk.FLAT, borderwidth=0, activestyle="none")
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
                      font=("Segoe UI", 9), relief=tk.FLAT,
                      bg="#265CFF", fg="white",
                      activebackground="#1a4fd4", activeforeground="white",
                      cursor="hand2").pack(pady=(0, 8))

            center_dialog(picker, parent_win)
            picker.focus_set()

        def insert_snippet_ref():
            choices = sorted([
                k for k, v in self.snippets.items()
                if not k.startswith("_") and not callable(v)
            ])
            if not choices:
                messagebox.showinfo("Variáveis", "Nenhum snippet estático disponível.",
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

        tk.Label(toolbar, textvariable=status_var, font=("Arial", 8), fg="#555").pack(side=tk.RIGHT)

        bind_shortcut("<Control-b>", "bold")
        bind_shortcut("<Control-i>", "italic")
        bind_shortcut("<Control-u>", "underline")
        text_widget.bind("<Control-Shift-C>", lambda event: (apply_style("code"), "break")[1])
        text_widget.bind("<Control-Shift-S>", lambda event: (apply_style("strike"), "break")[1])
        text_widget.bind("<KeyRelease>", update_status)
        text_widget.bind("<ButtonRelease-1>", update_status)
        update_status()
        return update_status
    def _create_static_snippets_tab(self, parent, root):
        """Build the static snippets tab UI."""

        main = tk.Frame(parent, bg="#F4F6FA", padx=14, pady=14)
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        frame_left = tk.LabelFrame(main, text="Biblioteca de snippets", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", padx=12, pady=12)
        frame_left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        frame_left.grid_columnconfigure(0, weight=1)
        frame_left.grid_rowconfigure(2, weight=1)

        search_var = tk.StringVar()
        tk.Label(frame_left, text="Buscar", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=0, column=0, sticky="w")
        search_entry = tk.Entry(frame_left, textvariable=search_var, font=("Segoe UI", 9), relief=tk.FLAT, highlightthickness=1, highlightbackground="#D7DEE8")
        search_entry.grid(row=1, column=0, sticky="ew", pady=(4, 10))

        listbox_shell = tk.Frame(frame_left, bg="#FFFFFF", highlightbackground="#D7DEE8", highlightthickness=1)
        listbox_shell.grid(row=2, column=0, sticky="nsew")
        listbox_shell.grid_columnconfigure(0, weight=1)
        listbox_shell.grid_rowconfigure(0, weight=1)

        listbox = tk.Listbox(listbox_shell, font=("Segoe UI", 10), relief=tk.FLAT, borderwidth=0, activestyle="none", selectborderwidth=0)
        scrollbar = tk.Scrollbar(listbox_shell, orient=tk.VERTICAL, command=listbox.yview)
        listbox.config(yscrollcommand=scrollbar.set)
        listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        frame_right = tk.LabelFrame(main, text="Editor de snippet", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", padx=12, pady=12)
        frame_right.grid(row=0, column=1, sticky="nsew")
        frame_right.grid_columnconfigure(0, weight=1)
        frame_right.grid_rowconfigure(3, weight=1)

        tk.Label(frame_right, text="Trigger", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=0, column=0, sticky="w")
        entry_trigger = tk.Entry(frame_right, font=("Segoe UI", 10), relief=tk.FLAT, highlightthickness=1, highlightbackground="#D7DEE8")
        entry_trigger.grid(row=1, column=0, sticky="ew", pady=(4, 10))

        tk.Label(frame_right, text="Valor do snippet", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=2, column=0, sticky="w")
        editor_shell = tk.Frame(frame_right, bg="#FFFFFF")
        editor_shell.grid(row=3, column=0, sticky="nsew")
        editor_shell.grid_columnconfigure(0, weight=1)
        editor_shell.grid_rowconfigure(1, weight=1)

        text_value = tk.Text(editor_shell, wrap=tk.WORD, font=("Segoe UI", 10), relief=tk.FLAT, highlightthickness=1, highlightbackground="#D7DEE8")
        update_format_status = self._create_formatting_toolbar(editor_shell, text_value)
        text_value.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        tk.Label(
            frame_right,
            text="Texto simples continua funcionando igual. Formatação é opcional.",
            font=("Segoe UI", 8),
            fg="#5B6472",
            bg="#FFFFFF",
        ).grid(row=4, column=0, sticky="w", pady=(2, 10))

        btn_frame = tk.Frame(frame_right, bg="#FFFFFF")
        btn_frame.grid(row=5, column=0, sticky="e")
        btn_new = tk.Button(btn_frame, text="Novo", width=12)
        btn_save = tk.Button(btn_frame, text="Salvar", width=12)
        btn_delete = tk.Button(btn_frame, text="Excluir", width=12)
        btn_new.pack(side=tk.LEFT, padx=(0, 6))
        btn_save.pack(side=tk.LEFT, padx=6)
        btn_delete.pack(side=tk.LEFT, padx=(6, 0))

        self._bind_mousewheel(listbox, listbox)
        self._bind_mousewheel(text_value, text_value)

        def get_static_visible_snippets():
            return filter_static_snippets(self.snippets, search_var.get())

        static_snips = get_static_visible_snippets()

        def refresh_listbox():
            listbox.delete(0, tk.END)
            static_snips.clear()
            static_snips.update(get_static_visible_snippets())
            for key in sorted(static_snips.keys()):
                listbox.insert(tk.END, key)

        def load_selected(event=None):
            selection = listbox.curselection()
            if not selection:
                return
            key = listbox.get(selection[0])
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

            self.snippets[trigger] = value
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

            if trigger in self.snippets and messagebox.askyesno("Confirmar", f"Excluir '{trigger}'?"):
                del self.snippets[trigger]
                if not self.save_snippets(self.snippets):
                    messagebox.showerror(
                        "Erro ao salvar",
                        "Não foi possível gravar snippets.json. Verifique os logs; a exclusão pode não ter sido salva.",
                    )
                    return
                self.refresh_runtime_indexes()
                entry_trigger.delete(0, tk.END)
                load_value_into_text_widget(text_value, "")
                update_format_status()
                refresh_listbox()
                self.notify_status(f"Snippet '{trigger}' excluído.", key=f"delete-static:{trigger}")

        listbox.bind("<<ListboxSelect>>", load_selected)
        btn_new.configure(command=on_new)
        btn_save.configure(command=on_save)
        btn_delete.configure(command=on_delete)
        search_var.trace_add("write", lambda *_: refresh_listbox())

        refresh_listbox()
        search_entry.focus_set()

    def _create_dynamic_mappings_tab(self, parent, root):
        """Build the dynamic mappings UI with customizable types."""

        main = tk.Frame(parent, bg="#F4F6FA", padx=14, pady=14)
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        frame_types = tk.LabelFrame(main, text="Tipos de mapeamento", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", padx=12, pady=12)
        frame_types.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        types_inner = tk.Frame(frame_types, bg="#FFFFFF")
        types_inner.pack(fill=tk.X)
        types_inner.grid_columnconfigure(1, weight=1)

        tk.Label(types_inner, text="Tipos disponíveis", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=0, column=0, sticky="w", padx=(0, 10))

        mapping_type = tk.StringVar(value="_cpf_numbers")
        rb_frame = tk.Frame(types_inner, bg="#FFFFFF")
        rb_frame.grid(row=0, column=1, sticky="w")

        btn_types_frame = tk.Frame(types_inner, bg="#FFFFFF")
        btn_types_frame.grid(row=0, column=2, sticky="e")
        rb_widgets = []

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

        def refresh_type_radiobuttons():
            nonlocal mappings_info
            for widget in rb_widgets:
                widget.destroy()
            rb_widgets.clear()

            mappings_info = get_mappings_info()
            available_keys = list(mappings_info.keys())
            if mapping_type.get() not in available_keys and available_keys:
                mapping_type.set(available_keys[0])

            for key, info in sorted(mappings_info.items(), key=lambda item: (not item[1]["builtin"], item[1]["label"])):
                rb = tk.Radiobutton(rb_frame, text=info["label"], variable=mapping_type, value=key, font=("Segoe UI", 9), bg="#FFFFFF")
                rb.pack(side=tk.LEFT, padx=(0, 10))
                rb_widgets.append(rb)
            update_example_label()

        def ensure_mapping_dict(current_type):
            mapping = self.snippets.get(current_type)
            if not isinstance(mapping, dict):
                mapping = {}
                self.snippets[current_type] = mapping
            return mapping

        lbl_example = tk.Label(main, text="", font=("Segoe UI", 8), fg="#5B6472", bg="#F4F6FA")
        lbl_example.grid(row=1, column=0, sticky="w", pady=(0, 10))

        content = tk.Frame(main, bg="#F4F6FA")
        content.grid(row=2, column=0, sticky="nsew")
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        frame_left = tk.LabelFrame(content, text="Itens do mapeamento", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", padx=12, pady=12)
        frame_left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        frame_left.grid_columnconfigure(0, weight=1)
        frame_left.grid_rowconfigure(2, weight=1)

        map_search_var = tk.StringVar()
        tk.Label(frame_left, text="Buscar", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=0, column=0, sticky="w")
        tk.Entry(frame_left, textvariable=map_search_var, font=("Segoe UI", 9), relief=tk.FLAT, highlightthickness=1, highlightbackground="#D7DEE8").grid(row=1, column=0, sticky="ew", pady=(4, 10))

        listbox_frame = tk.Frame(frame_left, bg="#FFFFFF", highlightbackground="#D7DEE8", highlightthickness=1)
        listbox_frame.grid(row=2, column=0, sticky="nsew")
        listbox_frame.grid_columnconfigure(0, weight=1)
        listbox_frame.grid_rowconfigure(0, weight=1)

        listbox_map = tk.Listbox(listbox_frame, font=("Segoe UI", 10), relief=tk.FLAT, borderwidth=0, activestyle="none")
        scrollbar_map = tk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=listbox_map.yview)
        listbox_map.config(yscrollcommand=scrollbar_map.set)
        listbox_map.grid(row=0, column=0, sticky="nsew")
        scrollbar_map.grid(row=0, column=1, sticky="ns")

        frame_right = tk.LabelFrame(content, text="Editor do item", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", padx=12, pady=12)
        frame_right.grid(row=0, column=1, sticky="nsew")
        frame_right.grid_columnconfigure(0, weight=1)
        frame_right.grid_rowconfigure(3, weight=1)

        tk.Label(frame_right, text="Identificador", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=0, column=0, sticky="w")
        entry_name = tk.Entry(frame_right, font=("Segoe UI", 10), relief=tk.FLAT, highlightthickness=1, highlightbackground="#D7DEE8")
        entry_name.grid(row=1, column=0, sticky="ew", pady=(4, 10))

        tk.Label(frame_right, text="Valor", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=2, column=0, sticky="w")
        editor_shell = tk.Frame(frame_right, bg="#FFFFFF")
        editor_shell.grid(row=3, column=0, sticky="nsew")
        editor_shell.grid_columnconfigure(0, weight=1)
        editor_shell.grid_rowconfigure(1, weight=1)

        text_value = tk.Text(editor_shell, wrap=tk.WORD, font=("Segoe UI", 10), relief=tk.FLAT, highlightthickness=1, highlightbackground="#D7DEE8")
        update_format_status = self._create_formatting_toolbar(editor_shell, text_value)
        text_value.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        tk.Label(
            frame_right,
            text="Mapeamentos também aceitam formatação opcional.",
            font=("Segoe UI", 8),
            fg="#5B6472",
            bg="#FFFFFF",
        ).grid(row=4, column=0, sticky="w", pady=(2, 10))

        btn_frame = tk.Frame(frame_right, bg="#FFFFFF")
        btn_frame.grid(row=5, column=0, sticky="e")
        btn_new_map = tk.Button(btn_frame, text="Novo", width=12)
        btn_save_map = tk.Button(btn_frame, text="Salvar", width=12)
        btn_delete_map = tk.Button(btn_frame, text="Excluir", width=12)
        btn_new_map.pack(side=tk.LEFT, padx=(0, 6))
        btn_save_map.pack(side=tk.LEFT, padx=6)
        btn_delete_map.pack(side=tk.LEFT, padx=(6, 0))

        def refresh_mapping_list():
            listbox_map.delete(0, tk.END)
            current_type = mapping_type.get()
            query = map_search_var.get()
            mapping = self.snippets.get(current_type, {})
            for key in iter_filtered_mapping_items(mapping, query):
                listbox_map.insert(tk.END, key)
            update_example_label()

        def add_new_type():
            dialog = tk.Toplevel(root)
            dialog.title("Novo Tipo de Mapeamento")
            dialog.resizable(False, False)
            dialog.transient(root)
            dialog.grab_set()
            dialog.configure(bg="#F4F6FA")
            self._set_window_icon(dialog)

            body = tk.Frame(dialog, bg="#F4F6FA", padx=18, pady=18)
            body.pack(fill=tk.BOTH, expand=True)
            tk.Label(body, text="Criar novo tipo de mapeamento dinâmico", font=("Segoe UI", 10, "bold"), bg="#F4F6FA").pack(anchor="w")
            tk.Label(body, text="Nome do tipo", font=("Segoe UI", 9), bg="#F4F6FA").pack(anchor="w", pady=(12, 0))
            entry_type_name = tk.Entry(body, font=("Segoe UI", 10))
            entry_type_name.pack(fill=tk.X, pady=(4, 8))
            tk.Label(body, text="Prefixo usado no trigger", font=("Segoe UI", 9), bg="#F4F6FA").pack(anchor="w")
            entry_prefix = tk.Entry(body, font=("Segoe UI", 10))
            entry_prefix.pack(fill=tk.X, pady=(4, 8))
            tk.Label(body, text="Ex.: tipo 'email' + prefixo 'mail' -> mailtrabalho", font=("Segoe UI", 8), fg="#5B6472", bg="#F4F6FA").pack(anchor="w")

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
                self.refresh_runtime_indexes(include_dynamic_items=True)
                refresh_type_radiobuttons()
                mapping_type.set(map_key)
                on_type_changed()
                self.notify_status(f"Tipo '{type_name}' criado.", key=f"mapping-type-create:{type_name}")
                dialog.destroy()

            tk.Button(body, text="Criar Tipo", command=save_new_type, width=15).pack(anchor="e", pady=(14, 0))
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
            self.refresh_runtime_indexes(include_dynamic_items=True)

            refresh_type_radiobuttons()
            available_keys = list(mappings_info.keys())
            if available_keys:
                mapping_type.set(available_keys[0])
            entry_name.delete(0, tk.END)
            load_value_into_text_widget(text_value, "")
            update_format_status()
            refresh_mapping_list()
            self.notify_status(f"Tipo '{info.get('label', current_type)}' excluído.", key=f"mapping-type-delete:{current_type}")

        tk.Button(btn_types_frame, text="Novo Tipo", width=12, command=add_new_type).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_types_frame, text="Excluir Tipo", width=12, command=delete_current_type).pack(side=tk.LEFT)

        self._bind_mousewheel(listbox_map, listbox_map)
        self._bind_mousewheel(text_value, text_value)

        def load_selected_mapping(event=None):
            selection = listbox_map.curselection()
            if not selection:
                return

            current_type = mapping_type.get()
            key = listbox_map.get(selection[0])
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
            self.refresh_runtime_indexes(include_dynamic_items=True)
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
                self.refresh_runtime_indexes(include_dynamic_items=True)
                entry_name.delete(0, tk.END)
                load_value_into_text_widget(text_value, "")
                update_format_status()
                refresh_mapping_list()
                self.notify_status(f"Item '{name}' excluído.", key=f"delete-map:{current_type}:{name}")

        refresh_type_radiobuttons()
        mapping_type.trace_add("write", lambda *_: on_type_changed())
        listbox_map.bind("<<ListboxSelect>>", load_selected_mapping)
        btn_new_map.configure(command=on_new_map)
        btn_save_map.configure(command=on_save_map)
        btn_delete_map.configure(command=on_delete_map)
        map_search_var.trace_add("write", lambda *_: refresh_mapping_list())

        refresh_mapping_list()

    def _create_reference_tab(self, parent, section_title, subtitle, sections, footer_text):
        main = tk.Frame(parent, bg="#F4F6FA", padx=14, pady=14)
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        header_card = tk.Frame(main, bg="#FFFFFF", highlightbackground="#D7DEE8", highlightthickness=1, padx=14, pady=12)
        header_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        tk.Label(header_card, text=section_title, font=("Segoe UI", 11, "bold"), bg="#FFFFFF", fg="#1F2937").pack(anchor="w")
        tk.Label(header_card, text=subtitle, font=("Segoe UI", 9), bg="#FFFFFF", fg="#5B6472").pack(anchor="w", pady=(4, 0))

        content = tk.Frame(main, bg="#FFFFFF", highlightbackground="#D7DEE8", highlightthickness=1)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        canvas = tk.Canvas(content, bg="#FFFFFF", highlightthickness=0)
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=canvas.yview)
        inner = tk.Frame(canvas, bg="#FFFFFF", padx=12, pady=12)
        inner.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))

        for title, items in sections:
            section = tk.LabelFrame(inner, text=title, font=("Segoe UI", 9, "bold"), bg="#FFFFFF", padx=12, pady=12)
            section.pack(fill=tk.X, expand=True, pady=(0, 12))
            for trigger, desc in items:
                row = tk.Frame(section, bg="#FFFFFF")
                row.pack(fill=tk.X, pady=2)
                tk.Label(row, text=trigger, font=("Consolas", 10, "bold"), fg="#2D5BD1", bg="#FFFFFF", width=12, anchor="w").pack(side=tk.LEFT)
                tk.Label(row, text=desc, font=("Segoe UI", 9), bg="#FFFFFF", anchor="w").pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)

        tk.Label(main, text=footer_text, font=("Segoe UI", 8), fg="#5B6472", bg="#F4F6FA").grid(row=2, column=0, sticky="w", pady=(10, 0))

        self._bind_mousewheel(canvas, canvas)
        self._bind_mousewheel_descendants(inner, canvas)

    def _create_datetime_eco_tab(self, parent):
        """Build the reference tab for Date/Time and Economic Indicator snippets."""
        self._create_reference_tab(
            parent,
            "Snippets dinâmicos de data e economia",
            "Esses triggers consultam data/hora local e dados econômicos do Banco Central.",
            [
                ("Data e Hora", DATETIME_SNIPPETS),
                ("Indicadores Econômicos (Banco Central)", ECONOMY_SNIPPETS),
            ],
            "Basta digitar o trigger em qualquer aplicativo suportado.",
        )

    def _create_stocks_tab(self, parent):
        """Build the reference tab for stock snippets (B3 and US)."""
        self._create_reference_tab(
            parent,
            "Snippets de ações e fundamentos",
            "Ao digitar um destes triggers, um popup pedirá o ticker antes da consulta.",
            [("Ações (B3 e US)", STOCK_SNIPPETS)],
            "Aceita tickers brasileiros (PETR4, VALE3) e americanos (AAPL, MSFT, GOOGL).",
        )

    def _create_whatsapp_tab(self, parent):
        """Build the reference tab for the WhatsApp shortcut."""
        self._create_reference_tab(
            parent,
            "Atalho de WhatsApp",
            "Os triggers podem ler o telefone do clipboard ou abrir um popup, sempre validando no mesmo padrão internacional.",
            [("WhatsApp", WHATSAPP_SNIPPETS)],
            "xwapp e xpwapp abrem o navegador. xlwapp insere o link no campo atual e também o mantém no clipboard.",
        )

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

    def tray_open_data_folder(self, icon, item):
        """Tray action: open the user data folder."""
        self.open_data_folder()

    def quit_app(self, icon, item):
        """Quit the application."""
        self.enabled = False
        if self.listener:
            self.listener.stop()
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
        
        self.task_runner.start(self.run_keyboard_listener, name="keyboard-listener")
        
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda text: f"{'✓' if self.enabled else '✗'} Ativado",
                self.toggle_enabled,
                checked=lambda item: self.enabled
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Gerenciar Snippets", self.manage_snippets_gui, default=True),
            pystray.MenuItem("Recarregar Snippets", self.reload_snippets),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Backup agora", self.tray_backup_now),
            pystray.MenuItem("Abrir pasta de dados", self.tray_open_data_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", self.quit_app)
        )

        
        self.icon = pystray.Icon(
            "text_expander",
            self.load_tray_icon(),
            "Text Expander",
            menu
        )

        self.icon.run(setup=self.on_tray_ready)


def main():
    """Main entry point."""
    if not acquire_single_instance_mutex():
        show_already_running_message()
        return

    expander = TextExpander()
    expander.run()


if __name__ == "__main__":
    main()
