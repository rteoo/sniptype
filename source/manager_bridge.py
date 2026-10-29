"""JSON bridge between the app and the Tauri manager window.

The Tauri manager (``ui/``) is a child process of the app. It writes one JSON
request per line on its stdout (``{"id", "method", "params"}``) and reads one
JSON message per line on its stdin: a response (``{"id", "result"}`` or
``{"id", "error"}``) or an event (``{"event"}``). The manager never touches
``snippets.json`` itself: every change goes through the app's own save path,
so backups, quarantine, shadowed statics and rollback hold exactly as they do
for the classic Tk manager.

Requests run on the GUI thread (``GuiThread.call``), serialized with the Tk
manager and every other handler that mutates the library.
"""

import copy
import itertools
import json
import os
import subprocess
import sys
import threading

import i18n
import ui_theme
from editor_session import static_draft_problem
from i18n import _
from library_metadata import MetadataReadOnlyError, static_item_metadata
from manager_actions import restore_static as manager_restore_static
from manager_view_support import manager_row_preview
from rich_text_support import extract_plain_text, is_rich_text_payload

MANAGER_EXE_NAME = "sniptype-manager.exe" if sys.platform == "win32" else "sniptype-manager"
MANAGER_UI_SETTING = "manager_ui"
DENSITY_CHOICES = ("compact", "comfortable", "touch")
PREVIEW_LIMIT = 160


class BridgeError(Exception):
    """A request the bridge refuses; ``message`` is shown to the person."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class ManagerBridge:
    """Answer manager requests against a live ``Sniptype``. GUI thread only."""

    def __init__(self, app, *, version, channel):
        self.app = app
        self.version = version
        self.channel = channel
        self._undo = {}
        self._undo_ids = itertools.count(1)
        self.methods = {
            "app.info": self.app_info,
            "app.openDataFolder": self.open_data_folder,
            "app.openClassicManager": self.open_classic_manager,
            "library.list": self.library_list,
            "snippet.get": self.snippet_get,
            "snippet.save": self.snippet_save,
            "snippet.delete": self.snippet_delete,
            "snippet.undoDelete": self.snippet_undo_delete,
            "settings.set": self.settings_set,
        }

    def handle(self, message):
        """Return the response for one decoded request."""
        request_id = message.get("id") if isinstance(message, dict) else None
        method = self.methods.get(message.get("method")) if isinstance(message, dict) else None
        if method is None:
            return {"id": request_id, "error": {"code": "unknown_method",
                                                "message": f"unknown method: {message!r}"}}
        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return {"id": request_id, "error": {"code": "bad_params", "message": "params must be an object"}}
        try:
            return {"id": request_id, "result": method(**params)}
        except BridgeError as error:
            return {"id": request_id, "error": {"code": error.code, "message": error.message}}
        except TypeError as error:
            # A malformed request from our own UI: say which, never crash the reader.
            return {"id": request_id, "error": {"code": "bad_params", "message": str(error)}}

    # -- app ---------------------------------------------------------------

    def app_info(self):
        app = self.app
        return {
            "version": self.version,
            "channel": self.channel,
            "language": i18n.language(),
            "languages": dict(i18n.LANGUAGES),
            "appearance": ui_theme.normalize_preference(app.settings.get("appearance")),
            "density": app.settings.get("density") if app.settings.get("density") in DENSITY_CHOICES
            else "compact",
            "terminatorMode": bool(app.terminator_mode),
            "dataDir": str(app.data_dir),
            "issues": [
                {"id": issue.id, "severity": issue.severity, "title": issue.title, "body": issue.body}
                for issue in app._manager_issues()
            ],
        }

    def open_data_folder(self):
        self.app.open_data_folder()
        return None

    def open_classic_manager(self):
        """Mapeamentos, dynamics, forms and backups still live in the Tk manager."""
        self.app.gui.submit(self.app._show_manager_window)
        return None

    # -- library -----------------------------------------------------------

    def _stored(self, trigger):
        """The persisted static value under ``trigger``, shadowed ones included, or None."""
        value = self.app._manager_static_projection().get(trigger)
        return None if callable(value) else value

    def library_list(self):
        projection = self.app._manager_static_projection()
        items = []
        for row in self.app._manager_rows():
            if row.kind != "static":
                continue
            preview = " ".join(manager_row_preview(row, projection).split())
            items.append({
                "trigger": row.stored_trigger,
                "effectiveTrigger": row.effective_trigger,
                "group": row.group_label if row.group_id else None,
                "favorite": row.favorite,
                "enabled": row.enabled,
                "shadowed": row.shadowed,
                "rich": is_rich_text_payload(projection.get(row.stored_trigger)),
                "preview": preview[:PREVIEW_LIMIT],
            })
        return items

    def snippet_get(self, trigger):
        value = self._stored(trigger)
        if value is None:
            raise BridgeError("missing", _("O snippet {name} não existe mais.").format(name=trigger))
        return {"trigger": trigger, "text": extract_plain_text(value), "rich": is_rich_text_payload(value)}

    def snippet_save(self, trigger, text, original=None, confirmed=()):
        """Save a plain-text static snippet.

        Answers ``{"status": "saved"}``, or ``{"status": "confirm", "check", ...}``
        when the person has to accept a replacement or trigger warnings first;
        the UI repeats the request with that check in ``confirmed``.
        """
        app = self.app
        trigger = trigger.strip() if isinstance(trigger, str) else ""
        if not isinstance(text, str):
            raise BridgeError("bad_params", "text must be a string")
        problem = static_draft_problem(trigger, text)
        if problem:
            raise BridgeError("invalid", _(problem))

        existing = self._stored(trigger)
        if is_rich_text_payload(existing):
            # Plain text from this editor would drop the formatting on disk.
            raise BridgeError("rich", _("Textos formatados ainda são editados no gerenciador clássico."))
        if existing is not None and trigger != original and "replace" not in confirmed:
            return {
                "status": "confirm",
                "check": "replace",
                "title": _("Substituir snippet"),
                "message": _("O snippet {name} já existe. Salvar troca o texto dele pelo que está no "
                             "editor.").format(name=trigger),
                "action": _("Substituir"),
            }
        if trigger not in app.snippets or callable(app.snippets[trigger]):
            warnings = app._validate_trigger_warnings(trigger)
            if warnings and "warnings" not in confirmed:
                return {
                    "status": "confirm",
                    "check": "warnings",
                    "title": _("Confirmar trigger"),
                    "message": _("Avisos sobre este trigger:\n\n• {warnings}").format(
                        warnings="\n• ".join(warnings)),
                    "action": _("Salvar mesmo assim"),
                }
        if existing == text:
            return {"status": "saved", "trigger": trigger}
        if not app.save_static_snippet(trigger, text):
            raise BridgeError("save_failed", _(
                "Não foi possível gravar snippets.json, então nada foi salvo. O rascunho continua no "
                "editor; verifique os logs e tente de novo."))
        return {"status": "saved", "trigger": trigger}

    def snippet_delete(self, trigger):
        """Delete a static snippet; the answer carries the token Desfazer sends back."""
        app = self.app
        value = copy.deepcopy(self._stored(trigger))
        provider = app.snippets.get(trigger) if trigger in app.shadowed_static_snippets else None
        item_metadata = static_item_metadata(app.library_metadata, trigger)
        outcome = app._delete_static_snippet(trigger, include_shadowed=True)
        if outcome == "dynamic":
            raise BridgeError("dynamic", _("'{trigger}' é um snippet dinâmico. Gerencie-o em Ações "
                                           "dinâmicas.").format(trigger=trigger))
        if outcome == "missing":
            raise BridgeError("missing", _("O snippet {name} não existe mais.").format(name=trigger))
        if outcome == "error":
            raise BridgeError("save_failed", _("Não foi possível gravar snippets.json. Verifique os logs; a "
                                               "exclusão pode não ter sido salva."))
        token = str(next(self._undo_ids))
        self._undo = {token: (trigger, value, provider, item_metadata)}
        return {"undoToken": token}

    def snippet_undo_delete(self, token):
        """Restore the snippet the last delete removed, with its metadata."""
        app = self.app
        entry = self._undo.pop(token, None)
        if entry is None:
            raise BridgeError("undo_expired", _("Não há exclusão para desfazer."))
        trigger, value, provider, item_metadata = entry
        try:
            if provider is not None and app.snippets.get(trigger) is not provider:
                raise ValueError(_("A ação dinâmica mudou desde a exclusão do snippet."))
            projection = app._manager_static_projection()
            dynamic_triggers = app._manager_dynamic_triggers()
            if provider is not None:
                projection.pop(trigger, None)
                dynamic_triggers = dynamic_triggers - {trigger}
            restored = manager_restore_static(
                projection, app.library_metadata, trigger, value, item_metadata,
                dynamic_triggers=dynamic_triggers,
            )
        except (KeyError, ValueError, MetadataReadOnlyError) as error:
            app.logger.warning(f"Manager bridge restore failed: {error}")
            raise BridgeError("undo_failed", _("Não foi possível restaurar {trigger}: {error}").format(
                trigger=trigger, error=error)) from error
        if not app._persist_manager_static_action(restored):
            raise BridgeError("save_failed", _("Não foi possível gravar snippets.json. Verifique os logs."))
        return {"trigger": trigger}

    # -- settings ----------------------------------------------------------

    def settings_set(self, key, value):
        """Persist one Configurações choice, then apply it the way the Tk cards do."""
        app = self.app
        valid = {
            "language": value in i18n.LANGUAGES,
            "appearance": value in ui_theme.APPEARANCE_CHOICES,
            "density": value in DENSITY_CHOICES,
            "terminatorMode": isinstance(value, bool),
        }
        if not valid.get(key, False):
            raise BridgeError("bad_params", f"unsupported setting {key!r}={value!r}")
        stored_key = "terminator_mode" if key == "terminatorMode" else key
        if not app._persist_settings({stored_key: value}):
            raise BridgeError("save_failed", _("Não foi possível salvar."))
        if key == "language":
            i18n.set_language(value)
            app.refresh_tray_menu()
        elif key == "appearance":
            ui_theme.set_preference(value)
        elif key == "density":
            ui_theme.set_density(value)
        else:
            app.terminator_mode = value
            app.refresh_runtime_indexes()
        return self.app_info()


def find_manager_executable(env=None, frozen=None, executable=None, source_dir=None):
    """Locate the Tauri manager binary, or None.

    ``SNIPTYPE_MANAGER_EXE`` wins; a packaged app ships it beside its own
    executable; a source checkout uses the release build, then the debug one.
    """
    env = os.environ if env is None else env
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    executable = sys.executable if executable is None else executable
    source_dir = os.path.dirname(os.path.abspath(__file__)) if source_dir is None else source_dir

    override = env.get("SNIPTYPE_MANAGER_EXE")
    if override:
        return override if os.path.isfile(override) else None
    if frozen:
        candidates = [os.path.join(os.path.dirname(executable), MANAGER_EXE_NAME)]
    else:
        target = os.path.join(os.path.dirname(source_dir), "ui", "src-tauri", "target")
        candidates = [os.path.join(target, build, MANAGER_EXE_NAME) for build in ("release", "debug")]
    return next((path for path in candidates if os.path.isfile(path)), None)


class ManagerProcess:
    """One running Tauri manager window and the thread that answers it."""

    def __init__(self, app, executable, bridge, *, popen=subprocess.Popen, log_path=None):
        self.app = app
        self.bridge = bridge
        self._write_lock = threading.Lock()
        stderr = open(log_path, "ab") if log_path else subprocess.DEVNULL
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = popen(
                [executable],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                creationflags=flags,
            )
        finally:
            if stderr is not subprocess.DEVNULL:
                stderr.close()
        self._reader = threading.Thread(target=self._read_requests, name="manager-bridge", daemon=True)
        self._reader.start()

    @property
    def alive(self):
        return self.process.poll() is None

    def send(self, message):
        line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            try:
                self.process.stdin.write(line)
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as error:
                self.app.logger.warning(f"Manager bridge write failed: {error}")

    def focus(self):
        self.send({"event": "focus"})

    def close(self):
        """Close the window: EOF on its stdin ends the Tauri process."""
        with self._write_lock:
            try:
                self.process.stdin.close()
            except OSError:
                pass

    def _answer(self, raw):
        try:
            message = json.loads(raw)
        except ValueError:
            self.app.logger.warning(f"Manager bridge: ignored a line that is not JSON: {raw[:200]!r}")
            return
        try:
            response = self.app.gui.call(lambda _root: self.bridge.handle(message))
        except Exception as error:
            self.app.logger.exception("Manager bridge request failed")
            response = {"id": message.get("id") if isinstance(message, dict) else None,
                        "error": {"code": "internal", "message": str(error)}}
        self.send(response)

    def _read_requests(self):
        for raw in self.process.stdout:
            raw = raw.decode("utf-8", errors="replace").strip()
            if raw:
                self._answer(raw)
        self.process.wait()
        self.app.logger.info(f"Manager window closed (exit {self.process.returncode}).")
