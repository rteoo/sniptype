"""Normalize and route optional global workflow hotkeys.

The module owns chord state so the keyboard listener only asks whether one
keypress was consumed and dispatches no action-specific logic itself.
"""

from pynput import keyboard
from pynput.keyboard import Key, KeyCode


ACTIONS = ("open_manager", "edit_last", "toggle_enabled")

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
