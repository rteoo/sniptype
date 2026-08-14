"""Non-activating on-screen status for push-to-talk voice input."""

import ctypes
import tkinter as tk

import ui_theme
from platform_support import current_os


VISIBLE_STATES = frozenset({"recording", "transcribing", "routing"})

_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_HWND_TOPMOST = -1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SW_SHOWNOACTIVATE = 4


def _windows_user32():
    """Bind the pointer-sized Win32 signatures used by the overlay."""
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    return user32


def indicator_content(state, mode=None):
    """Return the visible copy and accent token for a voice state."""
    if state == "recording":
        if mode == "command":
            return "Ouvindo comando…", "Solte para executar · Esc para cancelar", "warning"
        return "Ouvindo…", "Solte para transcrever · Esc para cancelar", "warning"
    if state == "transcribing":
        return "Transcrevendo…", "O texto aparecerá no cursor", "accent"
    if state == "routing":
        return "Inserindo texto…", "", "success"
    return None


class VoiceStatusIndicator:
    """Small bottom-center overlay owned by the shared Tk root."""

    def __init__(self, root):
        self.root = root
        self.window = None
        self.title_label = None
        self.detail_label = None
        self.dot_label = None

    def update(self, state, mode=None):
        content = indicator_content(state, mode)
        if content is None:
            self.hide()
            return
        if self.window is None or not self._window_exists():
            self._build()
        title, detail, accent_name = content
        ui = ui_theme.theme()
        accent = getattr(ui, accent_name)
        self.title_label.configure(text=title)
        self.detail_label.configure(text=detail)
        self.dot_label.configure(fg=accent)
        self._position()
        self._show_without_activation()

    def hide(self):
        if self.window is not None and self._window_exists():
            self.window.withdraw()

    def destroy(self):
        if self.window is not None and self._window_exists():
            self.window.destroy()
        self.window = None

    def _window_exists(self):
        try:
            return bool(self.window.winfo_exists())
        except Exception:
            return False

    def _build(self):
        ui = ui_theme.bind(self.root)
        window = tk.Toplevel(self.root)
        self.window = window
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        try:
            window.attributes("-alpha", 0.96)
        except tk.TclError:
            pass
        window.configure(bg=ui.surface_alt)

        container = tk.Frame(window, bg=ui.surface_alt, padx=16, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        self.dot_label = tk.Label(
            container,
            text="●",
            bg=ui.surface_alt,
            fg=ui.warning,
            font=ui.font(12, "bold"),
        )
        self.dot_label.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        self.title_label = tk.Label(
            container,
            text="",
            bg=ui.surface_alt,
            fg=ui.text,
            font=ui.font(10, "bold"),
            anchor="w",
        )
        self.title_label.grid(row=0, column=1, sticky="w")
        self.detail_label = tk.Label(
            container,
            text="",
            bg=ui.surface_alt,
            fg=ui.text_muted,
            font=ui.font(8),
            anchor="w",
        )
        self.detail_label.grid(row=1, column=1, sticky="w")

    def _position(self):
        self.window.update_idletasks()
        width = max(310, self.window.winfo_reqwidth())
        height = self.window.winfo_reqheight()
        x = max(12, (self.window.winfo_screenwidth() - width) // 2)
        y = max(12, self.window.winfo_screenheight() - height - 72)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _show_without_activation(self):
        """Reveal without moving keyboard focus away from the dictation target."""
        if current_os() != "windows":
            self.window.deiconify()
            self.window.lift()
            return
        try:
            user32 = _windows_user32()
            widget_hwnd = self.window.winfo_id()
            hwnd = user32.GetParent(widget_hwnd) or widget_hwnd
            style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd,
                _GWL_EXSTYLE,
                style | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE,
            )
            self.window.deiconify()
            user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
            user32.SetWindowPos(
                hwnd,
                ctypes.c_void_p(_HWND_TOPMOST),
                0,
                0,
                0,
                0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
            )
        except Exception:
            self.window.deiconify()
