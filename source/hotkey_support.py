"""Normalize and route optional global workflow hotkeys.

The module owns chord state so the keyboard listener only asks whether one
keypress was consumed and dispatches no action-specific logic itself.
"""

from pynput import keyboard
from pynput.keyboard import Key, KeyCode

from i18n import N_


ACTIONS = ("open_manager", "edit_last", "toggle_enabled")
ACTION_LABELS = {
    "open_manager": N_("Abrir gerenciador"),
    "edit_last": N_("Editar último expandido"),
    "toggle_enabled": N_("Alternar expansão"),
}


def display_hotkey(binding):
    """Render persisted pynput syntax as a human-readable chord."""
    if not binding:
        return ""
    labels = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "cmd": "Win"}
    return "+".join(labels.get(part.strip("<>"), part.strip("<>").upper())
                    for part in binding.split("+"))


_TK_MODIFIER_KEYS = {
    "Control_L": "ctrl", "Control_R": "ctrl",
    "Shift_L": "shift", "Shift_R": "shift",
    "Alt_L": "alt", "Alt_R": "alt", "Option_L": "alt", "Option_R": "alt",
    "Meta_L": "cmd", "Meta_R": "cmd", "Super_L": "cmd", "Super_R": "cmd",
    "Win_L": "cmd", "Win_R": "cmd",
}


def capture_hotkey(keysym, state, windowing_system="win32", pressed_keys=()):
    """Translate a Tk key event to pynput syntax, without installing a listener."""
    if keysym in _TK_MODIFIER_KEYS or keysym in {"Tab", "ISO_Left_Tab"}:
        return None
    # Tk 8.6 win/tkWinKey.c maps Mod1 to NumLock, Mod2 to Alt;
    # win/tkWinPointer.c also reports ALT_MASK (generic/tkInt.h).
    # Aqua's macosx/tkMacOSXKeyEvent.c maps Command/Option to Mod1/Mod2.
    # X11 modifier slots are configurable: use observed modifier key events
    # there, plus Tk's platform-independent synthetic Alt/Meta masks.
    alt_mask = 0x20000 | (0x10 if windowing_system in {"win32", "aqua"} else 0)
    cmd_mask = 0x10000 | (0x8 if windowing_system == "aqua" else 0)
    held = {_TK_MODIFIER_KEYS[key] for key in pressed_keys if key in _TK_MODIFIER_KEYS}
    for mask, name in ((0x4, "ctrl"), (alt_mask, "alt"), (0x1, "shift"), (cmd_mask, "cmd")):
        if state & mask:
            held.add(name)
    if keysym in {"BackSpace", "Delete"} and not held:
        return ""
    parts = [f"<{name}>" for name in ("ctrl", "alt", "shift", "cmd") if name in held]
    key = keysym.casefold()
    if len(key) == 1:
        parts.append(key)
    else:
        aliases = {"return": "enter", "escape": "esc", "prior": "page_up",
                   "next": "page_down", "space": "space"}
        parts.append(f"<{aliases.get(key, key)}>")
    return "+".join(parts)

# KeyboardEvent.key names (the WebView's) that are modifiers on their own.
_DOM_MODIFIER_KEYS = frozenset({"Control", "Shift", "Alt", "Meta", "OS", "AltGraph", "CapsLock", "NumLock"})
# KeyboardEvent.key names for pynput's named keys.
_DOM_NAMED_KEYS = {
    "Enter": "enter", "Escape": "esc", "Backspace": "backspace", "Delete": "delete", "Insert": "insert",
    "Home": "home", "End": "end", "PageUp": "page_up", "PageDown": "page_down", " ": "space",
    "ArrowUp": "up", "ArrowDown": "down", "ArrowLeft": "left", "ArrowRight": "right",
    "Pause": "pause", "PrintScreen": "print_screen", "ContextMenu": "menu",
}


def dom_hotkey(key, code, *, ctrl=False, alt=False, shift=False, meta=False):
    """Translate a WebView ``keydown`` to pynput syntax, like :func:`capture_hotkey` does for Tk.

    Letters and digits come from ``code`` (``KeyM``, ``Digit1``), so Shift
    and the keyboard layout do not change what is stored. Returns None for a
    key that cannot finish a chord (a modifier alone, Tab), and ``""`` for
    Backspace or Delete with no modifier, which clears the binding.
    """
    if not isinstance(key, str) or key in _DOM_MODIFIER_KEYS or key == "Tab":
        return None
    held = [name for name, on in (("ctrl", ctrl), ("alt", alt), ("shift", shift), ("cmd", meta)) if on]
    if key in {"Backspace", "Delete"} and not held:
        return ""
    code = code if isinstance(code, str) else ""
    if code.startswith("Key") and len(code) == 4:
        name = code[3].casefold()
    elif code.startswith("Digit") and len(code) == 6:
        name = code[5]
    elif key in _DOM_NAMED_KEYS:
        name = f"<{_DOM_NAMED_KEYS[key]}>"
    elif len(key) > 1 and key[0] == "F" and key[1:].isdigit():
        name = f"<{key.casefold()}>"
    elif len(key) == 1:
        name = key.casefold()
    else:
        return None
    return "+".join([f"<{part}>" for part in held] + [name])


_MODIFIER_ALIASES = {
    Key.alt_l: Key.alt,
    Key.alt_r: Key.alt,
    Key.ctrl_l: Key.ctrl,
    Key.ctrl_r: Key.ctrl,
    Key.shift_l: Key.shift,
    Key.shift_r: Key.shift,
    Key.cmd_l: Key.cmd,
    Key.cmd_r: Key.cmd,
}
_MODIFIERS = frozenset({Key.alt, Key.ctrl, Key.shift, Key.cmd})


def _canonical_key(key):
    key = _MODIFIER_ALIASES.get(key, key)
    if isinstance(key, KeyCode) and isinstance(key.char, str):
        return KeyCode.from_char(key.char.casefold())
    return key


def _parse(binding):
    normalized = binding.strip().casefold()
    parsed = tuple(_canonical_key(key) for key in keyboard.HotKey.parse(normalized))
    return normalized, frozenset(parsed)


def normalize_hotkeys(value):
    """Return ``(bindings, invalid)`` for the three supported actions.

    Unknown actions are preserved by ``settings_support`` but ignored here.
    Empty strings disable an action. ``invalid`` maps rejected fields to a
    concise reason suitable for logging or a settings dialog.
    """
    bindings = {action: None for action in ACTIONS}
    invalid = {}
    if value is None:
        return bindings, invalid
    if not isinstance(value, dict):
        return bindings, {"hotkeys": "expected an object"}

    claimed = {}
    for action in ACTIONS:
        raw = value.get(action)
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str):
            invalid[action] = "expected a string or null"
            continue
        try:
            normalized, chord = _parse(raw)
        except (ValueError, TypeError):
            invalid[action] = "invalid hotkey"
            continue
        if not chord:
            invalid[action] = "empty hotkey"
            continue
        has_modifier = bool(chord & _MODIFIERS)
        has_non_modifier = bool(chord - _MODIFIERS)
        if not has_non_modifier:
            invalid[action] = "modifier-only hotkeys are not supported"
            continue
        if not has_modifier and any(isinstance(key, KeyCode) for key in chord):
            invalid[action] = "printable keys require a modifier"
            continue
        if (
            Key.ctrl in chord
            and Key.alt in chord
            and any(isinstance(key, KeyCode) for key in chord)
        ):
            invalid[action] = "Ctrl+Alt printable chords conflict with AltGr"
            continue
        if chord in claimed:
            invalid[action] = f"duplicates {claimed[chord]}"
            continue
        claimed[chord] = action
        bindings[action] = normalized
    return bindings, invalid


class HotkeyRouter:
    """Track normalized key state and dispatch configured workflow actions."""

    def __init__(self, bindings, dispatch):
        self._dispatch = dispatch
        self._chords = {}
        for action, binding in (bindings or {}).items():
            if action not in ACTIONS or not binding:
                continue
            _normalized, chord = _parse(binding)
            self._chords[action] = chord
        self._pressed = set()
        self._active = set()

    def press(self, key):
        """Record one press and return True when it belongs to a fired chord."""
        canonical = _canonical_key(key)
        self._pressed.add(canonical)
        consumed = False
        for action, chord in self._chords.items():
            if canonical in chord and chord <= self._pressed:
                consumed = True
                if action not in self._active:
                    self._active.add(action)
                    self._dispatch(action)
        return consumed

    def release(self, key):
        """Release one key, rearming every chord that contains it."""
        canonical = _canonical_key(key)
        self._pressed.discard(canonical)
        for action, chord in self._chords.items():
            if canonical in chord:
                self._active.discard(action)

    def reset(self):
        self._pressed.clear()
        self._active.clear()
