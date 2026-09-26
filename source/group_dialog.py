"""GUI-thread-only editor for schema-v1 snippet groups.

The controller keeps group normalization and persistence representation out of
Tk.  It returns the value stored under ``__sniptype__.groups[group_id]``;
callers own the surrounding library save and group identity.
"""

import threading
import tkinter as tk
from tkinter import ttk

import ui_theme
from i18n import N_, _
from group_policy import (
    VALID_APPLICATION_MODES,
    VALID_TERMINATOR_POLICIES,
    normalize_executable_name,
    normalize_group,
)


TERMINATOR_LABELS = {
    "inherit": N_("Herdar configuração global"),
    "immediate": N_("Expandir imediatamente"),
    "terminator": N_("Exigir terminador"),
}
APPLICATION_LABELS = {
    "all": N_("Todos os aplicativos"),
    "allow": N_("Somente aplicativos permitidos"),
    "deny": N_("Todos, exceto os bloqueados"),
}
WINDOWS_POLICY_NOTE = N_(
    "As regras de executável são somente para Windows e evitam expansões "
    "acidentais; não são uma barreira de autenticação."
)


class GroupDefinitionError(ValueError):
    """A rejected group definition; ``field`` names the control to focus."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def _choice_token(value, labels, valid):
    if value in valid:
        return value
    for token, label in labels.items():
        if value in (label, _(label)):
            return token
    return None


def normalize_executable_lines(value):
    """Return unique normalized basenames, or raise ``ValueError`` on a bad line."""
    if not isinstance(value, str):
        raise GroupDefinitionError(_("Executáveis devem ser informados, um por linha."), "executables")
    normalized = []
    for line_number, raw in enumerate(value.splitlines(), start=1):
        if not raw.strip():
            continue
        executable = normalize_executable_name(raw)
        if executable is None:
            raise GroupDefinitionError(
                _("Executável inválido na linha {line}.").format(line=line_number), "executables"
            )
        if executable not in normalized:
            normalized.append(executable)
    return tuple(normalized)


def build_group_definition(values):
    """Validate controls and return the schema-v1 JSON group definition."""
    if not isinstance(values, dict):
        raise GroupDefinitionError(_("Configuração do grupo inválida."))
    label = values.get("label")
    if not isinstance(label, str) or not label.strip():
        raise GroupDefinitionError(_("O nome do grupo é obrigatório."), "label")
    notes = values.get("notes", "")
    prefix = values.get("prefix", "")
    enabled = values.get("enabled", True)
    if not isinstance(notes, str) or not isinstance(prefix, str):
        raise GroupDefinitionError(_("Notas e prefixo devem ser texto."), "notes")
    if any(character.isspace() for character in prefix):
        raise GroupDefinitionError(_("O prefixo não pode conter espaços."), "prefix")
    if not isinstance(enabled, bool):
        raise GroupDefinitionError(_("O estado do grupo deve ser booleano."))

    terminator = _choice_token(
        values.get("terminator", "inherit"),
        TERMINATOR_LABELS,
        VALID_TERMINATOR_POLICIES,
    )
    if terminator is None:
        raise GroupDefinitionError(_("Política de terminador inválida."), "terminator")
    application_mode = _choice_token(
        values.get("application_mode", "all"),
        APPLICATION_LABELS,
        VALID_APPLICATION_MODES,
    )
    if application_mode is None:
        raise GroupDefinitionError(_("Modo de aplicativo inválido."), "application_mode")

    executables = normalize_executable_lines(values.get("executables", ""))
    return {
        "label": label.strip(),
        "notes": notes,
        "prefix": prefix,
        "enabled": enabled,
        "terminator": terminator,
        "applications": {
            "mode": application_mode,
            "executables": list(executables),
        },
    }


class GroupDialogController:
    """Tk-free save/cancel controller for group settings."""

    def __init__(self, group=None, controls=None):
        normalized = normalize_group(None, group or {})
        self.initial = {
            "label": normalized.label,
            "notes": normalized.notes,
            "prefix": normalized.prefix,
            "enabled": normalized.enabled,
            "terminator": normalized.terminator,
            "application_mode": normalized.applications.mode,
            "executables": "\n".join(normalized.applications.executables),
        }
        self.controls = controls or {}
        self.result = None
        self.error = None
        self.invalid_field = None

    def collect_values(self):
        values = {}
        for name in (
            "label", "notes", "prefix", "enabled", "terminator",
            "application_mode", "executables",
        ):
            if name in self.controls:
                values[name] = self.controls[name].get()
        return values

    def save(self):
        values = self.collect_values()
        try:
            result = build_group_definition(values)
        except ValueError as error:
            self.result = None
            self.error = str(error)
            self.invalid_field = getattr(error, "field", None)
            control = self.controls.get(self.invalid_field)
            if control is not None:
                control.focus_set()
            return False
        self.result = result
        self.error = None
        self.invalid_field = None
        return True

    def cancel(self):
        self.result = None
        self.error = None
        self.invalid_field = None


class _TextControl:
    def __init__(self, widget):
        self.widget = widget

    def get(self):
        return self.widget.get("1.0", "end-1c")

    def focus_set(self):
        self.widget.focus_set()


class _VariableControl:
    def __init__(self, variable, widget):
        self.variable = variable
        self.widget = widget

    def get(self):
        return self.variable.get()

    def focus_set(self):
        self.widget.focus_set()


class GroupDialog:
    """Build and run group controls on their creating GUI thread."""

    def __init__(self, parent, group=None, *, title=N_("Configuração do grupo"), theme=None):
        self._owner_thread = threading.current_thread()
        self.parent = parent
        self.theme = theme or ui_theme.bind(parent)
        self.window = tk.Toplevel(parent)
        self.window.title(_(title))
        self.window.transient(parent)
        self.window.configure(bg=self.theme.surface)
        ui_theme.prepare_window(self.window, self.theme)
        self.window.minsize(520, 520)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self._group = group or {}
        self._controls = {}
        self._variables = {}
        self._error_label = None
        self.controller = None
        self._build()

    def _assert_owner(self):
        if threading.current_thread() is not self._owner_thread:
            raise RuntimeError("GroupDialog must be used on the GUI thread")

    def _label(self, parent, text):
        tk.Label(
            parent, text=text, anchor="w", bg=self.theme.card,
            fg=self.theme.text, font=self.theme.font(),
        ).pack(fill="x", padx=self.theme.space_md, pady=(self.theme.space_sm, self.theme.space_xs))

    def _build(self):
        self._assert_owner()
        body = tk.Frame(self.window, bg=self.theme.surface)
        body.pack(fill="both", expand=True, padx=self.theme.space_lg, pady=self.theme.space_lg)
        card = tk.Frame(body, bg=self.theme.card, pady=self.theme.space_sm)
        card.pack(fill="both", expand=True)

        self._label(card, _("Nome do grupo *"))
        label = tk.Entry(card, **self.theme.entry_colors(), **self.theme.field_chrome(), font=self.theme.font())
        label.pack(fill="x", padx=self.theme.space_md)

        self._label(card, _("Notas"))
        notes = tk.Text(card, height=3, wrap="word", **self.theme.text_colors(), **self.theme.field_chrome(), font=self.theme.font())
        notes.pack(fill="x", padx=self.theme.space_md)

        self._label(card, _("Prefixo de runtime"))
        prefix = tk.Entry(card, **self.theme.entry_colors(), **self.theme.field_chrome(), font=self.theme.font())
        prefix.pack(fill="x", padx=self.theme.space_md)

        enabled_var = tk.BooleanVar(self.window)
        enabled = tk.Checkbutton(
            card, text=_("Grupo ativo"), variable=enabled_var,
            **self.theme.checkbutton_colors(self.theme.card), font=self.theme.font(),
        )
        enabled.pack(anchor="w", padx=self.theme.space_md, pady=(self.theme.space_sm, 0))

        self._label(card, _("Terminador"))
        terminator = ttk.Combobox(
            card, state="readonly", values=tuple(_(label) for label in TERMINATOR_LABELS.values())
        )
        terminator.pack(fill="x", padx=self.theme.space_md)

        self._label(card, _("Modo de aplicativo"))
        application_mode = ttk.Combobox(
            card, state="readonly", values=tuple(_(label) for label in APPLICATION_LABELS.values())
        )
        application_mode.pack(fill="x", padx=self.theme.space_md)

        tk.Label(
            card, text=_(WINDOWS_POLICY_NOTE), anchor="w", justify="left",
            wraplength=470, bg=self.theme.card, fg=self.theme.text_muted,
            font=self.theme.font(8),
        ).pack(fill="x", padx=self.theme.space_md, pady=(self.theme.space_sm, 0))

        self._label(card, _("Executáveis (um por linha)"))
        executables = tk.Text(card, height=4, wrap="none", **self.theme.text_colors(), **self.theme.field_chrome(), font=self.theme.mono_font(8))
        executables.pack(fill="both", expand=True, padx=self.theme.space_md)

        normalized = normalize_group(None, self._group)
        label.insert(0, normalized.label if self._group else "")
        notes.insert("1.0", normalized.notes)
        prefix.insert(0, normalized.prefix)
        enabled_var.set(normalized.enabled)
        terminator.set(_(TERMINATOR_LABELS[normalized.terminator]))
        application_mode.set(_(APPLICATION_LABELS[normalized.applications.mode]))
        executables.insert("1.0", "\n".join(normalized.applications.executables))

        self._controls = {
            "label": label,
            "notes": _TextControl(notes),
            "prefix": prefix,
            "enabled": _VariableControl(enabled_var, enabled),
            "terminator": terminator,
            "application_mode": application_mode,
            "executables": _TextControl(executables),
        }
        self.controller = GroupDialogController(self._group, self._controls)

        self._error_label = tk.Label(
            body, text="", anchor="w", justify="left",
            bg=self.theme.surface, fg=self.theme.danger, font=self.theme.font(8),
        )
        self._error_label.pack(fill="x", pady=(self.theme.space_sm, 0))
        buttons = tk.Frame(body, bg=self.theme.surface)
        buttons.pack(fill="x", pady=(self.theme.space_md, 0))
        tk.Button(
            buttons, text=_("Cancelar"), command=self.cancel,
            **self.theme.button_chrome(compact=True), **self.theme.button_colors(),
        ).pack(side="right")
        tk.Button(
            buttons, text=_("Salvar"), command=self.save,
            **self.theme.button_chrome(compact=True), **self.theme.button_colors(accent=True),
        ).pack(side="right", padx=(0, self.theme.space_sm))
        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.window.bind("<Return>", self._save_from_key)

    def _save_from_key(self, event):
        if isinstance(event.widget, tk.Text):
            return None
        self.save()
        return "break"

    def save(self):
        self._assert_owner()
        if not self.controller.save():
            self._error_label.configure(text=self.controller.error or _("Configuração inválida."))
            return False
        self._close()
        return True

    def cancel(self):
        self._assert_owner()
        self.controller.cancel()
        self._close()

    def _close(self):
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        self.window.destroy()

    def run(self):
        self._assert_owner()
        self.window.grab_set()
        self.window.focus_force()
        first = self._controls.get("label")
        if first is not None:
            first.focus_set()
        self.window.wait_window()
        return self.controller.result


def run_group_dialog(parent, group=None, *, title=N_("Configuração do grupo"), theme=None):
    """Show the group editor on the caller's GUI thread and return its result."""
    return GroupDialog(parent, group, title=title, theme=theme).run()


__all__ = [
    "APPLICATION_LABELS",
    "TERMINATOR_LABELS",
    "WINDOWS_POLICY_NOTE",
    "GroupDefinitionError",
    "GroupDialog",
    "GroupDialogController",
    "build_group_definition",
    "normalize_executable_lines",
    "run_group_dialog",
]
