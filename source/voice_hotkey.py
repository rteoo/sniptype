"""Parse and observe push-to-talk chords without touching the expansion listener.

The expansion listener stays listen-only and must never swallow keys. Voice
uses a dedicated observer: OS filters suppress only the final key of a
configured chord so it does not type into the target. Press and release are
both required; auto-repeat is ignored by the controller, not here.
"""

from pynput.keyboard import Key, KeyCode


DEFAULT_DICTATION_HOTKEY = "ctrl+alt+space"
DEFAULT_COMMAND_HOTKEY = "ctrl+alt+shift+space"

MODE_DICTATION = "dictation"
MODE_COMMAND = "command"

_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "win": "win",
    "super": "win",
    "meta": "win",
    "cmd": "cmd",
    "command": "cmd",
}

_MODIFIER_KEYS = {
    Key.ctrl: "ctrl",
    Key.ctrl_l: "ctrl",
    Key.ctrl_r: "ctrl",
    Key.alt: "alt",
    Key.alt_l: "alt",
    Key.alt_r: "alt",
    Key.alt_gr: "alt",
    Key.shift: "shift",
    Key.shift_l: "shift",
    Key.shift_r: "shift",
    Key.cmd: "cmd",
    Key.cmd_l: "cmd",
    Key.cmd_r: "cmd",
}

try:
    _MODIFIER_KEYS[Key.cmd] = "cmd"
except AttributeError:
    pass


class Chord:
    """A modifier set plus one non-modifier key."""

    __slots__ = ("modifiers", "key", "spec")

    def __init__(self, modifiers, key, spec):
        self.modifiers = frozenset(modifiers)
        self.key = key
        self.spec = spec

    def __eq__(self, other):
        return (
            isinstance(other, Chord)
            and self.modifiers == other.modifiers
            and self.key == other.key
        )

    def __hash__(self):
        return hash((self.modifiers, self.key))


def parse_chord(spec):
    """Parse ``ctrl+alt+space`` into a Chord. Raises ValueError if unusable."""
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("empty hotkey")
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError("hotkey needs a modifier and a key")
    key = parts[-1]
    if key in _MODIFIER_ALIASES:
        raise ValueError("hotkey cannot end on a modifier")
    if len(key) != 1 and key not in {"space", "enter", "tab", "esc", "escape"}:
        if not key.startswith("f") or not key[1:].isdigit():
            raise ValueError(f"unsupported hotkey key: {key}")
    modifiers = []
    for part in parts[:-1]:
        alias = _MODIFIER_ALIASES.get(part)
        if alias is None:
            raise ValueError(f"unsupported modifier: {part}")
        modifiers.append(alias)
    if not modifiers:
        raise ValueError("hotkey needs a modifier")
    return Chord(modifiers, key, "+".join([*modifiers, key]))


def _key_name(key):
    modifier = _MODIFIER_KEYS.get(key)
    if modifier is not None:
        return modifier
    if key in (Key.space,):
        return "space"
    if key in (Key.enter,):
        return "enter"
    if key in (Key.tab,):
        return "tab"
    if key in (Key.esc,):
        return "esc"
    char = getattr(key, "char", None)
    if isinstance(char, str) and char:
        if char == " ":
            return "space"
        return char.lower()
    vk = getattr(key, "vk", None)
    if vk == 0x20:
        return "space"
    name = getattr(key, "name", None)
    if isinstance(name, str) and name:
        lowered = name.lower()
        if lowered in _MODIFIER_ALIASES:
            return _MODIFIER_ALIASES[lowered]
        return lowered
    return None


def chord_is_held(chord, held_modifiers, key_name):
    """True when ``key_name`` completes ``chord`` given the held modifiers."""
    return key_name == chord.key and held_modifiers >= chord.modifiers


class VoiceHotkeyMonitor:
    """Dedicated pynput listener that reports press/release of configured chords.

    Listener callbacks only update Python state and invoke the supplied
    press/release handlers. They never open devices, load models, or touch Tk.
    """

    def __init__(self, dictation_chord, command_chord, on_press, on_release, on_escape=None):
        self.dictation_chord = dictation_chord
        self.command_chord = command_chord
        self._on_press = on_press
        self._on_release = on_release
        self._on_escape = on_escape
        self._held = set()
        self._active_mode = None
        self._listener = None

    def start(self):
        from pynput import keyboard

        if self._listener is not None:
            return
        kwargs = {
            "on_press": self._handle_press,
            "on_release": self._handle_release,
        }
        # Selective swallow of the chord's final key, when the platform filter
        # exists. Unknown kwargs would break older pynput; only pass if present.
        self._listener = keyboard.Listener(**kwargs)
        if hasattr(self._listener, "suppress_event"):
            try:
                self._listener = keyboard.Listener(
                    on_press=self._handle_press,
                    on_release=self._handle_release,
                    win32_event_filter=self._win32_filter,
                )
            except TypeError:
                self._listener = keyboard.Listener(**kwargs)
        self._listener.start()

    def stop(self):
        listener = self._listener
        self._listener = None
        self._held.clear()
        self._active_mode = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass

    def _mode_for_key(self, key_name):
        if key_name is None:
            return None
        if chord_is_held(self.command_chord, self._held, key_name):
            return MODE_COMMAND
        if chord_is_held(self.dictation_chord, self._held, key_name):
            return MODE_DICTATION
        return None

    def _handle_press(self, key):
        name = _key_name(key)
        if name in {"esc", "escape"}:
            if self._on_escape is not None:
                self._on_escape()
            return
        if name in _MODIFIER_ALIASES.values():
            self._held.add(name)
            return
        if self._active_mode is not None:
            return
        mode = self._mode_for_key(name)
        if mode is None:
            return
        self._active_mode = mode
        self._on_press(mode)

    def _handle_release(self, key):
        name = _key_name(key)
        if name in _MODIFIER_ALIASES.values():
            self._held.discard(name)
            if self._active_mode is not None and not (
                chord_is_held(
                    self.command_chord if self._active_mode == MODE_COMMAND
                    else self.dictation_chord,
                    self._held | {name},
                    (
                        self.command_chord.key
                        if self._active_mode == MODE_COMMAND
                        else self.dictation_chord.key
                    ),
                )
            ):
                # Releasing a required modifier ends the hold.
                mode = self._active_mode
                self._active_mode = None
                self._on_release(mode)
            return
        if self._active_mode is None:
            return
        expected = (
            self.command_chord.key
            if self._active_mode == MODE_COMMAND
            else self.dictation_chord.key
        )
        if name == expected:
            mode = self._active_mode
            self._active_mode = None
            self._on_release(mode)

    def _win32_filter(self, msg, data):
        # Swallow only the final key of an armed chord so it does not type.
        vk = getattr(data, "vkCode", None)
        name = None
        if vk == 0x20:
            name = "space"
        elif isinstance(vk, int) and 0x41 <= vk <= 0x5A:
            name = chr(vk).lower()
        if name and self._mode_for_key(name) is not None and self._listener is not None:
            try:
                self._listener.suppress_event()
            except Exception:
                pass
        return True
