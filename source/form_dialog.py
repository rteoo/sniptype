"""Tk form dialog for :mod:`form_support`.

This module owns controls only; compilation and value validation stay in the
pure form domain.  ``FormDialog`` must be created and driven on the shared GUI
thread.  The expansion worker can call ``run_form_dialog`` through
``GuiThread.call`` and receive either a values mapping or ``None`` on cancel.
"""

import calendar
from datetime import date
import threading
import tkinter as tk
from tkinter import ttk

import ui_theme
from i18n import N_, _
from form_support import CompiledForm, FormValidationError, render_form


def _date_default(field):
    """Return a date field's initial ISO value without freezing ``today``."""
    value = field.default
    if value == "today":
        return date.today().isoformat()
    return value


def month_grid(year, month):
    """Return calendar rows for the standard-library month picker."""
    return calendar.monthcalendar(year, month)


class FormDialogController:
    """Tk-free submission controller used by the dialog and focused tests."""

    def __init__(self, compiled, controls, *, renderer=render_form):
        if not isinstance(compiled, CompiledForm):
            raise TypeError("FormDialogController expects a CompiledForm")
        self.compiled = compiled
        self.controls = controls
        self.renderer = renderer
        self.result = None
        self.error = None
        self.invalid_field = None

    def collect_values(self):
        values = {}
        for field in self.compiled.fields:
            control = self.controls[field.name]
            if field.type == "multiline":
                values[field.name] = control.get("1.0", "end-1c")
            else:
                values[field.name] = control.get()
        return values

    def _field_for_error(self, error):
        message = str(error)
        for field in self.compiled.fields:
            if field.name in message:
                return field.name
        return self.compiled.fields[0].name if self.compiled.fields else None

    def submit(self):
        """Validate and retain values; return false while the dialog stays open."""
        values = self.collect_values()
        try:
            self.renderer(self.compiled, values)
        except FormValidationError as error:
            self.error = str(error)
            self.invalid_field = self._field_for_error(error)
            control = self.controls.get(self.invalid_field)
            if control is not None:
                control.focus_set()
            return False
        self.error = None
        self.invalid_field = None
        self.result = values
        return True

    def cancel(self):
        self.result = None
        self.error = None
        self.invalid_field = None


class _DatePicker:
    """Small month-grid picker that writes an ISO date into a StringVar."""

    def __init__(self, parent, variable, theme):
        self.parent = parent
        self.variable = variable
        self.theme = theme
        self.window = None
        self._year = date.today().year
        self._month = date.today().month

    def open(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            return
        self.window = tk.Toplevel(self.parent)
        self.window.title(_("Escolher data"))
        self.window.transient(self.parent)
        self.window.resizable(False, False)
        self.window.configure(bg=self.theme.card)
        ui_theme.prepare_window(self.window, self.theme)
        self._build()
        self.window.grab_set()

    def _build(self):
        header = tk.Frame(self.window, **self.theme.toolbar_frame_colors())
        header.pack(fill="x", padx=self.theme.space_md, pady=(self.theme.space_md, self.theme.space_sm))
        previous = tk.Button(
            header, text="‹", command=lambda: self._move(-1),
            **self.theme.button_chrome(compact=True),
            **self.theme.button_colors(),
        )
        previous.pack(side="left")
        self._month_label = tk.Label(
            header, font=self.theme.font(weight="bold"), fg=self.theme.text,
            bg=self.theme.card,
        )
        self._month_label.pack(side="left", expand=True)
        following = tk.Button(
            header, text="›", command=lambda: self._move(1),
            **self.theme.button_chrome(compact=True),
            **self.theme.button_colors(),
        )
        following.pack(side="right")
        self._grid = tk.Frame(self.window, **self.theme.toolbar_frame_colors())
        self._grid.pack(fill="both", expand=True, padx=self.theme.space_md, pady=self.theme.space_sm)
        self._draw_month()

    def _move(self, delta):
        month = self._month + delta
        if month < 1:
            self._year -= 1
            month = 12
        elif month > 12:
            self._year += 1
            month = 1
        self._month = month
        self._draw_month()

    def _draw_month(self):
        for child in self._grid.winfo_children():
            child.destroy()
        self._month_label.configure(
            text=f"{calendar.month_name[self._month]} {self._year}"
        )
        for column, name in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            tk.Label(
                self._grid, text=name, width=3, font=self.theme.font(weight="bold"),
                fg=self.theme.text_muted, bg=self.theme.card,
            ).grid(row=0, column=column, padx=1, pady=1)
        for row, week in enumerate(month_grid(self._year, self._month), start=1):
            for column, day in enumerate(week):
                if not day:
                    tk.Label(self._grid, text="", width=3, bg=self.theme.card).grid(
                        row=row, column=column, padx=1, pady=1
                    )
                    continue
                tk.Button(
                    self._grid, text=str(day), width=3,
                    command=lambda selected=day: self._select(selected),
                    **self.theme.button_chrome(compact=True),
                    **self.theme.button_colors(),
                ).grid(row=row, column=column, padx=1, pady=1)

    def _select(self, day):
        self.variable.set(date(self._year, self._month, day).isoformat())
        self.window.grab_release()
        self.window.destroy()
        self.window = None


class FormDialog:
    """Build and run controls for one compiled form on the GUI thread."""

    def __init__(self, parent, compiled, *, title=N_("Preencher campos"), theme=None):
        if not isinstance(compiled, CompiledForm):
            raise TypeError("FormDialog expects a CompiledForm")
        self._owner_thread = threading.current_thread()
        self.parent = parent
        self.compiled = compiled
        self.theme = theme or ui_theme.bind(parent)
        self.window = tk.Toplevel(parent)
        self.window.title(_(title))
        self.window.transient(parent)
        self.window.configure(bg=self.theme.surface)
        ui_theme.prepare_window(self.window, self.theme)
        self.window.minsize(350, 300)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self._variables = {}
        self._controls = {}
        self._date_pickers = {}
        self._error_label = None
        self.controller = None
        self._build()

    def _assert_owner(self):
        if threading.current_thread() is not self._owner_thread:
            raise RuntimeError("FormDialog must be used on the GUI thread")

    def _build(self):
        self._assert_owner()
        body = tk.Frame(self.window, bg=self.theme.surface)
        body.pack(fill="both", expand=True, padx=self.theme.space_lg, pady=self.theme.space_lg)
        self._build_fields(body)
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
            buttons, text=_("OK"), command=self.submit,
            **self.theme.button_chrome(compact=True), **self.theme.button_colors(accent=True),
        ).pack(side="right", padx=(0, self.theme.space_sm))
        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.window.bind("<Return>", self._submit_from_key)

    def _submit_from_key(self, event):
        # Return is content inside a multiline control. Other controls retain
        # the existing keyboard-submit convenience.
        if isinstance(event.widget, tk.Text):
            return None
        self.submit()
        return "break"

    def _label(self, parent, field):
        label = field.label or field.name.replace("_", " ").title()
        tk.Label(
            parent, text=label, anchor="w", bg=self.theme.card,
            fg=self.theme.text, font=self.theme.font(),
        ).pack(fill="x", pady=(self.theme.space_sm, self.theme.space_xs))

    def _build_fields(self, parent):
        # A vertical frame is intentionally used instead of a second Tk root;
        # multiline fields own their own scrollbar and all controls share the
        # process-wide GUI thread.
        fields = tk.Frame(parent, bg=self.theme.card, bd=0)
        fields.pack(fill="both", expand=True)
        for field in self.compiled.fields:
            self._label(fields, field)
            if field.type == "multiline":
                control_frame = tk.Frame(fields, bg=self.theme.card)
                control_frame.pack(fill="both", expand=True)
                control = tk.Text(
                    control_frame, height=5, wrap="word",
                    **self.theme.text_colors(), **self.theme.field_chrome(), font=self.theme.font(),
                )
                scrollbar = ttk.Scrollbar(control_frame, orient="vertical", command=control.yview)
                control.configure(yscrollcommand=scrollbar.set)
                control.pack(side="left", fill="both", expand=True)
                scrollbar.pack(side="right", fill="y")
                control.insert("1.0", field.default)
            elif field.type == "choice":
                control = ttk.Combobox(fields, state="readonly", values=field.options)
                control.set(field.default)
                control.pack(fill="x")
            elif field.type == "optional":
                variable = tk.BooleanVar(self.window, value=field.default)
                control = tk.Checkbutton(
                    fields, text=field.content, variable=variable,
                    **self.theme.checkbutton_colors(self.theme.card),
                    font=self.theme.font(),
                )
                control.pack(anchor="w")
                self._variables[field.name] = variable
            elif field.type == "date":
                control_frame = tk.Frame(fields, bg=self.theme.card)
                control_frame.pack(fill="x")
                variable = tk.StringVar(self.window, value=_date_default(field))
                control = tk.Entry(control_frame, textvariable=variable, **self.theme.entry_colors(), **self.theme.field_chrome(), font=self.theme.font())
                control.pack(side="left", fill="x", expand=True)
                tk.Button(
                    control_frame, text=_("Calendário"), command=lambda name=field.name: self._date_pickers[name].open(),
                    **self.theme.button_chrome(compact=True), **self.theme.button_colors(),
                ).pack(side="right", padx=(self.theme.space_sm, 0))
                self._variables[field.name] = variable
                self._date_pickers[field.name] = _DatePicker(self.window, variable, self.theme)
            else:
                variable = tk.StringVar(self.window, value=field.default)
                control = tk.Entry(fields, textvariable=variable, **self.theme.entry_colors(), **self.theme.field_chrome(), font=self.theme.font())
                control.pack(fill="x")
                self._variables[field.name] = variable
            self._controls[field.name] = control
        self.controller = FormDialogController(self.compiled, self._control_bindings())

    def _control_bindings(self):
        bindings = dict(self._controls)
        for name, variable in self._variables.items():
            control = bindings[name]
            bindings[name] = _VariableControl(variable, control)
        return bindings

    def submit(self):
        self._assert_owner()
        if not self.controller.submit():
            self._error_label.configure(text=self.controller.error or _("Valor inválido."))
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
        """Block the calling worker via Tk's wait_window until submit/cancel."""
        self._assert_owner()
        self.window.grab_set()
        self.window.focus_force()
        first = next(iter(self._controls.values()), None)
        if first is not None:
            first.focus_set()
        self.window.wait_window()
        return self.controller.result


class _VariableControl:
    """Adapt a Tk variable plus widget to the controller's tiny read/focus seam."""

    def __init__(self, variable, widget):
        self.variable = variable
        self.widget = widget

    def get(self, *args):
        return self.variable.get()

    def focus_set(self):
        self.widget.focus_set()


def run_form_dialog(parent, compiled, *, title=N_("Preencher campos"), theme=None):
    """Show one form on the caller's GUI thread and return values or ``None``."""
    return FormDialog(parent, compiled, title=title, theme=theme).run()


__all__ = [
    "FormDialog",
    "FormDialogController",
    "month_grid",
    "run_form_dialog",
]
