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
import uuid
from datetime import datetime

import i18n
import manager_actions
import time_format
import ui_theme
from dynamic_registry import effective_trigger, reference_entries_by_category, validate_rename
from form_editor_dialog import FormEditorController, type_label
from form_support import DEFAULT_DATE_FORMAT, FIELD_TYPES, FormValidationError, compile_form
from preview_dialog import build_preview_model
from preview_support import resolve_preview
from editor_session import (
    mapping_draft_problem,
    mapping_type_key,
    mapping_type_problem,
    static_draft_problem,
    static_trigger_problem,
)
from group_dialog import (
    APPLICATION_LABELS,
    TERMINATOR_LABELS,
    WINDOWS_POLICY_NOTE,
    GroupDefinitionError,
    GroupDialogController,
    build_group_definition,
)
from group_policy import normalize_group
from i18n import N_, _
from backup_support import backup_time
from library_metadata import MetadataReadOnlyError, mapping_item_metadata, static_item_metadata
from manager_actions import TriggerCollisionError
from manager_view_support import (
    FILTER_ALL,
    FILTER_DISABLED,
    FILTER_FAVORITES,
    FILTER_PROBLEMS,
    FILTER_RECENT,
    UNGROUPED_FILTER,
    filter_manager_rows,
    manager_row_preview,
)
from rich_text_support import extract_plain_text, is_rich_text_payload
from snippet_utils import build_saveable_snippets, mapping_types

MANAGER_EXE_NAME = "sniptype-manager.exe" if sys.platform == "win32" else "sniptype-manager"
MANAGER_UI_SETTING = "manager_ui"
DENSITY_CHOICES = ("compact", "comfortable", "touch")
PREVIEW_LIMIT = 160
LIST_FILTERS = (FILTER_ALL, FILTER_FAVORITES, FILTER_RECENT, FILTER_DISABLED, FILTER_PROBLEMS)
# The group selector value for items in no group; real group ids are UUIDs.
UNGROUPED = "__ungrouped__"
# The dynamic snippet sections, in the order the classic tab shows them.
DYNAMIC_CATEGORIES = {
    "datetime": N_("Data e Hora"),
    "economy": N_("Indicadores Econômicos (Banco Central)"),
    "stock": N_("Ações (B3 e US)"),
    "whatsapp": "WhatsApp",  # i18n: not ui
}


def _read_only_message():
    return _("Os metadados da biblioteca são somente leitura nesta versão; favoritos, grupos e formulários não "
             "podem ser alterados.")


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
            "snippet.duplicate": self.snippet_duplicate,
            "snippet.rename": self.snippet_rename,
            "snippet.setFavorite": self.snippet_set_favorite,
            "snippet.setGroup": self.snippet_set_group,
            "groups.list": self.groups_list,
            "group.form": self.group_form,
            "group.save": self.group_save,
            "group.delete": self.group_delete,
            "group.undoDelete": self.group_undo_delete,
            "backups.list": self.backups_list,
            "backup.create": self.backup_create,
            "backup.preview": self.backup_preview,
            "backup.restore": self.backup_restore,
            "library.exportText": self.library_export_text,
            "library.importPreview": self.library_import_preview,
            "library.import": self.library_import,
            "dynamics.list": self.dynamics_list,
            "dynamic.setEnabled": self.dynamic_set_enabled,
            "dynamic.rename": self.dynamic_rename,
            "form.get": self.form_get,
            "form.save": self.form_save,
            "preview.get": self.preview_get,
            "mapping.types": self.mapping_types,
            "mapping.list": self.mapping_list,
            "mapping.get": self.mapping_get,
            "mapping.save": self.mapping_save,
            "mapping.delete": self.mapping_delete,
            "mapping.undoDelete": self.mapping_undo_delete,
            "mapping.setFavorite": self.mapping_set_favorite,
            "mapping.createType": self.mapping_create_type,
            "mapping.deleteType": self.mapping_delete_type,
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
        """Forms and formatting still live in the Tk manager."""
        self.app.gui.submit(self.app._show_manager_window)
        return None

    # -- library -----------------------------------------------------------

    def _stored(self, trigger):
        """The persisted static value under ``trigger``, shadowed ones included, or None."""
        value = self.app._manager_static_projection().get(trigger)
        return None if callable(value) else value

    def library_list(self, filter=FILTER_ALL, group=None):
        """Static rows, narrowed to one group (or ``UNGROUPED``) and then by ``filter``.

        ``total`` counts every static snippet, so the list can say what a view
        hides. Recentes keeps the order of use; every other view, library order.
        """
        if filter not in LIST_FILTERS:
            raise BridgeError("bad_params", f"unsupported filter {filter!r}")
        projection = self.app._manager_static_projection()
        rows = [row for row in self.app._manager_rows() if row.kind == "static"]
        total = len(rows)
        if group == UNGROUPED:
            rows = filter_manager_rows(rows, UNGROUPED_FILTER)
        elif group:
            rows = filter_manager_rows(rows, "group", group_id=group)
        rows = filter_manager_rows(rows, filter, workflow_state=self.app.workflow_state)
        items = []
        for row in rows:
            preview = " ".join(manager_row_preview(row, projection).split())
            items.append({
                "trigger": row.stored_trigger,
                "effectiveTrigger": row.effective_trigger,
                "groupId": row.group_id,
                "group": row.group_label if row.group_id else None,
                "favorite": row.favorite,
                "enabled": row.enabled,
                "shadowed": row.shadowed,
                "rich": is_rich_text_payload(projection.get(row.stored_trigger)),
                "preview": preview[:PREVIEW_LIMIT],
            })
        return {"items": items, "total": total}

    def _row(self, kind, name, container=None):
        """The manager row of one item, for metadata a filtered list may not hold."""
        return next((row for row in self.app._manager_rows()
                     if row.kind == kind and row.stored_trigger == name and row.container == container), None)

    def snippet_get(self, trigger):
        value = self._stored(trigger)
        row = self._row("static", trigger)
        if value is None or row is None:
            raise BridgeError("missing", _("O snippet {name} não existe mais.").format(name=trigger))
        return {"trigger": trigger, "text": extract_plain_text(value), "rich": is_rich_text_payload(value),
                "effectiveTrigger": row.effective_trigger, "favorite": row.favorite, "groupId": row.group_id}

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
        return {"undoToken": self._remember_undo("static", (trigger, value, provider, item_metadata))}

    def snippet_undo_delete(self, token):
        """Restore the snippet the last delete removed, with its metadata."""
        app = self.app
        trigger, value, provider, item_metadata = self._take_undo("static", token)
        try:
            if provider is not None and app.snippets.get(trigger) is not provider:
                raise ValueError(_("A ação dinâmica mudou desde a exclusão do snippet."))
            projection = app._manager_static_projection()
            dynamic_triggers = app._manager_dynamic_triggers()
            if provider is not None:
                projection.pop(trigger, None)
                dynamic_triggers = dynamic_triggers - {trigger}
            restored = manager_actions.restore_static(
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

    def _commit(self, build, *, mappings=False):
        """Run one ``manager_actions`` transaction and persist it, as the Tk handlers do.

        ``build`` returns the ``ActionResult``; every refusal or failed write
        becomes a ``BridgeError`` with the words the person sees.
        """
        app = self.app
        read_only = getattr(app.library_metadata, "read_only", False)
        try:
            result = build()
        except TriggerCollisionError as error:
            raise BridgeError("collision", _("O trigger efetivo {trigger} já é usado por outro snippet.").format(
                trigger=error.trigger)) from error
        except MetadataReadOnlyError as error:
            raise BridgeError("read_only", _read_only_message()) from error
        except (KeyError, ValueError) as error:
            app.logger.warning(f"Manager bridge action refused: {error}")
            raise BridgeError("refused", str(error)) from error
        persist = app._persist_manager_action if mappings else app._persist_manager_static_action
        if not persist(result):
            raise BridgeError("save_failed", _read_only_message() if read_only
                              else _("Não foi possível salvar a alteração."))
        return result

    def _static_trigger(self, trigger):
        """``trigger`` when it names a saved plain static snippet; a refusal otherwise."""
        value = self.app._manager_static_projection().get(trigger)
        if value is None:
            raise BridgeError("missing", _("O snippet {name} não existe mais.").format(name=trigger))
        if callable(value):
            raise BridgeError("dynamic", _("'{trigger}' é um snippet dinâmico. Gerencie-o em Ações "
                                           "dinâmicas.").format(trigger=trigger))
        return trigger

    def snippet_duplicate(self, trigger, destination):
        """Copy a snippet, formatting and metadata included: ``duplicated`` or ``invalid``."""
        app = self.app
        source = self._static_trigger(trigger)
        destination = destination.strip() if isinstance(destination, str) else ""
        problem = static_trigger_problem(app.snippets, destination)
        if problem:
            return {"status": "invalid", "message": problem}
        self._commit(lambda: manager_actions.duplicate_static(
            app._manager_static_projection(), app.library_metadata, source, destination,
            dynamic_triggers=app._manager_dynamic_triggers(),
        ))
        return {"status": "duplicated", "trigger": destination}

    def snippet_rename(self, trigger, destination, confirmed=()):
        """Rename a snippet with its metadata: ``renamed``, ``invalid`` or ``confirm`` (trigger warnings)."""
        app = self.app
        source = self._static_trigger(trigger)
        destination = destination.strip() if isinstance(destination, str) else ""
        problem = static_trigger_problem(app.snippets, destination, source)
        if problem:
            return {"status": "invalid", "message": problem}
        if destination == source:
            return {"status": "renamed", "trigger": source}
        warnings = app._validate_trigger_warnings(destination)
        if warnings and "warnings" not in confirmed:
            return {
                "status": "confirm",
                "check": "warnings",
                "title": _("Confirmar trigger"),
                "message": _("Avisos sobre este trigger:\n\n• {warnings}").format(warnings="\n• ".join(warnings)),
                "action": _("Renomear mesmo assim"),
            }
        self._commit(lambda: manager_actions.rename_static(
            app._manager_static_projection(), app.library_metadata, source, destination,
            dynamic_triggers=app._manager_dynamic_triggers(),
        ))
        return {"status": "renamed", "trigger": destination}

    def snippet_set_favorite(self, trigger, favorite):
        app = self.app
        source = self._static_trigger(trigger)
        self._commit(lambda: manager_actions.toggle_favorite(
            app._manager_static_projection(), app.library_metadata, source, bool(favorite),
            dynamic_triggers=app._manager_dynamic_triggers(),
        ))
        return {"trigger": source, "favorite": bool(favorite)}

    def snippet_set_group(self, trigger, group):
        """Put a snippet in group ``group``, or in no group when it is empty."""
        app = self.app
        source = self._static_trigger(trigger)
        if group:
            self._group(group)

        def build():
            if group:
                return manager_actions.assign_item(
                    app._manager_static_projection(), app.library_metadata, source, group,
                    dynamic_triggers=app._manager_dynamic_triggers(),
                )
            return manager_actions.unassign_item(
                app._manager_static_projection(), app.library_metadata, source,
                dynamic_triggers=app._manager_dynamic_triggers(),
            )

        self._commit(build)
        return {"trigger": source, "group": group or None}

    # -- groups ------------------------------------------------------------

    def _groups(self):
        metadata = self.app.library_metadata
        groups = metadata.get("groups", {}) if isinstance(metadata, dict) else {}
        return groups if isinstance(groups, dict) else {}

    def _group(self, group_id):
        definition = self._groups().get(group_id)
        if definition is None:
            raise BridgeError("missing_group", _("O grupo não existe mais."))
        return definition

    def groups_list(self):
        """Every group, in library order, and whether the library lets them change."""
        metadata = self.app.library_metadata
        listed = []
        for group_id, definition in self._groups().items():
            policy = normalize_group(group_id, definition)
            static_members, _mappings = manager_actions.group_members(metadata, group_id)
            listed.append({
                "id": str(group_id), "label": policy.label or _("Sem nome"), "prefix": policy.prefix,
                "enabled": policy.enabled, "count": len(static_members),
            })
        return {"readOnly": bool(getattr(metadata, "read_only", False)), "groups": listed}

    def group_form(self, id=None):
        """The values the group dialog opens with, and the words of its choices."""
        values = GroupDialogController(self._group(id) if id else None).initial
        if not id:
            values["label"] = ""
        return {
            "values": values,
            "terminators": [{"value": value, "label": _(label)} for value, label in TERMINATOR_LABELS.items()],
            "applicationModes": [{"value": value, "label": _(label)} for value, label in APPLICATION_LABELS.items()],
            "windowsNote": _(WINDOWS_POLICY_NOTE),
        }

    def group_save(self, values, id=None):
        """Create (no ``id``) or update a group: ``saved`` with its id, or ``invalid`` with the field."""
        app = self.app
        if id:
            self._group(id)
        try:
            definition = build_group_definition(values)
        except GroupDefinitionError as error:
            return {"status": "invalid", "field": error.field or "label", "message": str(error)}
        group_id = id or str(uuid.uuid4())
        action = manager_actions.update_group if id else manager_actions.create_group
        try:
            self._commit(lambda: action(
                app._manager_static_projection(), app.library_metadata, group_id, definition,
                dynamic_triggers=app._manager_dynamic_triggers(),
            ))
        except BridgeError as error:
            if error.code != "collision":
                raise
            # Only a new prefix or a re-enabled group can make members collide.
            return {"status": "invalid", "field": "prefix", "message": error.message}
        return {"status": "saved", "id": group_id, "label": definition["label"]}

    def group_delete(self, id):
        """Delete a group; its snippets stay, in no group. The token brings both back."""
        app = self.app
        definition = copy.deepcopy(dict(self._group(id)))
        static_members, mapping_members = manager_actions.group_members(app.library_metadata, id)
        self._commit(lambda: manager_actions.delete_group(
            app._manager_static_projection(), app.library_metadata, id,
            dynamic_triggers=app._manager_dynamic_triggers(),
        ))
        token = self._remember_undo("group", (id, definition, static_members, mapping_members))
        return {"undoToken": token, "label": definition.get("label") or _("Sem nome")}

    def group_undo_delete(self, token):
        app = self.app
        group_id, definition, static_members, mapping_members = self._take_undo("group", token)
        try:
            self._commit(lambda: manager_actions.restore_group(
                app._manager_static_projection(), app.library_metadata, group_id, definition,
                static_items=static_members, mapping_items=mapping_members,
                dynamic_triggers=app._manager_dynamic_triggers(),
            ))
        except BridgeError as error:
            raise BridgeError(error.code, _("Não foi possível recriar o grupo {name}: {error}").format(
                name=definition.get("label") or _("Sem nome"), error=error.message)) from error
        return {"id": group_id}

    def _remember_undo(self, kind, entry):
        """Keep only the newest delete, as the Tk receipt does; return its token."""
        token = str(next(self._undo_ids))
        self._undo = {token: (kind, entry)}
        return token

    def _take_undo(self, kind, token):
        kept = self._undo.get(token)
        if kept is None or kept[0] != kind:
            raise BridgeError("undo_expired", _("Não há exclusão para desfazer."))
        del self._undo[token]
        return kept[1]

    # -- mappings ----------------------------------------------------------

    def _type(self, container):
        """The listed mapping type ``container``, or a refusal when the library no longer has it."""
        info = mapping_types(self.app.snippets).get(container)
        if info is None:
            raise BridgeError("missing_type", _("O tipo {type} não existe mais.").format(type=container))
        return info

    def _mapping_value(self, container, name):
        mapping = self.app.snippets.get(container)
        if not isinstance(mapping, dict) or name == "__prefix__":
            return None
        return mapping.get(name)

    def mapping_types(self):
        types = []
        for key, info in mapping_types(self.app.snippets).items():
            mapping = self.app.snippets.get(key)
            count = sum(1 for name in mapping if name and name != "__prefix__") if isinstance(mapping, dict) else 0
            types.append({"key": key, **info, "count": count})
        return types

    def mapping_list(self, type):
        self._type(type)
        items = []
        for row in self.app._manager_rows():
            if row.kind != "mapping" or row.container != type:
                continue
            preview = " ".join(manager_row_preview(row, self.app.snippets).split())
            items.append({
                "name": row.stored_trigger,
                "effectiveTrigger": row.effective_trigger,
                "favorite": row.favorite,
                "rich": is_rich_text_payload(self._mapping_value(type, row.stored_trigger)),
                "preview": preview[:PREVIEW_LIMIT],
            })
        return items

    def mapping_get(self, type, name):
        info = self._type(type)
        value = self._mapping_value(type, name)
        if value is None:
            raise BridgeError("missing", _("O item {name} não existe mais.").format(name=name))
        row = self._row("mapping", name, type)
        return {"type": type, "name": name, "text": extract_plain_text(value),
                "rich": is_rich_text_payload(value), "effectiveTrigger": info["prefix"] + name,
                "favorite": bool(row and row.favorite)}

    def mapping_save(self, type, name, text, original=None, confirmed=(), formFrom=None):
        """Save a plain-text mapping item; answers like :meth:`snippet_save`.

        ``formFrom`` names the item of the same type a Duplicar copy was made
        from; its form comes along on this first save.
        """
        info = self._type(type)
        name = name.strip() if isinstance(name, str) else ""
        if not isinstance(text, str):
            raise BridgeError("bad_params", "text must be a string")
        problem = mapping_draft_problem(name, text)
        if problem:
            raise BridgeError("invalid", _(problem))
        existing = self._mapping_value(type, name)
        if is_rich_text_payload(existing):
            raise BridgeError("rich", _("Textos formatados ainda são editados no gerenciador clássico."))
        if existing is not None and name != original and "replace" not in confirmed:
            return {
                "status": "confirm",
                "check": "replace",
                "title": _("Substituir item"),
                "message": _("O item {name} de {type} já existe. Salvar troca o texto dele pelo que está no "
                             "editor.").format(name=name, type=info["label"]),
                "action": _("Substituir"),
            }
        metadata = self._copied_mapping_form(type, name, text, formFrom) if formFrom else None
        if (existing != text or metadata is not None) and not self.app.save_mapping_item(
                type, name, text, metadata=metadata):
            raise BridgeError("save_failed", _(
                "Não foi possível gravar snippets.json, então nada foi salvo. O rascunho continua no "
                "editor; verifique os logs e tente de novo."))
        return {"status": "saved", "type": type, "name": name}

    def _copied_mapping_form(self, type, name, text, source):
        """The metadata that gives ``name`` the form of ``source``, or None when it has none."""
        app = self.app
        form = app._mapping_form_metadata(type, source)
        if form is None:
            return None
        mapping = app.snippets.get(type)
        proposed = {**app.snippets, type: {**(mapping if isinstance(mapping, dict) else {}), name: text}}
        try:
            return manager_actions.set_mapping_form(
                proposed, app.library_metadata, type, name, form,
                dynamic_triggers=app._manager_dynamic_triggers(),
            ).metadata
        except (KeyError, ValueError, MetadataReadOnlyError) as error:
            raise BridgeError("form", _("O formulário copiado não serve para este texto: {error}").format(
                error=error)) from error

    def mapping_delete(self, type, name):
        """Delete one mapping item; the answer carries the token Desfazer sends back."""
        app = self.app
        self._type(type)
        value = copy.deepcopy(self._mapping_value(type, name))
        if value is None:
            raise BridgeError("missing", _("O item {name} não existe mais.").format(name=name))
        item_metadata = mapping_item_metadata(app.library_metadata, type, name)
        if not app.delete_mapping_item(type, name):
            raise BridgeError("save_failed", _("Não foi possível gravar snippets.json. Verifique os logs; a "
                                               "exclusão não foi salva."))
        return {"undoToken": self._remember_undo("mapping", (type, name, value, item_metadata))}

    def mapping_undo_delete(self, token):
        """Restore the item the last mapping delete removed, with its metadata."""
        app = self.app
        container, name, value, item_metadata = self._take_undo("mapping", token)
        try:
            restored = manager_actions.restore_mapping_item(
                app.snippets, app.library_metadata, container, name, value, item_metadata,
                dynamic_triggers=app._manager_dynamic_triggers(),
            )
        except (KeyError, ValueError, MetadataReadOnlyError) as error:
            app.logger.warning(f"Manager bridge mapping restore failed: {error}")
            raise BridgeError("undo_failed", _("Não foi possível restaurar {name}: {error}").format(
                name=name, error=error)) from error
        if not app._persist_manager_action(restored):
            raise BridgeError("save_failed", _("Não foi possível gravar snippets.json. Verifique os logs."))
        return {"type": container, "name": name}

    def mapping_set_favorite(self, type, name, favorite):
        app = self.app
        self._type(type)
        if self._mapping_value(type, name) is None:
            raise BridgeError("missing", _("O item {name} não existe mais.").format(name=name))
        self._commit(lambda: manager_actions.toggle_mapping_favorite(
            app.snippets, app.library_metadata, type, name, bool(favorite),
            dynamic_triggers=app._manager_dynamic_triggers(),
        ), mappings=True)
        return {"type": type, "name": name, "favorite": bool(favorite)}

    def mapping_create_type(self, name, prefix):
        """Create a custom mapping type: ``{"status": "created", "key"}`` or ``{"status": "invalid", ...}``."""
        app = self.app
        type_name = name.strip().lower() if isinstance(name, str) else ""
        prefix = prefix.strip().lower() if isinstance(prefix, str) else ""
        problem = mapping_type_problem(mapping_types(app.snippets), app.snippets, type_name, prefix)
        if problem:
            field, message = problem
            return {"status": "invalid", "field": field, "message": message}
        key = mapping_type_key(type_name)
        if not app.create_mapping_type(key, prefix):
            raise BridgeError("save_failed", _("Não foi possível gravar snippets.json. Verifique os logs; o tipo "
                                               "não foi criado."))
        return {"status": "created", "key": key}

    def mapping_delete_type(self, type):
        """Delete a custom mapping type with every item; the UI has the person type its name first."""
        info = self._type(type)
        if info["builtin"]:
            raise BridgeError("builtin", _("Não é possível excluir tipos padrão (CPF, CNPJ)."))
        if not self.app.delete_mapping_type(type):
            raise BridgeError("save_failed", _("Não foi possível gravar snippets.json. Verifique os logs; o tipo "
                                               "não foi excluído."))
        return {"type": type}

    # -- forms and preview -------------------------------------------------

    def _form_target(self, name, type=None):
        """``(stored value, saved form or None)`` of a static snippet, or of a mapping item when ``type`` is given."""
        app = self.app
        if type:
            self._type(type)
            value = self._mapping_value(type, name)
            if value is None:
                raise BridgeError("missing", _("O item {name} não existe mais.").format(name=name))
            return value, app._mapping_form_metadata(type, name)
        value = self._stored(name)
        if value is None:
            raise BridgeError("missing", _("O snippet {name} não existe mais.").format(name=name))
        return value, app._static_form_metadata(name)

    def form_get(self, name, type=None):
        """The fields the form dialog opens with.

        Without a saved form, the fields are the ones expansion already asks
        for (each ``%%variable%%`` that is not a snippet, a mapping or the
        clipboard), as plain text fields.
        """
        value, form = self._form_target(name, type)
        template = extract_plain_text(value)
        variables = [field.name for field in compile_form(template, None, self.app.snippets).fields]
        if form is not None:
            fields = copy.deepcopy(form.get("fields", []))
        else:
            fields = [{"name": variable, "type": "text", "default": ""} for variable in variables]
        return {
            "saved": form is not None,
            "fields": fields,
            "variables": variables,
            "types": [{"value": field_type, "label": type_label(field_type)} for field_type in FIELD_TYPES],
            "dateFormat": DEFAULT_DATE_FORMAT,
            "readOnly": bool(getattr(self.app.library_metadata, "read_only", False)),
        }

    def form_save(self, name, fields, type=None):
        """Validate a form against the saved text and store it: ``saved``, or ``invalid`` with the field index."""
        app = self.app
        value, _form = self._form_target(name, type)
        controller = FormEditorController(fields, app.snippets, template=extract_plain_text(value))
        try:
            form = controller.save()
        except FormValidationError:
            return {"status": "invalid", "message": controller.error, "index": controller.invalid_index}
        if type:
            self._commit(lambda: manager_actions.set_mapping_form(
                app.snippets, app.library_metadata, type, name, form,
                dynamic_triggers=app._manager_dynamic_triggers(),
            ), mappings=True)
        else:
            self._commit(lambda: manager_actions.set_form(
                app._manager_static_projection(), app.library_metadata, name, form,
                dynamic_triggers=app._manager_dynamic_triggers(),
            ))
        return {"status": "saved", "count": len(form["fields"])}

    def preview_get(self, name=None, type=None, text=None):
        """What expanding would type, without the clipboard or a provider.

        ``text`` is the editor's plain draft; without it the saved value is
        previewed. The saved item's form fills its fields with their defaults;
        a draft whose fields no longer match it is previewed without the form.
        """
        value, form = self._form_target(name, type) if name else (None, None)
        notes = []
        if text is not None:
            if not isinstance(text, str):
                raise BridgeError("bad_params", "text must be a string")
            value = text
        try:
            result = resolve_preview(value, self.app.snippets, form)
        except FormValidationError as error:
            if text is None:
                raise BridgeError("form", _("O formulário não corresponde ao texto: {error}").format(
                    error=error)) from error
            result = resolve_preview(value, self.app.snippets, None)
            notes.append(_("Os campos do rascunho não batem com o formulário salvo; eles aparecem vazios."))
        model = build_preview_model(result)
        return {"text": model.text, "status": "\n".join(note for note in (model.status_text, *notes) if note)}

    # -- dynamic snippets --------------------------------------------------

    def _dynamic_entry(self, key):
        entry = self.app.dynamic_registry.get(key)
        if not isinstance(entry, dict):
            raise BridgeError("missing", _("O snippet dinâmico {name} não existe mais.").format(name=key))
        return entry

    def dynamics_list(self):
        """Every registered dynamic snippet by section; ``key`` is the stable id the overrides use."""
        sections = []
        for category, entries in reference_entries_by_category(self.app.dynamic_registry).items():
            sections.append({
                "id": category,
                "label": _(DYNAMIC_CATEGORIES.get(category, category)),
                "items": [
                    {"key": key, "trigger": trigger, "description": _(description) if description else "",
                     "enabled": enabled}
                    for key, trigger, description, enabled in entries
                ],
            })
        return sections

    def dynamic_set_enabled(self, key, enabled, confirmed=()):
        """Turn one dynamic snippet on or off.

        Turning on a trigger a static snippet or a mapping item already uses
        answers ``confirm`` first; the shadowed value stays on disk.
        """
        app = self.app
        self._dynamic_entry(key)
        enabled = bool(enabled)
        if enabled and "shadow" not in confirmed:
            conflict = app._dynamic_shadow_conflict(key)
            if conflict is not None:
                title, message = conflict
                return {"status": "confirm", "check": "shadow", "title": title, "message": message,
                        "action": _("Ativar mesmo assim")}
        if not app._toggle_registry_entry(key, enabled, confirmed=True):
            raise BridgeError("save_failed", _("Falha ao salvar alteração do snippet dinâmico."))
        return {"status": "saved", "key": key, "enabled": enabled}

    def dynamic_rename(self, key, trigger, confirmed=()):
        """Give a dynamic snippet another trigger: ``renamed``, ``invalid`` or ``confirm`` (warnings)."""
        app = self.app
        entry = self._dynamic_entry(key)
        trigger = trigger.strip() if isinstance(trigger, str) else ""
        if trigger and trigger == effective_trigger(key, entry):
            return {"status": "renamed", "key": key, "trigger": trigger}
        errors, warnings = validate_rename(
            app.dynamic_registry, key, trigger,
            build_saveable_snippets(app.snippets, app.shadowed_static_snippets), app.library_metadata,
        )
        if errors:
            return {"status": "invalid", "message": "\n".join(errors)}
        if warnings and "warnings" not in confirmed:
            return {"status": "confirm", "check": "warnings", "title": _("Confirmar trigger"),
                    "message": "\n".join(warnings), "action": _("Renomear mesmo assim")}
        if not app._rename_registry_entry(key, trigger):
            raise BridgeError("save_failed", _("Falha ao salvar o novo nome do snippet dinâmico."))
        return {"status": "renamed", "key": key, "trigger": trigger}

    # -- backups, import and export -----------------------------------------

    def _backup_path(self, name):
        """The backup called ``name``; only a listed backup, so a name never reaches outside backups."""
        for backup in self.app.backup_summaries():
            if os.path.basename(backup["path"]) == name:
                return backup["path"]
        raise BridgeError("missing", _("O backup não existe mais."))

    def backups_list(self):
        """Every backup, newest first, as the Backups page lists it."""
        now = datetime.now()
        return [{
            "name": os.path.basename(backup["path"]),
            "when": time_format.stamp_with_age(backup["taken"], now),
            "texts": backup["texts"],
            "lists": backup["lists"],
            "size": backup["size"],
            "empty": backup["empty"],
        } for backup in self.app.backup_summaries()]

    def backup_create(self):
        created = self.app.backup_now()
        if not created:
            raise BridgeError("save_failed", _("Falha ao criar backup. Verifique os logs."))
        return {"name": os.path.basename(created)}

    def backup_preview(self, name):
        """What restoring a backup changes, for the question before it."""
        path = self._backup_path(name)
        counts, error = self.app.preview_restore(path)
        if error:
            raise BridgeError("invalid", error)
        return {"name": name, "when": time_format.stamp_with_age(backup_time(path), datetime.now()),
                "counts": counts}

    def backup_restore(self, name):
        """Put a backup in place of the library; the current library is backed up first."""
        path = self._backup_path(name)
        ok, error = self.app.restore_backup(path)
        if not ok:
            raise BridgeError("restore_failed", _("Falha ao restaurar: {error}").format(error=error))
        return {"name": name, "when": time_format.absolute_stamp(backup_time(path), datetime.now())}

    def library_export_text(self):
        """The library file as it is on disk; the window saves it where the person chooses."""
        try:
            with open(self.app.snippets_file, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as error:
            raise BridgeError("export_failed", _("Falha ao exportar: {error}").format(error=error)) from error
        return {"text": text, "fileName": "snippets-export.json"}

    def _import_document(self, text):
        """The library document in ``text``, or a refusal saying why it cannot be imported."""
        if not isinstance(text, str):
            raise BridgeError("bad_params", "text must be a string")
        try:
            data = json.loads(text)
        except ValueError as error:
            raise BridgeError("invalid", _("Arquivo inválido: {error}").format(error=error)) from error
        document, error = self.app.read_import_document(data)
        if error:
            raise BridgeError("invalid", error)
        return document

    def library_import_preview(self, text):
        """``{merge, replace}`` change counts for the file the window read."""
        return self.app.import_change_counts(self._import_document(text))

    def library_import(self, text, mode):
        """Import the file the window read: ``merge`` or ``replace``, the current library backed up first."""
        if mode not in ("merge", "replace"):
            raise BridgeError("bad_params", f"unsupported mode {mode!r}")
        ok, error = self.app.apply_import(self._import_document(text), mode)
        if not ok:
            raise BridgeError("import_failed", error)
        return {"mode": mode}

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
