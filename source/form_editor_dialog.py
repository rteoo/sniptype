"""Structured form-definition editor for the snippet manager.

The controller owns a private, ordered draft and is deliberately independent
of Tk.  ``FormEditor`` is a thin GUI wrapper around that draft: it creates one
``Toplevel`` under the supplied application root and returns a new persisted
definition only after :mod:`form_support` accepts every field.
"""

from copy import deepcopy
import threading
import tkinter as tk
from tkinter import ttk

import ui_theme
from form_support import (
    DEFAULT_DATE_FORMAT,
    FIELD_TYPES,
    FormField,
    FormValidationError,
    compile_form,
    validate_form_fields,
)


_TYPE_LABELS = {
    "text": "Texto",
    "multiline": "Texto multilinha",
    "choice": "Escolha",
    "date": "Data",
    "optional": "Opcional",
}


def _field_draft(field):
    if isinstance(field, FormField):
        field = {
            "name": field.name,
            "type": field.type,
            "default": field.default,
            "options": list(field.options),
            "content": field.content,
            "output_format": field.output_format,
            "label": field.label,
        }
    if not isinstance(field, dict):
        return deepcopy(field)
    return deepcopy(field)


def _initial_fields(definition):
    if definition is None:
        return []
    if isinstance(definition, dict):
        definition = definition.get("fields", [])
    if not isinstance(definition, (list, tuple)):
        raise TypeError("Form definition fields must be a list")
    return [_field_draft(field) for field in definition]


def _default_for_type(field_type):
    if field_type == "choice":
        return "Option 1"
    if field_type == "date":
        return "today"
    if field_type == "optional":
        return False
    return ""


def _new_field(field_type):
    field = {"name": "", "type": field_type, "default": _default_for_type(field_type)}
    if field_type == "choice":
        field["options"] = ["Option 1"]
    elif field_type == "date":
        field["output_format"] = DEFAULT_DATE_FORMAT
    elif field_type == "optional":
        field["content"] = ""
    return field


def _persist_field(field):
    """Convert normalized ``FormField`` data to the small JSON schema."""
    result = {
        "name": field.name,
        "type": field.type,
        "default": field.default,
    }
    if field.label is not None:
        result["label"] = field.label
    if field.type == "choice":
        result["options"] = list(field.options)
    elif field.type == "date":
        result["output_format"] = field.output_format
    elif field.type == "optional":
        result["content"] = field.content
    return result


class FormEditorController:
    """Tk-free ordered draft and validation seam for form definitions."""

    def __init__(
        self,
        definition=None,
        snippets=None,
        *,
        template=None,
        validator=validate_form_fields,
    ):
        self.fields = _initial_fields(definition)
        self.snippets = snippets
        self.template = template
        self.validator = validator
        self.result = None
        self.error = None
        self.invalid_index = None

    def _field(self, index):
        try:
            return self.fields[index]
        except (IndexError, TypeError) as exc:
            raise IndexError(f"Unknown form field index: {index}") from exc

    def add_field(self, field_type="text"):
        if field_type not in FIELD_TYPES:
            raise ValueError(f"Unsupported form field type: {field_type}")
        field = _new_field(field_type)
        self.fields.append(field)
        return len(self.fields) - 1

    def update_field(self, index, **changes):
        field = self._field(index)
        field.update(deepcopy(changes))
        return index

    def remove_field(self, index):
        self._field(index)
        del self.fields[index]
        return index

    def move_field(self, index, delta):
        self._field(index)
        if not isinstance(delta, int):
            raise TypeError("Field movement must be an integer")
        new_index = max(0, min(len(self.fields) - 1, index + delta))
        if new_index != index:
            self.fields[index], self.fields[new_index] = (
                self.fields[new_index], self.fields[index]
            )
        return new_index

    def _error_field_index(self, error):
        paths = getattr(error, "errors", ())
        for path in paths:
            if isinstance(path, str) and path.startswith("fields["):
                try:
                    return int(path.split("[", 1)[1].split("]", 1)[0])
                except (IndexError, ValueError):
                    pass
        message = str(error)
        for index, field in enumerate(self.fields):
            name = field.get("name") if isinstance(field, dict) else None
            if isinstance(name, str) and name and name in message:
                return index
        return 0 if self.fields else None

    def save(self):
        """Validate the draft and return a detached ``{fields: [...]}`` result."""
        try:
            if self.template is None:
                normalized = self.validator(self.fields, self.snippets)
            else:
                normalized = compile_form(
                    self.template,
                    self.fields,
                    self.snippets,
                ).fields
        except FormValidationError as error:
            self.error = str(error)
            self.invalid_index = self._error_field_index(error)
            raise
        self.error = None
        self.invalid_index = None
        self.result = {"fields": [_persist_field(field) for field in normalized]}
        return deepcopy(self.result)

    def cancel(self):
        """Discard the draft and leave ``result`` unset."""
        self.result = None
        self.error = None
        self.invalid_index = None
        return None


class FormEditor:
    """Single-Toplevel GUI editor for one structured form definition."""

    def __init__(
        self,
        parent,
        definition=None,
        snippets=None,
        *,
        template=None,
        title="Editar formulário",
        theme=None,
    ):
        self._owner_thread = threading.current_thread()
        self.controller = FormEditorController(
            definition,
            snippets,
            template=template,
        )
        self.parent = parent
        self.theme = theme or ui_theme.bind(parent)
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.transient(parent)
        self.window.configure(bg=self.theme.surface)
        ui_theme.prepare_window(self.window, self.theme)
        self.window.minsize(720, 500)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self._selected = None
        self._updating = False
        self._build()
        self._refresh_list()
        if self.controller.fields:
            self._select(0)

    def _assert_owner(self):
        if threading.current_thread() is not self._owner_thread:
            raise RuntimeError("FormEditor must be used on the GUI thread")

    def _label(self, parent, text):
        tk.Label(
            parent, text=text, anchor="w", bg=self.theme.card,
            fg=self.theme.text, font=self.theme.font(),
        ).pack(fill="x", pady=(self.theme.space_sm, self.theme.space_xs))

    def _button(self, parent, text, command, *, accent=False, danger=False):
        return tk.Button(
            parent, text=text, command=command,
            **self.theme.button_chrome(compact=True),
            **self.theme.button_colors(accent=accent, danger=danger),
        )

    def _build(self):
        self._assert_owner()
        body = tk.Frame(self.window, bg=self.theme.surface)
        body.pack(fill="both", expand=True, padx=self.theme.space_lg, pady=self.theme.space_lg)

        heading = tk.Label(
            body, text="Campos do formulário", anchor="w",
            bg=self.theme.surface, fg=self.theme.text_strong, font=self.theme.font(weight="bold"),
        )
        heading.pack(fill="x", pady=(0, self.theme.space_sm))
        content = tk.Frame(body, bg=self.theme.surface)
        content.pack(fill="both", expand=True)

        left = tk.Frame(content, bg=self.theme.card)
        left.pack(side="left", fill="y", padx=(0, self.theme.space_md))
        self._field_list = tk.Listbox(
            left, width=27, height=16, exportselection=False,
            **self.theme.listbox_colors(), **self.theme.field_chrome(),
            font=self.theme.font(),
        )
        self._field_list.pack(fill="both", expand=True)
        self._field_list.bind("<<ListboxSelect>>", self._on_select)
        list_buttons = tk.Frame(left, **self.theme.toolbar_frame_colors())
        list_buttons.pack(fill="x", pady=(self.theme.space_sm, 0))
        self._button(list_buttons, "Adicionar", self._add).pack(side="left")
        self._button(list_buttons, "↑", self._move_up).pack(side="left", padx=(self.theme.space_xs, 0))
        self._button(list_buttons, "↓", self._move_down).pack(side="left", padx=(self.theme.space_xs, 0))
        self._button(list_buttons, "Remover", self._remove, danger=True).pack(side="left", padx=(self.theme.space_xs, 0))

        right = tk.Frame(content, bg=self.theme.card)
        right.pack(side="left", fill="both", expand=True)
        editor = tk.Frame(right, bg=self.theme.card)
        editor.pack(fill="both", expand=True, padx=self.theme.space_lg, pady=self.theme.space_lg)

        self.name_var = tk.StringVar(self.window)
        self.label_var = tk.StringVar(self.window)
        self.type_var = tk.StringVar(self.window)
        self.default_var = tk.StringVar(self.window)
        self.options_var = tk.StringVar(self.window)
        self.content_var = tk.StringVar(self.window)
        self.format_var = tk.StringVar(self.window)
        self.optional_default_var = tk.BooleanVar(self.window, value=False)

        self._label(editor, "Nome")
        self.name_entry = tk.Entry(editor, textvariable=self.name_var, **self.theme.entry_colors(), **self.theme.field_chrome(), font=self.theme.font())
        self.name_entry.pack(fill="x")
        self._label(editor, "Rótulo")
        self.label_entry = tk.Entry(editor, textvariable=self.label_var, **self.theme.entry_colors(), **self.theme.field_chrome(), font=self.theme.font())
        self.label_entry.pack(fill="x")
        self._label(editor, "Tipo")
        self.type_combo = ttk.Combobox(editor, textvariable=self.type_var, state="readonly", values=FIELD_TYPES)
        self.type_combo.pack(fill="x")
        self.type_combo.bind("<<ComboboxSelected>>", self._on_type_change)
        self._label(editor, "Valor padrão")
        self.default_entry = tk.Entry(editor, textvariable=self.default_var, **self.theme.entry_colors(), **self.theme.field_chrome(), font=self.theme.font())
        self.default_entry.pack(fill="x")
        self.optional_default = tk.Checkbutton(
            editor, text="Selecionado por padrão", variable=self.optional_default_var,
            **self.theme.checkbutton_colors(self.theme.card), font=self.theme.font(),
        )

        self._choice_frame = tk.Frame(editor, bg=self.theme.card)
        self._label(self._choice_frame, "Opções (uma por linha)")
        self.options_text = tk.Text(self._choice_frame, height=5, wrap="word", **self.theme.text_colors(), **self.theme.field_chrome(), font=self.theme.font())
        self.options_text.pack(fill="x")
        self._optional_frame = tk.Frame(editor, bg=self.theme.card)
        self._label(self._optional_frame, "Conteúdo quando selecionado")
        self.content_entry = tk.Entry(self._optional_frame, textvariable=self.content_var, **self.theme.entry_colors(), **self.theme.field_chrome(), font=self.theme.font())
        self.content_entry.pack(fill="x")
        self._date_frame = tk.Frame(editor, bg=self.theme.card)
        self._label(self._date_frame, "Formato da data")
        self.format_entry = tk.Entry(self._date_frame, textvariable=self.format_var, **self.theme.entry_colors(), **self.theme.field_chrome(), font=self.theme.font())
        self.format_entry.pack(fill="x")

        self.error_label = tk.Label(
            editor, text="", anchor="w", justify="left",
            bg=self.theme.card, fg=self.theme.danger, font=self.theme.font(8),
        )
        self.error_label.pack(fill="x", pady=(self.theme.space_md, 0))
        actions = tk.Frame(body, bg=self.theme.surface)
        actions.pack(fill="x", pady=(self.theme.space_md, 0))
        self._button(actions, "Cancelar", self.cancel).pack(side="right")
        self._button(actions, "Salvar", self.submit, accent=True).pack(side="right", padx=(0, self.theme.space_sm))
        self.window.bind("<Escape>", lambda _event: self.cancel())

    def _refresh_list(self):
        self._updating = True
        try:
            self._field_list.delete(0, "end")
            for field in self.controller.fields:
                name = field.get("name") if isinstance(field, dict) else ""
                field_type = field.get("type", "text") if isinstance(field, dict) else "text"
                self._field_list.insert("end", f"{name or '(sem nome)'} — {_TYPE_LABELS.get(field_type, field_type)}")
            if self._selected is not None and self.controller.fields:
                self._selected = max(0, min(self._selected, len(self.controller.fields) - 1))
                self._field_list.selection_set(self._selected)
                self._field_list.see(self._selected)
        finally:
            self._updating = False

    def _current_index(self):
        selected = self._field_list.curselection()
        return selected[0] if selected else self._selected

    def _select(self, index):
        self._commit_current()
        self._selected = index
        self._field_list.selection_clear(0, "end")
        self._field_list.selection_set(index)
        self._field_list.see(index)
        self._load_current()

    def _on_select(self, _event=None):
        if self._updating:
            return
        selected = self._field_list.curselection()
        if selected:
            self._select(selected[0])

    def _load_current(self):
        field = self.controller.fields[self._selected]
        self._updating = True
        try:
            self.name_var.set(field.get("name", ""))
            self.label_var.set(field.get("label", ""))
            field_type = field.get("type", "text")
            self.type_var.set(field_type)
            self.default_var.set(str(field.get("default", "")) if field_type != "optional" else "")
            self.optional_default_var.set(bool(field.get("default", False)))
            self.content_var.set(field.get("content", ""))
            self.format_var.set(field.get("output_format", DEFAULT_DATE_FORMAT))
            self.options_text.delete("1.0", "end")
            self.options_text.insert("1.0", "\n".join(field.get("options", [])))
            self._render_type_fields(field_type)
        finally:
            self._updating = False

    def _render_type_fields(self, field_type):
        self._choice_frame.pack_forget()
        self._optional_frame.pack_forget()
        self._date_frame.pack_forget()
        self.optional_default.pack_forget()
        if field_type == "choice":
            self._choice_frame.pack(fill="x", pady=(self.theme.space_sm, 0))
        elif field_type == "optional":
            self._optional_frame.pack(fill="x", pady=(self.theme.space_sm, 0))
            self.optional_default.pack(anchor="w", pady=(self.theme.space_sm, 0))
        elif field_type == "date":
            self._date_frame.pack(fill="x", pady=(self.theme.space_sm, 0))

    def _commit_current(self):
        if self._selected is None or self._updating:
            return
        field = self.controller.fields[self._selected]
        field_type = self.type_var.get() or "text"
        field.update({
            "name": self.name_var.get(),
            "label": self.label_var.get(),
            "type": field_type,
        })
        if field_type == "optional":
            field["default"] = bool(self.optional_default_var.get())
            field["content"] = self.content_var.get()
            field.pop("options", None)
            field.pop("output_format", None)
        elif field_type == "choice":
            field["default"] = self.default_var.get()
            field["options"] = self.options_text.get("1.0", "end-1c").splitlines()
            field.pop("content", None)
            field.pop("output_format", None)
        elif field_type == "date":
            field["default"] = self.default_var.get()
            field["output_format"] = self.format_var.get()
            field.pop("options", None)
            field.pop("content", None)
        else:
            field["default"] = self.default_var.get()
            field.pop("options", None)
            field.pop("content", None)
            field.pop("output_format", None)

    def _on_type_change(self, _event=None):
        if self._updating:
            return
        self._commit_current()
        self._render_type_fields(self.type_var.get())

    def _add(self):
        self._assert_owner()
        self._commit_current()
        index = self.controller.add_field("text")
        self._refresh_list()
        self._select(index)
        self.name_entry.focus_set()

    def _remove(self):
        self._assert_owner()
        index = self._current_index()
        if index is None:
            return
        self.controller.remove_field(index)
        self._selected = None if not self.controller.fields else min(index, len(self.controller.fields) - 1)
        self._refresh_list()
        if self._selected is not None:
            self._select(self._selected)

    def _move(self, delta):
        self._assert_owner()
        index = self._current_index()
        if index is None:
            return
        self._commit_current()
        self._selected = self.controller.move_field(index, delta)
        self._refresh_list()
        self._select(self._selected)

    def _move_up(self):
        self._move(-1)

    def _move_down(self):
        self._move(1)

    def _focus_invalid(self):
        index = self.controller.invalid_index
        if index is None or not self.controller.fields:
            return
        index = max(0, min(index, len(self.controller.fields) - 1))
        self._selected = index
        self._refresh_list()
        self._field_list.selection_set(index)
        self._load_current()
        self.name_entry.focus_set()

    def submit(self):
        self._assert_owner()
        self._commit_current()
        try:
            result = self.controller.save()
        except FormValidationError:
            self.error_label.configure(text=self.controller.error or "Campo inválido.")
            self._focus_invalid()
            return False
        self._close()
        return result

    def cancel(self):
        self._assert_owner()
        self.controller.cancel()
        self._close()
        return None

    def _close(self):
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        self.window.destroy()

    def run(self):
        """Wait for submit/cancel on the GUI thread and return the result."""
        self._assert_owner()
        self.window.grab_set()
        self.window.focus_force()
        self.window.wait_window()
        return self.controller.result


def run_form_editor(
    parent,
    definition=None,
    snippets=None,
    *,
    template=None,
    title="Editar formulário",
    theme=None,
):
    """Open the editor on the caller's GUI thread."""
    return FormEditor(
        parent,
        definition,
        snippets,
        template=template,
        title=title,
        theme=theme,
    ).run()


__all__ = ["FormEditor", "FormEditorController", "run_form_editor"]
