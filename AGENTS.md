# AGENTS.md

This file is the canonical agent contract for this repository — it guides Claude Code, Codex, and any other coding agent. `CLAUDE.md` is a thin pointer here; make all edits to project guidance in this file.

## Project Overview

Txt Xpander is a Windows system tray text expander. Typing a trigger word replaces the typed text with an expanded value, usually by placing the payload on the clipboard and sending Ctrl+V. By default expansion fires immediately on the last character of a matching trigger. An opt-in terminator mode (`settings.json` key `terminator_mode: true`, default off) instead expands only after a word-ending character (space/punctuation) and re-emits that character; Enter is not a terminator.

The app includes:

- A Tkinter snippet manager GUI.
- A pystray system tray app.
- A pynput keyboard listener.
- Static snippets stored in `snippets.json`.
- Runtime dynamic snippets for dates, Brazilian Central Bank indicators, stock data, and WhatsApp links.
- Rich-text snippets with HTML/RTF clipboard payloads.
- A PyInstaller onedir packaged release.

## Commands

Run commands from the repository root unless a command says otherwise.

**Install and run from source:**

```powershell
cd source
python -m pip install -r requirements.txt
pythonw txt_xpander.pyw
```

Use `python txt_xpander.pyw` instead when debug console output is useful.

**Run tests:**

```powershell
cd source
python -m unittest discover -s tests -v
python -m unittest tests.test_snippet_utils -v
```

**Build packaged release:**

```powershell
build_release.bat
```

**Build the macOS release (`.app` bundle):**

```bash
./build_release_macos.sh
```

**Build the Windows installer (Setup.exe):**

```powershell
build_release.bat      # produce dist\Txt Xpander first
build_installer.bat    # compile installer\TxtXpanderSetup-<version>.exe
```

`build_installer.bat` requires the Inno Setup 6 compiler (`ISCC.exe`) and compiles `installer\txt_xpander.iss`: a per-user install to `%LOCALAPPDATA%\Programs\Txt Xpander` (no admin), Start Menu/Desktop/Startup shortcuts, and a proper uninstaller that leaves `~/.txt_xpander` user data intact. Bump `MyAppVersion` and `MyAppChannel` in the `.iss` alongside the app release metadata.

Release channels are explicit. The published stable channel remains the latest
plain `vMAJOR.MINOR.PATCH` tag (`v3.3.0`); current source is `3.3.0` on the
`stable` channel. The app docstring owns `Version:` and
`Channel:` for the running build, and `installer\txt_xpander.iss` mirrors both
as `MyAppVersion` and `MyAppChannel`. Beta installers are named
`TxtXpanderSetup-<version>-beta.exe`; beta tags use
`vMAJOR.MINOR.PATCH-beta.N`. Do not promote beta to stable until the supported-OS
test matrix and packaged desktop smoke tests pass.

The build script backs up and restores the packaged `snippets.json`, stages the PyInstaller output, swaps `dist\Txt Xpander`, and can update the Windows Startup shortcut.

Build details: the release is `--onedir` (not `--onefile`); the hidden import `pystray._win32` is required; `snippets.json` and the icon are bundled as data files, but the user-editable copy in `dist\Txt Xpander\` is separate from the bundled fallback in `_internal\`.

`build_release_macos.sh` mirrors the same staging discipline (build into a temp dist, promote `dist/Txt Xpander.app` only on success, refuse to run while the app is running) and drops the Windows-only steps — no Startup shortcut (macOS autostart is the LaunchAgent the tray toggle writes), no packaged `snippets.json` to preserve. macOS specifics worth knowing before touching it: the `.icns` is generated directly from the 256px `source/txt_xpander.ico` with `sips`; do not restore the old partial-iconset path because current `iconutil` rejects it, and do not upscale the source to manufacture missing 512px artwork. The script asserts that the staged bundle both contains and references the generated icon. PyInstaller emits the selected Python interpreter's native architecture; the current Apple Silicon beta is ARM64-only, and Intel/universal artifacts require a matching toolchain plus separate verification. `LSUIElement` is written with `plutil` *after* the build because PyInstaller has no CLI flag for extra Info.plist keys, which breaks the seal PyInstaller put on the bundle and is why the script re-signs afterwards (ad-hoc, or `CODESIGN_IDENTITY` when set). Inside the bundle `sys._MEIPASS` is `Contents/Frameworks` and `sys.executable` is `Contents/MacOS/Txt Xpander`, so `get_runtime_resource_dir()` and `default_autostart_command()` both work unchanged — the LaunchAgent runs that binary directly and needs no `open -a` wrapper. An ad-hoc rebuild changes the bundle's cdhash and invalidates its TCC grants; consistently using the same stable signing identity preserves them, while changing identities invalidates them.

`LSUIElement` in the plist does not by itself keep the app out of the Dock: Aqua Tk sets `NSApplicationActivationPolicyRegular` on the shared `NSApplication` while creating the root, and a runtime policy beats the plist. `platform_support.hide_dock_icon()` puts it back to accessory and `run()` calls it **after** the root exists (order asserted in `test_tray_startup`) — reversing it earlier would just be overwritten. Failure there only warns: a Dock icon is cosmetic and must not take the tray down.

## Repository Layout

- `source\txt_xpander.pyw` is the main entry point. `TextExpander` owns startup, single-instance handling, snippet loading, keyboard events, tray actions, GUI windows, and snippet expansion.
- `source\trigger_index.py` compiles trigger lookup data (longest-first buckets, `form_triggers`). Preserve the indexed lookup path; do not replace it with full O(n) trigger scans in the keyboard hot path.
- `source\snippet_utils.py` loads, validates, merges, and atomically saves snippets.
- `source\app_paths.py` resolves the user data directory and handles one-time legacy migration.
- `source\backup_support.py` creates rotating backups and quarantines corrupt files.
- `source\settings_support.py` loads/saves the optional `settings.json`.
- `source\dynamic_registry.py` binds the `dynamic_snippets.json` registry to named providers.
- `source\variable_support.py` parses and resolves `%%var%%` tokens: clipboard-paste variables, form fields, and references to every snippet kind — static snippets, dynamic mapping triggers (`cpffulano`), and runtime dynamic snippets (the callable is invoked). Resolving a dynamic reference can block or open a dialog, so `resolve_inline` is worker-thread only.
- `source\rich_text_support.py` builds and normalizes rich-text payloads, including HTML/RTF generation and style-span handling.
- `source\runtime_support.py` contains insertion helpers (`TextInserter`), background task support, logging, and notification formatting.
- `source\clipboard_support.py` owns the clipboard backends and exports the `Clipboard` instance selected for the running OS. The Win32 ctypes bindings live behind that selection and never execute off Windows.
- `source\sync_export.py` compiles the static library plus dynamic registry into the versioned mobile bundle (`txt_xpander_bundle.json`) described by `source\docs\sync-design.md`. `build_bundle` is pure and provably never invokes a provider: dynamic triggers are mapped to a sentinel callable purely so `classify_variable` still returns `dynamic_ref` for them.
- `source\macos_permissions.py` probes the two macOS TCC grants the app depends on (Input Monitoring for the listener, Accessibility for the synthesized paste) and owns the PT-BR onboarding copy, the System Settings deep-links and the re-check decision. Inert off macOS: every check answers `unknown` and the decision layer then asks for nothing.
- `source\whatsapp_support.py` normalizes phone numbers and builds WhatsApp URLs.
- `source\whatsapp_runtime_support.py` runs the `xwapp`, `xlwapp`, and `xpwapp` action flows.
- `source\voice_support.py` owns the optional push-to-talk state machine. `voice_catalog.py` is the SHA256-pinned model list; `voice_models.py` downloads into a non-roaming cache (never `~/.txt_xpander`); `voice_dispatch.py` routes dictation, spoken triggers, and form fields without calling `_dispatch_expansion`; `voice_hotkey.py` is a dedicated observer, not the expansion listener. Voice is default-off. The module is implemented on `feat/voice-input`; live ASR is not proven. Only the Balanced profile is user-selectable. A missing voice backend or a failed `VoiceController` must leave expansion unchanged. Status: `source/docs/voice-input-plan.md`.
- `source\bcb_consultor.py` fetches Brazilian Central Bank API values with caching.
- `source\yf_stocks.py` wraps yfinance stock/fundamentals lookups. The ticker prompt itself is a Tk dialog in `txt_xpander.pyw` (`ask_ticker_input`), not in this module.
- `source\gui_thread.py` owns the process's only `tk.Tk()` root. Worker threads never touch Tk: they pass a callable to `GuiThread.call` (blocks, returns the result, re-raises errors) or `GuiThread.submit` (fire-and-forget), and a `root.after` pump runs it on the GUI thread. The keyboard listener must never call into it. *Which* thread that is depends on the OS: a dedicated worker thread on Windows (`ensure_started`), the main thread on macOS (`adopt_main_thread` + `run_mainloop`, selected by `platform_support.tk_runs_on_main_thread`). The marshaling contract is identical in both modes — only the thread the pump ticks on changes.
- `source\gui_support.py` contains GUI filtering and dialog helpers. The manager's single "Snippets Dinâmicos" tab (sections for Data/Hora, Economia, Ações and WhatsApp) is generated from the dynamic registry, not from hardcoded lists; each row can be enabled/disabled and renamed in place.
- `source\ui_theme.py` resolves the GUI's colors and fonts per OS. Every `bg=`/`fg=`/`font=` in `txt_xpander.pyw` goes through it (`ui = ui_theme.bind(root)` in a window builder, `ui_theme.theme()` in a tab builder); a literal `"#RRGGBB"` or `"Segoe UI"` back in the GUI is a regression, and `tests\test_ui_theme.py` fails on one.
- `source\tests\` contains unit tests.
- `source\docs\` contains planning notes for refactors and features, plus `audit-report.md` (full code audit) and `improvement-plan.md` (phased roadmap).
- `source\run_txt_xpander.bat` is the source-side launcher. It checks/install dependencies and starts the app with `pythonw`.
- `installer\txt_xpander.iss` is the Inno Setup script; `build_installer.bat` compiles the versioned installer directly into `installer\` (gitignored). The per-user install location is independent of where user data lives (`~/.txt_xpander`), which is what makes a Program-Files-style install safe.
- `build_release_macos.sh` is the macOS build script; it produces `dist/Txt Xpander.app` (menu-bar-only bundle).
- `dist\Txt Xpander\` is the packaged application folder. Treat `build\`, `dist\`, and `dist_staging\` as generated output unless the task is explicitly about packaging.

## Architecture Notes

The keyboard hot path is `TextExpander.on_press()`. It appends keystrokes to a buffer and checks the compiled trigger index for a suffix match on every keystroke. The index is pre-compiled at load time into buckets keyed by the trigger's last character (`direct_by_last_char`), ordered longest-first so a trigger that is a suffix of another cannot shadow it; it also precomputes `form_triggers` so the form-variable regex never runs per keystroke. The listener only detects and erases the trigger; all expansion work (callable execution including BCB fetches, variable resolution, dialogs, clipboard, paste) runs on a worker thread via `_run_expansion`, so no keystroke is ever blocked and a raising callable can never kill the listener. The buffer length always includes composed dynamic mapping triggers plus a margin (`TRIGGER_BUFFER_MARGIN`).

Expansion flow:

1. Detect a direct or dynamic trigger.
2. Route snippets with form variables to the slow async path.
3. Resolve inline variables such as `%%clipboard-paste%%` and `%%snippet_ref%%`.
4. Resolve form variables after collecting user input.
5. Insert text or rich text through clipboard paste for reliable multiline and chat-app behavior.

Dynamic snippets are described in `source\dynamic_snippets.json` (bundled) plus an optional per-user override at `~/.txt_xpander\dynamic_snippets.json`. `source\dynamic_registry.py` binds each entry's `provider` (`datetime`/`bcb`/`stock`/`whatsapp`) to a callable; `slow_snippets` and the manager's reference tabs are derived from this registry, not hardcoded. An unknown provider/method or a disabled entry is logged and skipped, never fatal. The callables (BCB/yfinance fetches, WhatsApp flows) stay in Python — only their metadata is data.

The JSON **key is the stable identity** (what the override file is keyed by); an optional `trigger` field renames what the user types, resolved by `effective_trigger(key, entry)`. The manager writes both the `enabled` and `trigger` fields to the user override keyed by that stable id, so renaming and toggling stay independent. Always bind and group by the effective trigger, never the raw key. Add a new dynamic trigger by adding a registry entry whose provider already exists; add a new provider by registering a factory in `PROVIDERS`.

Static snippets are merged under dynamic ones at load. `source\snippets.json` is an anonymized seed plus mapping containers; do not assume it is disposable fixture data. Mapping containers with keys prefixed by `_`, such as `_cpf_numbers`, `_cnpj_numbers`, and `_custom_codes`, create pattern-based triggers like `cpfalice`.

Rich-text snippets are dictionaries shaped like:

```json
{"__kind__": "rich_text", "text": "...", "spans": [...], "html": "...", "rtf": "..."}
```

Style spans are range based. When text changes, keep spans normalized and clipped through `rich_text_support.py` helpers.

## Runtime Notes

This is a Windows-first app using `pynput` for keyboard hooks, `pystray` for the tray icon, `tkinter` for GUI, `ctypes` for Win32 clipboard and mutex calls, and clipboard paste as the primary insertion path. OS-specific decisions are centralized in `source\platform_support.py` (paste modifier, single-instance strategy, autostart install/remove behind the tray toggle, the Windows-only `PYSTRAY_BACKEND` pin, and the tray/Tk threading seam); adding a macOS/Linux backend should extend that module rather than scatter `sys.platform` checks.

The GUI's *appearance* is a second seam, in `source\ui_theme.py`. The manager was written with a hardcoded light palette, and on macOS that made it unusable in dark mode: Aqua themes any widget the app leaves uncolored according to the system appearance, so an uncolored `tk.Entry` rendered as a black box inside a `#F4F6FA` frame. Three rules there are load-bearing, all with tests. **Windows resolves to the literals the GUI shipped with** — `palette("windows")` is the old table verbatim, and Aqua's system color names must never reach it (they are also why Linux takes the same literal palette: `systemTextColor` does not exist on X11). **A color the pre-change GUI did not set stays unset on Windows**: `entry_colors()`/`listbox_colors()`/`plain_button_colors()` return `{}` there and `text_native` resolves to `SystemButtonText`, because pinning those would swap the user's own highlight color for the app's blue. And **only opaque Aqua colors are usable**: `systemSecondaryLabelColor`, `systemSeparatorColor` and friends carry an alpha channel that Tk drops, handing back pure white — those tokens are fixed grays chosen per appearance instead. The appearance is probed by measuring `systemWindowBackgroundColor`'s luminance, re-run on every `bind()` so reopening a window picks up a switch; a failed probe answers "light", never dark.

`ui_theme` also owns the two places where Aqua's *geometry* differs, not just its colors. Aqua draws `tk.Button`/`tk.Checkbutton` itself: it ignores `-background`, keeps its own bezel, but honors `-foreground` — so painting a button is how you get an invisible label, and `button_colors()`/`checkbutton_colors()`/`toolbar_button_colors()`/`glyph_button_colors()` all answer `{}` on macOS (a `tests\test_ui_theme.py` AST check fails if any `tk.Button`/`tk.Checkbutton` in the GUI takes a color keyword directly). That bezel is also wider than the flat Win32 button the character widths were tuned against, which clipped the last button of every row: `button_width()` returns `0` on macOS so buttons size to their text, `manager_window_size` is wider there, and `stacked_toolbar_status` moves the format status onto its own line because nine native buttons already fill the editor pane.

Which event loop owns the main thread is the one place the two OSes genuinely diverge, because macOS gives Tk and AppKit only one main thread between them (issue #24, `source\docs\macos-threading.md`). On Windows `icon.run()` blocks the main thread and Tk lives on a worker. On macOS `TextExpander.run()` takes the mirror branch: the Tk root is created on the main thread first, `platform_support.tray_icon_options()` then hands pystray the `NSApplication` Tk just created (`darwin_nsapplication`, an **`Icon` constructor** kwarg — order matters, `sharedApplication()` would otherwise mint a bare one nobody runs), the tray goes up with `run_detached()`, and `gui.run_mainloop()` blocks. Consequence worth remembering: on macOS tray menu callbacks arrive *on* the GUI thread — and that thread is inside AppKit, not inside Tk.

That last point is load-bearing and cost a process abort to learn (issue #53). **Never call into Tcl/Tk from a Cocoa callback** — a tray menu action, an NSNotification observer, an NSTimer block. `_tkinter` keeps one global `tcl_tstate`, set while Python is inside a Tcl call and cleared by `LEAVE_TCL`; a Cocoa callback runs while `mainloop()` is already inside `ENTER_TCL`, so a Tcl call there clears that global with no `ENTER_PYTHON` frame left to restore it, and the *next* Tcl→Python callback dies with `Fatal Python error: PyEval_RestoreThread`, SIGABRT, no traceback. Note the delayed blast radius: the abort surfaces on an unrelated `after` timer, which is why the crash reports point at the pump rather than at the code that broke the invariant.

Three consequences, all with tests: `submit()` in main-thread mode **never** runs inline (`call()` cannot follow — its caller blocks, which on the GUI thread would deadlock); `stop()` from the GUI thread queues the teardown instead of scheduling it with `root.after`; and the pump stops draining as soon as the teardown runs, so nothing executes against a destroyed root. Cocoa callbacks may touch Python state only — the pump does the Tk work from inside the Tk loop, where the invariant holds. A guard built the other way (pausing the pump from an `NSMenuDidBeginTracking` observer) *caused* the crash on every menu open, because pausing meant calling `after_cancel` from a Cocoa frame.

Accessory-mode Tk can also paint a Toplevel before Cocoa has activated Txt Xpander or made that Toplevel's native window key. A blue entry border is not proof that physical keys have a destination: the ticker prompt visibly dropped several initial characters while the previous application remained active. Expansion dialogs use `gui_support.focus_modal_input()` after centering: the Toplevel stays transparent through `NSApplicationDidBecomeActiveNotification`, then `platform_support.focus_tk_window_when_ready()` resolves its exact `NSWindow` through Tk's exported drawable bridge and waits for `NSWindowDidBecomeKeyNotification` before revealing it. On close, `_run_modal_dialog()` observes `NSWorkspaceDidActivateApplicationNotification` and the expansion worker waits for the original editor to become frontmost before it may synthesize Cmd+V. All three handoffs have bounded failure paths; never replace a native readiness barrier with a fixed sleep.

macOS gates both directions of the app behind TCC and reports neither failure to Python: an untrusted `pynput` listener *starts*, stays alive and never delivers a key (one line on stderr, invisible under `pythonw`), and a synthesized Cmd+V is dropped silently. So the state is probed explicitly at startup on a worker thread — `IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)` for **Input Monitoring**, `AXIsProcessTrusted()` for **Accessibility** — and cached in `_macos_permission_status`, which the tray entry reads (never a probe: pystray re-evaluates `visible=` on every render). Three rules are load-bearing, all with tests. Only an explicit **denied** prompts the user; `unknown` (an old macOS, a missing symbol) is logged and never nags, because a grant the app cannot verify is a demand the user cannot satisfy. The re-check **never reports the app as working** — the frameworks read TCC at process start, so a refused listener stays dead for this process's lifetime and the only honest success message asks for a restart. And the deep-links matter: pynput's own stderr warning says "accessibility clients", inherited from the pre-Catalina API, but the global listener is gated by Input Monitoring — following that wording sends the user to the wrong pane.

macOS also has a gate the user cannot grant: **Secure Keyboard Entry**, which makes the system drop synthesized events in both directions. `macos_permissions.secure_input_enabled()` (`Carbon/IsSecureEventInputEnabled`) is consulted in `_dispatch_expansion` **before `_erase_chars`**, and that order is load-bearing with a test: checking after the erase would leave a half-eaten trigger and emit backspaces that a later-focused app could receive. A failed probe answers "not secure" — it must never disable expansion.

The three delays in the insertion path (`clipboard_settle_delay`, `paste_restore_delay`, `erase_key_delay`) are per-OS defaults resolved by `platform_support.insertion_timings(settings)`, each overridable from `settings.json`; an override that is not a finite number in `[0, 2]` seconds is ignored and logged (a delay written in milliseconds would freeze the listener thread). macOS settles faster (0.02 vs 0.05) because `pbcopy`/`osascript` exit only after NSPasteboard holds the payload, measured on a real host — `source/docs/macos-insertion.md` holds the numbers, the reasoning, and the manual paste matrix that still needs a granted Mac.

The autostart entry is classified, not just probed for existence: three writers own the same Startup entry (the tray toggle, `build_release.bat`, the Inno Setup `startup` task), so `classify_autostart` compares the entry's argv against `default_autostart_command()` and yields absent/current/stale. Two rules are load-bearing, both with tests. Reading the entry costs a PowerShell round-trip on Windows, and pystray re-evaluates `checked=` on every menu render — so the app resolves once at startup on a worker thread, caches the result in `_autostart_state`, and the menu only reads the cache. Repair is narrow: an entry whose target no longer exists is rewritten to the running copy, but one pointing at another *installed* copy is left alone and shown unchecked, because a source checkout and the packaged release legitimately coexist.

Clipboard access goes through `source\clipboard_support.py`, which picks a backend at import time: `WindowsClipboard` (ctypes user32/kernel32, text + HTML + RTF) on Windows, `PosixClipboard` (`pbcopy`/`pbpaste`, `wl-copy`/`wl-paste`, `xclip` or `xsel` via subprocess) elsewhere. The `WinDLL` setup only executes on Windows, so `runtime_support` imports cleanly off Windows. Use the module-level `Clipboard` instance — never a backend class directly. A desktop with no clipboard tool logs a warning and returns failure instead of crashing. Rich text on the POSIX backend is macOS-only: `pbcopy` cannot carry HTML, so a rich payload is written by piping a generated `set the clipboard to {«class utf8»:…, «class HTML»:…, «class RTF »:…}` record into `osascript -` (`mac_rich_clipboard_script`). Every flavor is a hex `«data …»` literal, which is what makes quotes, backslashes and newlines in a snippet un-injectable; the HTML flavor carries its own `<meta charset="utf-8">` because NSPasteboard hands the bytes over untouched. PyObjC's `NSPasteboard` would be the direct API but is a new runtime dependency for one call site, so the subprocess route wins. A failed `osascript` run leaves the previous clipboard intact and falls back to the plain-text `pbcopy` write (logged once per session); Linux still downgrades to plain text with its own once-per-session log line. Two constraints there are load-bearing, both with regression tests: the copy path must **never** capture the tool's stdout (`xclip`/`wl-copy` fork a daemon that owns the selection and inherits the pipe — reading it to EOF hangs the paste, and `timeout=` does not bound the wait), and the tool lookup re-resolves while none is found, so a tray session that outlives a missing tool recovers without a restart (`osascript` is resolved per rich paste for the same reason). `osascript`'s stderr *is* read, deliberately: it exits instead of forking a selection-owning daemon, and the AppleScript error is the only diagnostic a failed pasteboard write leaves behind.

Three constraints in the insertion path are load-bearing, all with regression tests. **CRLF conversion at the write site is idempotent** (`normalize_clipboard_newlines`): CF_UNICODETEXT is a CRLF format, but text arriving *from* the clipboard already carries CRLF — every `%%clipboard-paste%%` substitution does — and a blind `\n` → `\r\n` doubles it, pasting an extra blank line per break. **The typed fallback never types multi-line text**: pynput sends a real Enter per newline, which submits in a chat app and executes in a terminal, so a failed paste leaves the payload on the clipboard and notifies instead. **Multi-line snippets deliberately do not restore the previous clipboard** — the old CRLF comparison skipped them by accident, and restoring is an unobservable race (Windows gives no "the target read the clipboard" signal for real data), so re-enabling it could paste the snapshot in place of the snippet. `TextInserter._restore_clipboard` logs when the clipboard holds neither the payload nor the snapshot, which is the signature of a remote-desktop sync agent co-writing it; that warning is the evidence needed before changing any of the above. Delayed rendering (`SetClipboardData(NULL)` + a `WM_RENDERFORMAT` pump on the existing GUI thread) is the named upgrade that would make restore timing observable.

Single-instance enforcement uses the Win32 mutex `Local\TxtXpanderSingleton` on Windows; other platforms use a PID lockfile in the data dir.

Network-backed helpers use short caches: BCB lookups cache for about 300 seconds and yfinance stock fundamentals cache for about 600 seconds.

## Snippets File Safety

`snippets.json` is user data. It lives in the per-user data directory resolved by `source\app_paths.py`: `TXT_XPANDER_HOME` if set, otherwise `~/.txt_xpander`. Layout: `snippets.json`, `settings.json` (optional), `backups\`, `logs\`. The committed `source\snippets.json` is an **anonymized seed only** — do not add personal data to it. On first launch the app migrates a legacy exe-side `snippets.json` (from older builds) into the data dir, leaving the legacy file untouched; if none exists it seeds from the bundled sample.

The data layer already protects the library and the app must keep these guarantees:

- Every `save_snippets` takes a rotating backup of the prior file first (newest 30 kept in `backups\`) and returns success/failure; GUI call sites surface failures and roll back in-memory state.
- A corrupt `snippets.json` is quarantined (`snippets.corrupt-<ts>.json`) and restored from the newest **valid** backup — never overwritten with defaults while a backup exists.
- A corrupt file is never copied into the backup set (it could otherwise rank newest by mtime and defeat recovery).
- A static snippet whose name collides with a dynamic trigger is never dropped by a save. `merge_snippets` is `{**static, **dynamic}`, so the callable replaces the static value in the merged map the app saves from; `find_shadowed_statics` records those values at load and `build_saveable_snippets(snippets, preserved)` writes them back. Every path that creates the collision (static editor, enable toggle) asks for confirmation first, and the dynamic snippet is what expands.
- `backup_support.py` owns backup/quarantine helpers; `app_paths.py` owns path resolution and migration; `settings_support.py` owns `settings.json`.

`build_release.bat` no longer syncs `dist`→`source` or restores data into `dist` (user data is not in `dist` anymore); it keeps a one-time safety copy of any pre-existing packaged `snippets.json`. The optional `settings.json` key `mirror_dir` makes each successful save also copy to a write-only mirror.

The optional key `sync_export_dir` turns on the mobile sync bundle: every path that changes the live library (`save_snippets`, `restore_backup`, `import_library`, and both registry writers) calls `export_sync_bundle()`, which re-reads `snippets.json` and the registry **from disk** — `self.snippets` is stale between a restore/import write and its reload, and `self.dynamic_registry` is reassigned only after the registry writers persist. Absent key = feature off, zero behavior change. Unlike `mirror_dir`, a missing export directory is **never created**: a typo'd path would otherwise silently publish the user's full plaintext CPF/CNPJ library somewhere they never chose. Skip-if-unchanged is driven by `~/.txt_xpander\sync_export.state` (content digest excluding `exported_at`/`generator`, plus the recorded path and an existence check) so the bundle is not rewritten on every save; the export is best-effort and never turns a persisted save into a reported failure.

## Testing Guidance

The test suite is under `source\tests\` and uses `unittest`. Source modules are imported as flat sibling files from `source\`, not as an installed package. Tests are designed to avoid a running app instance and should mock Windows APIs, clipboard, dialogs, browser calls, and network-dependent behavior where needed.

Use focused tests for narrow changes and run the full suite before finalizing changes that touch trigger detection, snippet persistence, variable resolution, rich text, runtime insertion, or WhatsApp flows.

Never probe Tk availability by building a throwaway `tk.Tk()` in the test process. On macOS Tk 9.0.3 a root created and destroyed outside any mainloop leaves the Aqua interpreter in a state where a *later* root destroyed from inside an `after` callback traps the whole runner (SIGTRAP, no Python traceback). `test_gui_thread` probes out of process for exactly this reason; the app itself is unaffected because it only ever builds one root.

Temporary test artifacts belong in `source\tests\tmp\`, which is gitignored.

There is no repo-local `pyproject.toml`, `pytest`, `ruff`, `black`, `mypy`, or `tox` configuration at the time of writing.

## Coding Guidance

- Prefer small support modules over expanding `TextExpander` further when adding isolated behavior.
- Keep keyboard listener work fast and deterministic.
- Preserve atomic JSON writes via `os.replace`.
- Avoid persisting runtime-only dynamic snippets.
- Keep all GUI work on the shared GUI thread via `gui_thread.GuiThread`. Never create a second `tk.Tk()`, and never assume which thread the root is on — go through `call`/`submit`.
- Keep slow snippet behavior on background paths.
- Treat clipboard contents as user state; restore or preserve it according to the existing action-specific behavior.
- Use existing helper modules before introducing new abstractions.
- This is a Windows-first app. Be careful with changes involving `pythonw`, `.pyw`, `ctypes`, tray behavior, keyboard hooks, Startup shortcuts, and PyInstaller data paths.

## Dependencies

Runtime dependencies are listed in `source\requirements.txt`:

- `pynput`
- `pystray`
- `Pillow`
- `yfinance`

`source\requirements.txt` holds exactly these four runtime dependencies. Voice capture (`sounddevice`) and `transcribe-cpp` are optional: missing them leaves expansion unchanged and voice unavailable. PyInstaller is needed to build releases and is installed separately (`pip install pyinstaller`); it is not in `requirements.txt`.

## Agent Workflow

Before changing behavior, read the relevant support module and nearby tests. For changes in `txt_xpander.pyw`, also check whether the behavior already has extracted helpers in `source\*_support.py`.

When editing:

- Keep changes scoped to the requested behavior.
- Add or update tests in `source\tests\` for behavior changes.
- Do not modify generated build artifacts unless the task is explicitly about packaging or release output.
- Do not edit user snippets casually. If a task requires snippet data changes, explain the risk and preserve a backup.
- `Txt Xpander.spec` hardcodes absolute repo paths, but it is regenerated by `build_release.bat` (`--specpath`), so do not hand-edit it expecting the change to survive a build.
- The live user library lives in `~/.txt_xpander\snippets.json`, not in `dist`. The committed `source\snippets.json` is an anonymized seed. See `source\docs\audit-report.md` and `source\docs\improvement-plan.md` for the known-issues backlog and the phase status before "fixing" something that is already documented or already done.
