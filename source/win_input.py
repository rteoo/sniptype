"""Batched, self-tagged keyboard injection for Windows.

pynput's ``Controller`` issues one ``SendInput`` call per key event. Sniptype's
erase used to pair that with a sleep per backspace, on the keyboard listener
thread. That thread is also the one pumping the ``WH_KEYBOARD_LL`` hook, so
every sleep froze keyboard input system-wide, and a long enough stall makes
Windows skip the hook (events missed) or silently remove it.

``SendInput`` with an array is documented to insert the events serially and
without interleaving other keyboard or mouse input. One call per erase and one
per paste chord therefore removes the sleeps and closes the window where a
physical key could land between two backspaces, or between Ctrl down and V
(which would turn the user's next key into a Ctrl shortcut).

Every event carries :data:`INJECTION_TAG` in ``dwExtraInfo`` so the listener
can ignore its own synthesized keys (see :func:`is_own_event`) instead of
feeding a Ctrl+V into the trigger buffer or the hotkey router.

Importable anywhere; the ctypes bindings are only created on Windows.
"""

import sys

# "SNIP" in ASCII. Arbitrary, but must be non-zero: 0 is what every other
# injector (pynput included) leaves in dwExtraInfo.
INJECTION_TAG = 0x534E4950

VK_BACK = 0x08
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_NUMPAD0 = 0x60
VK_DECIMAL = 0x6E
VK_DIVIDE = 0x6F
MAPVK_VK_TO_CHAR = 2

# Numpad keys whose character does not depend on the layout. pynput derives a
# key's char from its scan code; with NumLock on the numpad digits share scan
# codes with the navigation keys (so they arrive with no char), and the numpad
# '/' loses its extended flag and reads as whatever key owns scan 0x35 (';' on
# ABNT2). '*', '+' and '-' already arrive correctly.
NUMPAD_CHARS = {VK_NUMPAD0 + digit: str(digit) for digit in range(10)}
NUMPAD_CHARS[VK_DIVIDE] = "/"

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _USER32 = ctypes.WinDLL("user32", use_last_error=True)

    _KEYEVENTF_KEYUP = 0x0002
    _INPUT_KEYBOARD = 1
    _MAPVK_VK_TO_VSC = 0

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class _INPUT_UNION(ctypes.Union):
        # MOUSEINPUT is the largest member; it must be present so sizeof(INPUT)
        # matches what SendInput validates cbSize against.
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("value", _INPUT_UNION)]

    _USER32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    _USER32.SendInput.restype = wintypes.UINT
    _USER32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    _USER32.MapVirtualKeyW.restype = wintypes.UINT
    _USER32.VkKeyScanW.argtypes = (wintypes.WCHAR,)
    _USER32.VkKeyScanW.restype = ctypes.c_short
    _USER32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    _USER32.GetAsyncKeyState.restype = ctypes.c_short
    _USER32.GetForegroundWindow.argtypes = ()
    _USER32.GetForegroundWindow.restype = wintypes.HWND
    _USER32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _USER32.GetKeyboardLayout.argtypes = (wintypes.DWORD,)
    _USER32.GetKeyboardLayout.restype = wintypes.HKL
    _USER32.MapVirtualKeyExW.argtypes = (wintypes.UINT, wintypes.UINT, wintypes.HKL)
    _USER32.MapVirtualKeyExW.restype = wintypes.UINT


def backspace_events(count):
    """``count`` backspace press/release pairs, as ``(vk, is_press)``."""
    events = []
    for _ in range(count):
        events.append((VK_BACK, True))
        events.append((VK_BACK, False))
    return events


def paste_chord_events(v_vk):
    """Ctrl down, V down, V up, Ctrl up."""
    return [(VK_CONTROL, True), (v_vk, True), (v_vk, False), (VK_CONTROL, False)]


def paste_vk():
    """Virtual-key code for the character ``v`` in the calling thread's layout.

    Mirrors pynput's ``press('v')`` (``VkKeyScan``) so the chord matches what
    was sent before; falls back to the letter's VK code on a failed lookup.
    """
    result = _USER32.VkKeyScanW("v")
    if result == -1:
        return ord("V")
    return result & 0xFF


def send_key_events(events):
    """Inject ``events`` in one ``SendInput`` call; True if all were inserted.

    ``False`` means Windows blocked the input — typically UIPI, when the
    focused window runs elevated and Sniptype does not.
    """
    if not events:
        return True
    inputs = (_INPUT * len(events))()
    for slot, (vk, is_press) in zip(inputs, events):
        slot.type = _INPUT_KEYBOARD
        slot.value.ki = _KEYBDINPUT(
            wVk=vk,
            wScan=_USER32.MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC),
            dwFlags=0 if is_press else _KEYEVENTF_KEYUP,
            time=0,
            dwExtraInfo=INJECTION_TAG,
        )
    sent = _USER32.SendInput(len(events), inputs, ctypes.sizeof(_INPUT))
    return sent == len(events)


class BatchKeyboard:
    """The two injections the hot path needs, each as one atomic batch."""

    def erase(self, count):
        return send_key_events(backspace_events(count))

    def paste(self):
        return send_key_events(paste_chord_events(paste_vk()))


def ctrl_or_alt_held():
    """True while Ctrl or Alt (AltGr included) is down, as pynput reads it."""
    state = _USER32.GetAsyncKeyState(VK_CONTROL) | _USER32.GetAsyncKeyState(VK_MENU)
    return bool(state & 0x8000)


def layout_decimal_char():
    """The character VK_DECIMAL types in the foreground window's layout.

    ',' on ABNT2, '.' on US. The layout is per thread and follows the user's
    input-language switch, so it is read on each press from the thread that
    receives the key. These are non-blocking user32 reads (no message is
    sent), and only a numpad decimal press pays for them, so no cache.
    """
    thread = _USER32.GetWindowThreadProcessId(_USER32.GetForegroundWindow(), None)
    code = _USER32.MapVirtualKeyExW(VK_DECIMAL, MAPVK_VK_TO_CHAR, _USER32.GetKeyboardLayout(thread))
    if not code or code & 0x80000000:  # unmapped, or a dead key
        return None
    return chr(code & 0xFFFF)


def typed_char(vk, char):
    """The character a key types, correcting pynput for Windows numpad keys.

    ``char`` is pynput's translation and is returned unchanged for every key
    outside the numpad table, before touching user32: this runs on the
    listener thread for every press. With Ctrl or Alt held a numpad key types
    nothing (Alt+digits compose an Alt code), matching how pynput reports
    Ctrl+digit on the top row.
    """
    if vk not in NUMPAD_CHARS and vk != VK_DECIMAL:
        return char
    if ctrl_or_alt_held():
        return None
    if vk == VK_DECIMAL:
        return layout_decimal_char()
    return NUMPAD_CHARS[vk]


def is_own_event(data):
    """True for a ``KBDLLHOOKSTRUCT`` this module injected."""
    return (data.dwExtraInfo or 0) == INJECTION_TAG


def listener_event_filter(_msg, data):
    """pynput ``win32_event_filter``: hide our own keys from the listener.

    Returning ``False`` only stops pynput from dispatching the event to
    ``on_press``/``on_release``; the key still reaches the focused app.
    Runs inside the hook procedure, so it must stay trivial.
    """
    return not is_own_event(data)
