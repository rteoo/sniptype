"""Observe clicks without putting Python on Windows' synchronous mouse hook.

The observer publishes only a counter. The keyboard listener owns its buffer
and compares that counter; the observer never calls Tk or edits app state.
"""

import ctypes
import threading

from platform_support import IS_WINDOWS


BUTTON_DOWN_FLAGS = 0x0155  # Left, right, middle, X1 and X2 button-down.
WM_INPUT = 0x00FF
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x0100
RIDEV_REMOVE = 0x0001


if IS_WINDOWS:
    from ctypes import wintypes

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
        wintypes.WPARAM, wintypes.LPARAM,
    )

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ]

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [
            ("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
            ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND),
        ]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [
            ("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
            ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM),
        ]

    class MOUSEBUTTONS(ctypes.Structure):
        _fields_ = [("flags", wintypes.USHORT), ("data", wintypes.USHORT)]

    class MOUSEBUTTONUNION(ctypes.Union):
        _fields_ = [("buttons", MOUSEBUTTONS), ("ulButtons", wintypes.ULONG)]

    class RAWMOUSE(ctypes.Structure):
        _fields_ = [
            ("usFlags", wintypes.USHORT), ("buttonUnion", MOUSEBUTTONUNION),
            ("ulRawButtons", wintypes.ULONG), ("lLastX", wintypes.LONG),
            ("lLastY", wintypes.LONG), ("ulExtraInformation", wintypes.ULONG),
        ]

    class RAWMOUSEINPUT(ctypes.Structure):
        _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


def _windows_api():
    """Bind pointer-sized Win32 signatures only on the Windows backend."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "RegisterClassW": ([ctypes.POINTER(WNDCLASS)], wintypes.ATOM),
        "UnregisterClassW": ([wintypes.LPCWSTR, wintypes.HINSTANCE], wintypes.BOOL),
        "CreateWindowExW": ([
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ], wintypes.HWND),
        "DestroyWindow": ([wintypes.HWND], wintypes.BOOL),
        "DefWindowProcW": ([
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ], ctypes.c_ssize_t),
        "RegisterRawInputDevices": ([
            ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT,
        ], wintypes.BOOL),
        "GetRawInputData": ([
            wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
            ctypes.POINTER(wintypes.UINT), wintypes.UINT,
        ], wintypes.UINT),
        "GetMessageW": ([
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
        ], wintypes.BOOL),
        "TranslateMessage": ([ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
        "DispatchMessageW": ([ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
        "PostMessageW": ([
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ], wintypes.BOOL),
        "PostQuitMessage": ([ctypes.c_int], None),
    }
    for name, (args, result) in signatures.items():
        function = getattr(user32, name)
        function.argtypes, function.restype = args, result
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    return user32, kernel32


class MouseActivityMonitor:
    """Start/stop a background click counter; construction has no OS effects."""

    def __init__(self):
        self._generation = 0
        self._error = None
        self._thread = None
        self._listener = None
        self._user32 = None
        self._hwnd = None
        self._ready = threading.Event()
        self._stopping = threading.Event()

    @property
    def generation(self):
        if self._error is not None:
            raise RuntimeError("Mouse input capture failed; restart Sniptype") from self._error
        if self._listener is not None and not self._listener.is_alive():
            raise RuntimeError("Mouse input capture stopped; restart Sniptype")
        return self._generation

    def _on_click(self, _x, _y, _button, pressed, *_args):
        if pressed:
            self._generation += 1

    def start(self):
        if self._thread is not None or self._listener is not None:
            raise RuntimeError("Mouse input capture is already started")
        self._stopping.clear()
        self._ready.clear()
        self._error = None
        if not IS_WINDOWS:
            from pynput import mouse

            self._listener = mouse.Listener(on_click=self._on_click)
            self._listener.start()
            return
        self._thread = threading.Thread(
            target=self._run_windows, name="mouse-input", daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(3):
            self.stop()
            raise RuntimeError("Mouse input capture did not start in time")
        if self._error is not None:
            self.stop()
            raise RuntimeError("Mouse input capture could not start") from self._error

    def stop(self):
        self._stopping.set()
        if self._listener is not None:
            self._listener.stop()
            self._listener.join(3)
            if self._listener.is_alive():
                raise RuntimeError("Mouse input capture did not stop in time")
            self._listener = None
        if self._thread is not None:
            if self._hwnd is not None:
                if not self._user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0):
                    raise ctypes.WinError(ctypes.get_last_error())
            self._thread.join(3)
            if self._thread.is_alive():
                raise RuntimeError("Mouse input capture did not stop in time")
            self._thread = None

    def _read_mouse(self, handle):
        # A registered mouse packet has a fixed, DWORD-aligned native layout.
        packet = RAWMOUSEINPUT()
        size = wintypes.UINT(ctypes.sizeof(packet))
        received = self._user32.GetRawInputData(
            handle, RID_INPUT, ctypes.byref(packet), ctypes.byref(size),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if received == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        if received < ctypes.sizeof(packet) or packet.header.dwType != 0:
            raise RuntimeError("Invalid raw mouse input packet")
        if packet.mouse.buttonUnion.buttons.flags & BUTTON_DOWN_FLAGS:
            # ceiling: an undelivered Raw Input click cannot invalidate a key
            # already being handled. Use one native mouse/keyboard event queue
            # if strict ordering between near-simultaneous inputs is required.
            self._generation += 1

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == WM_INPUT:
            try:
                self._read_mouse(lparam)
            except Exception as error:
                # ctypes callbacks cannot propagate errors through Win32. Mark
                # capture unusable so subsequent buffer/paste checks fail closed.
                self._error = error
            # Required cleanup for foreground raw input; also valid in background.
            return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)
        if message == WM_CLOSE:
            self._user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            self._hwnd = None
            self._user32.PostQuitMessage(0)
            return 0
        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _run_windows(self):
        registered_class = False
        registered_mouse = False
        instance = None
        class_name = f"SniptypeMouseInput-{id(self):x}"
        try:
            self._user32, kernel32 = _windows_api()
            instance = kernel32.GetModuleHandleW(None)
            # Retain the ctypes callback for the window's whole lifetime.
            window_proc = WNDPROC(self._window_proc)
            window_class = WNDCLASS(
                lpfnWndProc=window_proc, hInstance=instance, lpszClassName=class_name,
            )
            if not self._user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered_class = True
            self._hwnd = self._user32.CreateWindowExW(
                0, class_name, None, 0, 0, 0, 0, 0, -3, None, instance, None,
            )  # HWND_MESSAGE: hidden, never activates or changes keyboard focus.
            if not self._hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            device = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, self._hwnd)
            if not self._user32.RegisterRawInputDevices(
                ctypes.byref(device), 1, ctypes.sizeof(device),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            registered_mouse = True
            self._ready.set()
            message = wintypes.MSG()
            while not self._stopping.is_set():
                result = self._user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0:
                    if not self._stopping.is_set():
                        raise RuntimeError("Mouse input capture stopped unexpectedly")
                    break
                self._user32.TranslateMessage(ctypes.byref(message))
                self._user32.DispatchMessageW(ctypes.byref(message))
        except Exception as error:
            self._error = error
        finally:
            if registered_mouse:
                device = RAWINPUTDEVICE(0x01, 0x02, RIDEV_REMOVE, None)
                if not self._user32.RegisterRawInputDevices(
                    ctypes.byref(device), 1, ctypes.sizeof(device),
                ):
                    self._error = ctypes.WinError(ctypes.get_last_error())
            if self._hwnd is not None:
                self._user32.DestroyWindow(self._hwnd)
                self._hwnd = None
            if registered_class:
                if not self._user32.UnregisterClassW(class_name, instance):
                    self._error = ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
