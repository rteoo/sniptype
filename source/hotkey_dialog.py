"""GUI-thread-only editor for optional workflow hotkeys.

The dialog is deliberately a thin adapter around :mod:`hotkey_support`.
Normalization owns parsing and conflict rules; this module only presents the
three supported actions and keeps the window open when normalization reports a
bad or duplicate binding.
"""

import threading
import tkinter as tk

import ui_theme
from hotkey_support import ACTIONS, normalize_hotkeys


ACTION_LABELS = {
    "open_manager": "Abrir gerenciador",
    "edit_last": "Editar último expandido",
    "toggle_enabled": "Alternar expansão",
}
HINT_TEXT = "Use combinações como <ctrl>+<shift>+m. Deixe vazio para desativar."


class HotkeyDialogController:
    """Tk-free save/cancel controller for the three optional bindings."""

    def __init__(self, bindings=None, controls=None, *, normalizer=normalize_hotkeys):
        source = bindings if isinstance(bindings, dict) else {}
        self.initial = {action: source.get(action) for action in ACTIONS}
        self.controls = controls or {}
        self.normalizer = normalizer
        self.result = None
        self.error = None
        self.invalid_action = None

    def collect_values(self):
        return {
            action: self.controls[action].get()
            for action in ACTIONS
            if action in self.controls
        }

    def save(self):
        """Normalize values; return false and focus the offending row on error."""
        values = self.collect_values()
        normalized, invalid = self.normalizer(values)
        if invalid:
            self.result = None
            self.error = "; ".join(
                f"{ACTION_LABELS.get(action, action)}: {reason}"
                for action, reason in invalid.items()
            )
            self.invalid_action = next(
                (action for action in ACTIONS if action in invalid), None
            )
            control = self.controls.get(self.invalid_action)
            if control is not None:
                control.focus_set()
            return False
        self.result = normalized
        self.error = None
        self.invalid_action = None
        return True

    def cancel(self):
        self.result = None
        self.error = None
        self.invalid_action = None


class HotkeyDialog:
    """Build and run the hotkey editor on its creating GUI thread."""

    def __init__(self, parent, bindings=None, *, title="Atalhos", theme=None):
        self._owner_thread = threading.current_thread()
        self.parent = parent
        self.theme = theme or ui_theme.bind(parent)
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.transient(parent)
        self.window.configure(bg=self.theme.surface)
        self.window.minsize(420, 260)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self._controls = {}
        self._error_label = None
        self.controller = None
        self._bindings = bindings or {}
        self._build()

    def _assert_owner(self):
        if threading.current_thread() is not self._owner_thread:
            raise RuntimeError("HotkeyDialog must be used on the GUI thread")

    def _build(self):
        self._assert_owner()
        body = tk.Frame(self.window, bg=self.theme.surface)
        body.pack(fill="both", expand=True, padx=self.theme.space_lg, pady=self.theme.space_lg)

        tk.Label(
            body, text=HINT_TEXT, anchor="w", justify="left",
            bg=self.theme.surface, fg=self.theme.text_muted, font=self.theme.font(8),
        ).pack(fill="x", pady=(0, self.theme.space_md))

        card = tk.Frame(body, bg=self.theme.card)
        card.pack(fill="both", expand=True)
        normalized, _invalid = normalize_hotkeys(self._bindings)
        for action in ACTIONS:
            row = tk.Frame(card, bg=self.theme.card)
            row.pack(fill="x", padx=self.theme.space_md, pady=self.theme.space_sm)
            tk.Label(
                row, text=ACTION_LABELS[action], anchor="w", width=24,
                bg=self.theme.card, fg=self.theme.text, font=self.theme.font(),
            ).pack(side="left")
            control = tk.Entry(
                row, **self.theme.entry_colors(), font=self.theme.font(),
            )
            if normalized.get(action):
                control.insert(0, normalized[action])
            control.pack(side="left", fill="x", expand=True)
            self._controls[action] = control

        self._error_label = tk.Label(
            body, text="", anchor="w", justify="left",
            bg=self.theme.surface, fg=self.theme.danger, font=self.theme.font(8),
        )
        self._error_label.pack(fill="x", pady=(self.theme.space_sm, 0))

        buttons = tk.Frame(body, bg=self.theme.surface)
        buttons.pack(fill="x", pady=(self.theme.space_md, 0))
        tk.Button(
            buttons, text="Cancelar", command=self.cancel,
            **self.theme.button_chrome(compact=True), **self.theme.button_colors(),
        ).pack(side="right")
        tk.Button(
            buttons, text="Salvar", command=self.save,
            **self.theme.button_chrome(compact=True), **self.theme.button_colors(accent=True),
        ).pack(side="right", padx=(0, self.theme.space_sm))

        self.controller = HotkeyDialogController(self._bindings, self._controls)
        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.window.bind("<Return>", lambda _event: self.save())

    def save(self):
        self._assert_owner()
        if not self.controller.save():
            self._error_label.configure(text=self.controller.error or "Atalho inválido.")
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
        """Block via Tk's wait_window and return normalized bindings or ``None``."""
        self._assert_owner()
        self.window.grab_set()
        self.window.focus_force()
        first = next(iter(self._controls.values()), None)
        if first is not None:
            first.focus_set()
        self.window.wait_window()
        return self.controller.result


def run_hotkey_dialog(parent, bindings=None, *, title="Atalhos", theme=None):
    """Show the editor on the caller's GUI thread and return save/cancel result."""
    return HotkeyDialog(parent, bindings, title=title, theme=theme).run()


__all__ = [
    "ACTION_LABELS",
    "ACTIONS",
    "HINT_TEXT",
    "HotkeyDialog",
    "HotkeyDialogController",
    "run_hotkey_dialog",
]
