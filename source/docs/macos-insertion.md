# macOS insertion path: paste timings, erase, secure input

Notes for [issue #27](https://github.com/rteoo/txt_xpander/issues/27): the
expansion insertion path (`TextInserter._paste_value`,
`TextExpander._erase_chars`) was tuned entirely against Windows timing. This
documents what the delays are for, which values macOS uses and why, and what a
real-host pass still has to confirm by hand.

> **STATUS: partially verified.** The pasteboard half was measured on this Mac
> (macOS 15, Darwin 25.5.0, Python 3.14.6) and the constants follow from that
> measurement. The **synthesized-keystroke half was not exercised**: it needs
> Input Monitoring *and* Accessibility granted to the running process, which is
> a TCC decision no script can make for itself. The manual matrix at the bottom
> is the remaining work, and it needs a human at a granted Mac.

## The sequence

Typing a trigger produces, in order:

1. **Erase** — one synthesized backspace per trigger character, on the listener
   thread, with `erase_key_delay` between them (`_erase_chars`).
2. **Snapshot** — read the current clipboard text, under the global paste lock.
3. **Set** — write the payload to the clipboard.
4. **Settle** — sleep `clipboard_settle_delay`, so the payload is really there
   before anything asks for it.
5. **Paste** — press the paste shortcut: Cmd+V on macOS, Ctrl+V elsewhere
   (`platform_support.paste_modifier_is_cmd`).
6. **Restore** — sleep `paste_restore_delay`, then put the snapshot back if the
   clipboard still holds our payload.

Steps 4 and 6 are the two guesses in the design. Step 4 guards against pasting
before the clipboard is populated; step 6 against restoring before the target
app has read it. Neither has a completion signal to wait on, on either OS.

## The values

Resolved by `platform_support.insertion_timings(settings)`; defaults per OS,
each key overridable from `settings.json`.

| Key | Windows | macOS | Linux |
| --- | --- | --- | --- |
| `clipboard_settle_delay` | 0.05 | **0.02** | 0.05 |
| `paste_restore_delay` | 0.12 | 0.12 | 0.12 |
| `erase_key_delay` | 0.01 | 0.01 | 0.01 |

An override that is not a number, is negative, or exceeds 2 s is ignored and
logged at startup — a delay written in milliseconds (`"erase_key_delay": 10`)
would otherwise freeze the listener thread for ten seconds per character.

### Why macOS settles faster

Measured on this host, 15 iterations per payload, using the app's own
`Clipboard` backend:

| Payload | `set_content` | readable with **zero** added delay |
| --- | --- | --- |
| plain, single line | ~13 ms | 15/15 |
| multi-line | ~12 ms | 15/15 |
| rich text (`osascript`) | ~12 ms | 15/15 |

`pbcopy` and `osascript` are separate processes that exit only after
NSPasteboard holds the data, so by the time `set_content` returns the payload is
already servable — and the subprocess round-trip has itself burned ~12 ms, more
than a fifth of the Windows settle window. Windows writes the clipboard
in-process with `SetClipboardData` in microseconds and needs its own margin;
copying that margin to macOS is latency for nothing. 20 ms is kept as slack, not
as a requirement.

Linux keeps the Windows value: `xclip`/`wl-copy` fork a daemon that owns the
selection, so tool exit does not prove the selection is servable yet.

### Why `paste_restore_delay` did not move

It is the only delay whose correct value depends on the *target application*
reading the pasteboard, and that could not be exercised here (see status). It
stays at the Windows value on every OS until someone measures it against real
targets; the key exists so that tuning it is a settings edit, not a patch.

macOS does have more natural slack than the number suggests: the restore path
reads the clipboard (~8 ms) and writes it (~12 ms) through subprocesses, so the
real window between Cmd+V and the snapshot landing is ~20 ms wider than on
Windows.

## Secure input

macOS Secure Keyboard Entry — Terminal's menu item, a focused password field,
the login window — is a separate gate from TCC and one the user cannot grant.
While it is on, the system drops synthesized events in both directions: the
listener never sees the trigger, and backspaces and Cmd+V never land.

`macos_permissions.secure_input_enabled()`
(`Carbon/IsSecureEventInputEnabled`) is checked in `_dispatch_expansion`
**before the erase**, and a positive answer aborts the expansion with a tray
notification (60 s cooldown) and a log line. Checking before the erase is the
point: the trigger is left exactly as the user typed it rather than partially
eaten by backspaces, and no synthesized key is emitted that some other app might
receive when focus moves.

The probe is best-effort by design — a missing symbol or a raising call reports
"not secure" and expansion proceeds as before, because a probe failure must not
disable the app. In practice the case usually never reaches this check at all:
secure input also blocks the listener, so the trigger is typically never
detected in the first place. The gate covers the window where secure input turns
on between detection and insertion.

## Remaining manual matrix

Run on a Mac with both Input Monitoring and Accessibility granted to the app
(tray → permissions entry if either is missing; a grant needs an app restart).

For each target — **TextEdit**, a **browser textarea** (Safari or Chrome),
**Mail**, and a **chat app** (WhatsApp Web) — expand:

- [ ] a single-line snippet
- [ ] a multi-line snippet
- [ ] a rich-text snippet

and check, each time:

- [ ] the trigger is **fully erased** (no leftover characters, nothing eaten
      from the text before it)
- [ ] the payload pastes **once**, complete, with newlines intact
- [ ] the previous clipboard is **restored** (single-line snippets only —
      multi-line deliberately does not restore; see the ceiling comment in
      `TextInserter._restore_clipboard`)
- [ ] typing the trigger **fast**, mid-sentence, produces the same result

Then the failure cases:

- [ ] Terminal with **Secure Keyboard Entry** on: the trigger stays on screen
      untouched, a tray notification explains why, nothing is pasted.
- [ ] a **password field**: same, and the field is never corrupted.

If a target needs a different `clipboard_settle_delay` or `paste_restore_delay`,
record the value and the target here and change the macOS default in
`platform_support._INSERTION_TIMING_DEFAULTS` — not the shared one.
