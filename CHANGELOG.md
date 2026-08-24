# Changelog

All notable changes to Txt Xpander are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [3.4.0] — 2026-08-24

Promotes `3.4.0` from beta to the stable channel. Optional voice input ships
default-off; a missing backend or a failed controller leaves expansion
unchanged.

### Added

- **Optional voice input** (default off): push-to-talk dictation, spoken
  triggers, and form-field fill. Balanced (Parakeet) and Accuracy (Qwen) are
  user-selectable; Accuracy is labeled slower and memory-heavy and always uses
  automatic language detection. Live streaming remains unavailable. Models
  download on demand into a non-roaming cache, resume from a verified byte
  range, and are SHA256-checked. A missing `transcribe-cpp` backend or a
  construction failure leaves expansion unchanged.
- Configurable dictation and voice-command push-to-talk shortcuts in Voice
  Settings, validated before save and applied without reloading the speech
  model.
- Release builds install an exact pinned voice dependency set and run an
  embedded runtime probe before promoting the staged Windows or macOS app.
- Native click-through, non-activating macOS recording panel so voice status
  does not steal focus from the target app.

### Changed

- The Windows and macOS build scripts exclude `torch`, `transformers`,
  `onnxruntime`, `cv2`, `torchvision`, `torchaudio`, and `scipy` so a dirty
  host environment cannot pull them into the packaged app.

### Fixed

- Releasing any required push-to-talk modifier ends the active hold exactly
  once; configured final keys are selectively suppressed on Windows and
  macOS without swallowing unrelated shortcuts.
- Voice profile changes now publish a final stable status after success,
  rollback, or terminal failure instead of leaving the UI in a loading state.
- Normal recordings no longer exhaust a 64-chunk callback queue after roughly
  one second. Buffered capture now uses stable 1,024-sample blocks and enforces
  the documented 30-second limit by sample count.
- When custom shortcuts overlap, the most-specific modifier chord wins no
  matter which action owns it.
- Tk-dependent tests skip cleanly when the host Tcl/Tk installation is
  unusable rather than failing during collection.

## [3.4.0-beta.3] — 2026-08-21

### Added

- Interrupted voice-model downloads now resume from a deterministic partial
  file when the server returns a valid byte range. Invalid or ignored ranges
  restart safely, while integrity failures discard the partial artifact.
- Release builds install an exact pinned voice dependency set and run an
  embedded runtime probe before promoting the staged Windows or macOS app.

### Changed

- The Accuracy/Qwen profile is user-selectable, clearly labeled as slower and
  memory-heavy, and locked to automatic language detection.
- The macOS recording indicator uses a click-through non-activating native
  panel so showing voice status does not steal focus from the target app.

### Fixed

- Releasing any required push-to-talk modifier ends the active hold exactly
  once; configured final keys are selectively suppressed on Windows and
  macOS without swallowing unrelated shortcuts.
- Voice profile changes now publish a final stable status after success,
  rollback, or terminal failure instead of leaving the UI in a loading state.
- Tk-dependent tests skip cleanly when the host Tcl/Tk installation is
  unusable rather than failing during collection.

## [3.4.0-beta.2] — 2026-08-14

### Added

- Dictation and voice-command push-to-talk shortcuts are configurable in the
  Voice Settings dialog, validated before saving, and applied without
  reloading the speech model.

### Fixed

- Normal recordings no longer exhaust a 64-chunk callback queue after roughly
  one second. Buffered capture now uses stable 1,024-sample blocks and enforces
  the documented 30-second limit by sample count.
- When custom shortcuts overlap, the most-specific modifier chord wins no
  matter which action owns it.

## [3.4.0-beta.1] — 2026-08-14

### Added

- **Optional voice input** (default off, beta): push-to-talk dictation,
  spoken triggers, and form-field fill. The module is implemented; live ASR
  is not proven and is not in the stable `v3.3.0` build. Models download on
  demand into a non-roaming cache. Only the Balanced profile is
  user-selectable; Accuracy and Live streaming stay in the catalog until they
  pass adoption gates. Enabling voice without the optional `transcribe-cpp`
  backend reports unavailable. A missing backend or a construction failure
  leaves expansion unchanged. Changing profile during a hold stops the
  microphone; Escape cancels native inference via `session.cancel()` and
  shutdown joins workers before unload; a form transcript binds to the form
  that was open at press; macOS restore waits for the captured app before
  Cmd+V. The expansion listener does not stop PortAudio. See
  `source/docs/voice-input-plan.md`.

### Changed

- The Windows and macOS build scripts exclude `torch`, `transformers`,
  `onnxruntime`, `cv2`, `torchvision`, `torchaudio`, and `scipy` so a dirty
  host environment cannot pull them into the packaged app.

## [3.3.0-beta] — 2026-07-23

This is the beta channel for the next feature release. The stable channel
remains `v3.2.1` until the full cross-platform test matrix and desktop smoke
tests pass.

### Added

- **Explicit stable and beta channels**: the app now identifies the running version and non-stable channel in the tray tooltip, tray menu and manager title. Windows beta installers include `-beta` in the filename and installed-app display name; macOS bundles carry the version and channel in `Info.plist`.
- **macOS build**: `build_release_macos.sh` produces `dist/Txt Xpander.app`, a menu-bar-only bundle (`LSUIElement` plus an accessory activation policy applied after Tk starts, since Tk otherwise forces the app into the Dock) with the icon converted to `.icns` at build time. The tray autostart toggle writes a LaunchAgent pointing at the bundle's binary.
- **macOS permission onboarding**: the app checks Input Monitoring and Accessibility at startup, links to the correct System Settings panes and requires a restart after grants change rather than claiming a refused listener recovered in-process.
- **macOS rich-text clipboard support**: rich snippets write plain text, HTML and RTF through an injection-safe AppleScript pasteboard record, with a logged plain-text fallback.
- **Mobile sync export**: the optional `sync_export_dir` setting compiles the static library and dynamic registry into a deterministic, versioned mobile bundle without invoking dynamic providers.

### Changed

- **macOS owns Tk on the main thread**: the tray attaches to Tk's `NSApplication` and runs detached, while the shared GUI marshaling contract remains the same as Windows.
- **macOS manager UI**: the manager follows light/dark appearance, uses native Aqua controls and avoids clipped toolbar and action rows.
- **Cross-platform CI definition**: the unit suite is configured for Windows, macOS and Linux on Python 3.12 and 3.14. Hosted runs remain a stable-promotion requirement; a beta may be prepared locally when hosted runners are unavailable.
- **Per-OS insertion timing**: clipboard settle, paste restore and erase delays use measured platform defaults with bounded settings overrides.
- **macOS beta architecture**: the current packaged beta is native ARM64 for Apple Silicon. Intel and universal builds require their own matching toolchain and verification.

### Fixed

- **macOS dialog-backed snippets own and return keyboard focus correctly**: ticker and form dialogs stay transparent until macOS confirms both that Txt Xpander is active and that the exact native popup window is receiving keyboard events; after submission, expansion waits until macOS confirms the original editor is frontmost before sending Cmd+V. Every handoff fails visibly after a bounded wait instead of dropping input or pasting into the wrong app. Previously `xfund` could ignore the first several ticker keystrokes, then paste into the hidden Tk root instead of the editor.
- **macOS: using the menu-bar menu no longer kills the app**: clicking the tray icon made AppKit run a nested menu-tracking loop on the main thread, where a Tk timer fired into Python with no valid thread state and aborted the process (`PyEval_RestoreThread`, "Txt Xpander quit unexpectedly"). Opening the menu, opening the snippet manager and quitting all work now. Windows behaviour is unchanged.
- Secure Keyboard Entry is checked before a trigger is erased and outside the listener hot path, so password fields keep the original typed text without adding per-keystroke framework calls.
- Static snippets and composed mapping triggers are preserved or confirmed before a dynamic trigger shadows them; editor delete/overwrite paths no longer discard a shadowed static value.
- Empty trigger keys are excluded consistently from every compiled index set.
- A corrupt per-user dynamic-registry entry no longer replaces a valid bundled entry.
- Rich-text RTF generation now handles astral Unicode characters and malformed scalar span payloads safely.
- The macOS release build converts the shipped 256px icon directly to `.icns`; current `iconutil` versions no longer reject a partial iconset before packaging starts.

### Technical

- The macOS startup-order test now mocks the Dock activation-policy call and asserts the complete startup sequence without reaching live AppKit from the unit runner.
- Build, Gatekeeper, signing and permission steps — including that rebuilding under ad-hoc signing invalidates Input Monitoring/Accessibility grants — are documented in the README.

## [3.2.1] — 2026-07-21

### Fixed

- **Pasted clipboard content no longer gains a blank line per break**: snippets that embed `%%clipboard-paste%%` receive the clipboard's text with CRLF line endings, and the Windows write site converted line endings a second time, turning every `\r\n` into `\r\r\n`. Copying multi-line text and expanding a snippet that quotes it now pastes exactly the breaks that were copied.
- **A failed paste no longer types multi-line snippets**: the typed fallback sends a real Enter for each newline, which submitted the message in a chat app and executed the line in a terminal. A multi-line snippet that cannot be pasted is now left on the clipboard with a tray notification to press Ctrl+V; single-line snippets still fall back to typing as before.

### Technical

- The app now logs when the clipboard holds neither the snippet nor the previous contents at restore time — the signature of a remote-desktop clipboard sync agent (NoMachine, RDP) overwriting the clipboard mid-paste, which the app was previously silent about.
- Multi-line snippets keep their existing behaviour of not restoring the previous clipboard, now as an explicit, documented branch rather than a side effect of the line-ending bug above.
- 306 tests pass, up from 300.

## [3.2.0] — 2026-07-20

### Added

- **"Iniciar com o sistema" tray toggle**: right-click the tray icon to create or remove the per-user autostart entry — Startup `.lnk` on Windows, LaunchAgent plist on macOS, `~/.config/autostart` entry on Linux — replacing the manual `shell:startup` instructions. The work runs off the menu thread so the tray never freezes, and failures are reported instead of silently claimed.
- **Snippet lists with value preview**: the static snippets and mapping items lists are now tables showing the trigger, a one-line value preview, and markers (`RT` for rich text, `%%` for variables). Notebook tab titles show item counts.

### Changed

- **Behavior change — the autostart checkbox now tells the truth**: it is checked only when the Startup entry actually launches *this* install. An entry left by a deleted `dist` folder, a removed interpreter, or a deleted checkout is detected as dead and repaired automatically at startup; an entry owned by another *live* install shows unchecked and is left alone (clicking the toggle repoints it here). Users running both a source checkout and the packaged release will see the box unchecked where it used to be misleadingly checked.
- **Single GUI architecture**: every dialog and the manager window now share one Tk root on a dedicated GUI thread, removing the crash/hang risk of two windows built on separate roots. The stock ticker prompt is a proper Tk dialog (the old `mshta`/VBScript popup is gone). Only one expansion dialog can be open at a time; a second trigger arriving mid-dialog is refused and reported like a cancel — nothing inserted, no terminator re-emitted.
- **Per-OS clipboard backend** (`clipboard_support.py`): Windows keeps the full ctypes backend (text, HTML, RTF); macOS/Linux get a plain-text backend (`pbcopy`/`pbpaste`, `wl-copy`/`wl-paste`, `xclip`, `xsel`), so the app imports and runs off Windows. POSIX rich-text pastes downgrade to plain text with a log line. Unverified on real macOS/Linux hosts; CI is Windows-only.
- Restoring a backup or importing a library now refreshes the manager's snippet lists immediately instead of showing the pre-restore library.

### Fixed

- **Pasted rich text with accented characters no longer truncates**: the Windows HTML-clipboard fragment offsets were computed in characters instead of UTF-8 bytes, cutting formatted pastes short whenever the snippet contained accents.
- A stale Startup entry no longer reads as "enabled" while starting nothing (or the wrong copy) at login.
- A GUI-thread failure can no longer leave an expansion worker blocked forever holding the dialog lock, and autostart worker errors are always surfaced instead of dying invisibly under `pythonw`.
- Blank snippet keys in hand-edited files no longer produce broken rows in the manager lists.

### Technical

- 296 tests pass, up from 210: GuiThread marshaling, modal-dialog serialization, clipboard backend selection and degradation, autostart install/read round-trips and absent/current/stale classification, tray autostart policy, and Treeview row rendering
- New modules: `gui_thread.py`, `clipboard_support.py`; autostart adapters live in `platform_support.py`
- Snippet file format is unchanged

## [3.1.0] — 2026-07-20

### Added

- **Rename built-in dynamic snippets from the manager**: each trigger in the dynamic snippets tab has a ✎ button (or double-click the trigger) to rename it. The rename is stored as a `trigger` field in the per-user `dynamic_snippets.json` override, keyed by the entry's stable id, so enabling/disabling and renaming stay independent and future bundled changes still reach the user. Collisions with another dynamic trigger, a static snippet, a mapping prefix, or a composed mapping trigger are blocked; shadowing risks warn first.
- **`%%trigger%%` references now resolve every snippet kind**: besides static snippets, a reference can point at a dynamic mapping trigger (`%%cpffulano%%`) or a runtime dynamic snippet (`%%xhj%%`, `%%xdolar%%`, `%%xcot%%`, `%%xlwapp%%`), whose callable is invoked and its result substituted. The `%%s` toolbar picker now lists all three kinds.

### Changed

- **The Data/Hora & Economia, Ações (Stocks) and WhatsApp tabs are now one "Snippets Dinâmicos" tab** with four sections, so every built-in dynamic snippet is managed in one place.
- **Mapping types are now a scrollable vertical list** instead of a single row of radio buttons, which clipped types once more than a handful existed.
- A snippet whose body references a *slow* dynamic trigger (BCB, stocks, WhatsApp) is now itself routed through the async expansion path, so resolving the reference never blocks the keyboard listener. Computed once at index-compile time; the per-keystroke path is unchanged.
- **Behavior change**: a `%%name%%` token matching a dynamic trigger or a dynamic mapping trigger is no longer treated as a form field, so it substitutes instead of prompting. A form field deliberately named after one of those must be renamed.
- A failing dynamic reference (network down) substitutes an empty string and notifies rather than aborting the containing expansion.
- Inline `%%xlwapp%%`/`%%xwapp%%` run their flow during resolution; the wa.me URL they place on the clipboard is overwritten by the containing snippet's own paste.

### Technical

- **Continuous integration**: the full test suite now runs on GitHub Actions (`windows-latest`, Python 3.12 and 3.14) for every pull request and push to `main`
- All 210 tests pass (35 added for renaming, universal references, and slow-path routing)
- Snippet file format is unchanged; the `dynamic_snippets.json` override gains an optional `trigger` field that older versions ignore

## [3.0.0] — 2026-07-16

Major release: user data now lives in a stable per-user directory, and Txt Xpander
ships as a proper per-user Windows installer. The library is migrated automatically
on first launch, but because the on-disk data location changes, this is a breaking
behavioral change and warrants a major version bump.

### Added

- **Per-user Windows installer** (Inno Setup, `installer/txt_xpander.iss`):
  - Installs to `%LOCALAPPDATA%\Programs\Txt Xpander` with **no administrator/UAC prompt** (`PrivilegesRequired=lowest`)
  - Stable `AppId` so future versions upgrade in place; detects a running instance via the app mutex
  - Optional desktop icon and "start with Windows" startup shortcut
  - **Uninstall never touches `~/.txt_xpander`** — user data survives uninstall by design
  - `build_installer.bat` compiles the packaged `dist` folder into `installer/Output/`
- **Stable per-user data directory** (`app_paths.py`): snippets, settings, backups, and logs now live under `~/.txt_xpander` instead of beside the executable (which, in the packaged build, sat inside OneDrive and was hostile to atomic writes)
  - `TXT_XPANDER_HOME` environment variable overrides the location
  - **Automatic one-time migration** copies a legacy exe-side `snippets.json` into the data dir on first launch, leaving the original untouched as a safety copy and dropping a breadcrumb
- **Rotating backups and corrupt-file recovery** (`backup_support.py`):
  - Backup before every save plus a once-daily startup backup, keeping the newest 30
  - Corrupt `snippets.json` is quarantined aside (never overwritten) and restored from the newest valid backup, falling back to sample defaults only as a last resort
  - Backups tab in the manager: restore, export, and import the library
- **File logging** to `~/.txt_xpander/logs`
- **JSON-driven dynamic snippet registry** (`dynamic_registry.py` + `dynamic_snippets.json`): dynamic triggers are configured from JSON with named providers instead of being hardcoded
- **Snippet manager improvements**: save-time validation, rename and duplicate actions, `Ctrl+S` to save, DPI awareness, and a notification-history viewer
- **Cross-platform seam** (`platform_support.py`) isolating OS-specific behavior behind a Windows backend
- **New test suites**: `test_app_paths`, `test_backup_support`, `test_data_safety`, `test_dynamic_registry`, `test_hotpath`, `test_platform_support`, `test_settings_support`, `test_validation_support`, and a manager-GUI construction smoke test

### Changed

- **User data location moved** out of the packaged app directory to `~/.txt_xpander` — migrated automatically, but a breaking change to where data is stored
- **Hot path** (`trigger_index.py`, `runtime_support.py`): expansion now runs off the keyboard-listener thread with deterministic matching, reducing input latency and race risk
- **`build_release.bat`** no longer syncs `dist` → `source`; the bundled `snippets.json` is an anonymized seed only, since real data lives in the per-user directory
- Comments and docstrings translated to English; `AGENTS.md` established as the canonical agent contract

### Fixed

- **Corrupt-backup poisoning**: recovery is hardened so a corrupt file copied into a fresh startup backup can no longer rank newest-by-mtime and defeat restoration; only valid files are ever backed up

### Technical

- All 175 tests pass
- New modules: `app_paths.py`, `backup_support.py`, `settings_support.py`, `dynamic_registry.py`, `validation_support.py`, `platform_support.py`
- Snippet file format is unchanged; existing libraries load as-is after migration

## [2.7] — 2026-03-30

### Added

- **Custom variables in snippets** (`%%variable_name%%` syntax):
  - **Snippet references**: `%%trigger%%` expands inline to the plain text of another snippet (one level deep, no recursion)
  - **Clipboard paste**: `%%clipboard-paste%%` inserts the current clipboard content at expansion time
  - **Form fields**: `%%fieldname%%` prompts the user with a labeled input dialog before inserting the snippet
  - Three new toolbar buttons in the snippet manager GUI to insert variable tokens:
    - `%%s` — searchable picker for snippet references
    - `%%cb` — insert clipboard-paste variable directly
    - `%%?` — prompt for a form field name to insert
- **Tray icon double-click** opens the "Gerenciar Snippets" window directly (Windows default action on `default=True` menu item)
- **Form-fill detection** in keyboard listener: snippets containing `%%field%%` variables are routed through the async path to show a form dialog
- **Form dialog** (`_show_form_dialog`): modal Tkinter window with labeled entry fields, OK/Cancel buttons, centered on screen
- **Variable support module** (`variable_support.py`):
  - `find_variable_names()` — extracts unique `%%var%%` names in order
  - `classify_variable()` — determines type (clipboard, snippet_ref, form_field)
  - `has_form_variables()` — checks if a snippet needs a form dialog
  - `resolve_inline()` — resolves clipboard + snippet refs (safe on hot path, no dialogs)
  - `resolve_form_variables()` — substitutes form field values after dialog collection
- **Rich text compatibility** for variables:
  - `rebuild_rich_text()` helper in `rich_text_support.py` handles variable resolution inside rich-text snippets
  - Spans are automatically clipped to new text length and HTML/RTF regenerated
- **32 new unit tests** in `test_variable_support.py` covering all variable functionality

### Changed

- **Expansion pipeline** now includes variable resolution stage:
  - Fast path (direct/dynamic snippets): resolve inline variables only, insert immediately
  - Slow path (rich-text, stock lookups, form-fill variables): show dialogs/fetch data, then resolve all variables
- **`expand_snippet()`** now calls `resolve_inline()` to handle `%%clipboard-paste%%` and `%%trigger%%` substitutions
- **`run_slow_snippet()`** extended to handle non-callable static snippets (those with form variables):
  - Detects form field names, shows input dialog, collects values, substitutes, inserts
  - Callable snippets (stock actions) continue with their existing flow
- **`on_press()`** keyboard listener detects form variables at trigger time and routes to slow path if needed

### Fixed

- **Tray icon double-click** now prevents opening duplicate manager windows by using Windows API `FindWindowW()` to detect an existing window and restore it instead
- **Snippet data loss on rebuild**: `build_release.bat` now syncs `dist\snippets.json` → `source\snippets.json` before PyInstaller runs, ensuring the bundled fallback copy in `_internal/snippets.json` contains the latest user snippets
- Circular reference protection in variable resolution (guards against `%%xself%%` referencing itself)

### Technical

- All 85 tests pass (53 existing + 32 new variable tests)
- No breaking changes to public API or snippet file format
- Backward compatible: existing snippets without variables work unchanged

## [2.6] — 2026-03-09

### Added

- `xlwapp` trigger: generate WhatsApp `wa.me` link from clipboard or fallback popup, insert into active field, keep link in clipboard
- `xpwapp` trigger: skip clipboard lookup, prompt immediately for phone and optional message, open browser with generated link
- Refactored WhatsApp runtime flow into shared `whatsapp_runtime_support.py` helper so all three triggers (`xwapp`, `xlwapp`, `xpwapp`) use consistent validation and URL generation

### Changed

- WhatsApp action modes now use a centralized helper for phone normalization, link generation, and error handling

## [2.5] — 2026-03-07

### Added

- `xwapp` dynamic snippet: read phone number from clipboard, create `wa.me` link, open in browser, keep link in clipboard
- Manual WhatsApp popup fallback when clipboard content is not a valid phone number
- WhatsApp reference tab in the snippet manager GUI showing trigger usage and examples
- `build_release.bat` improvements:
  - Safely stages builds to temporary directory before replacing `dist\Txt Xpander`
  - Preserves the packaged app's existing `snippets.json` during distribution updates
  - Adds optional Windows Startup shortcut creation after successful build

## [2.4] — 2026-03-06

### Added

- **Working PyInstaller standalone build** in `dist\Txt Xpander`:
  - Single-directory bundle with bundled Python runtime and all dependencies
  - User-editable `snippets.json` beside the executable (seeded on first run)
  - Standalone `.exe` with packaged icon and resources
- **Snippet insertion via clipboard** (clipboard-first behavior):
  - Copy snippet text to clipboard, paste with Ctrl+V
  - Better multiline snippet reliability (each line stays intact)
  - Improved compatibility with chat applications and text fields
- **Rich-text snippet support**:
  - Snippets can now contain formatting spans (bold, italic, underline, code, strikethrough)
  - Generates HTML and RTF payloads for clipboard compatibility
  - Rich-text editing and preview in the snippet manager GUI
  - Formatting toolbar with buttons: B, I, U, S, <>, ⌫ (clear)
  - Keyboard shortcuts: Ctrl+B (bold), Ctrl+I (italic), Ctrl+U (underline), Ctrl+Shift+C (code), Ctrl+Shift+S (strikethrough)
- `x-hj` dynamic snippet: ISO date format (YYYY-MM-DD)
- Improved snippet manager GUI:
  - Better layout and resizing behavior
  - Search/filter functionality for snippets and mappings
  - Notification history viewer (🔔 button)
  - Reference tabs for date/time, economy, stocks, and WhatsApp triggers

### Fixed

- Packaged startup: app now correctly seeds and persists `snippets.json` beside the executable
- Tray icon: fixed packaged app tray icon display and notifications
- Snippet manager: improved scrollbar and resize behavior

## [2.3] — 2026-02-XX

### Added

- Dynamic economic indicators (`xdolar`, `xselic`, `xipcam`, `xcdi`, etc.) via Brazilian Central Bank API
- Dynamic stock fundamentals (`xcot`, `xplucro`, `xcap`, etc.) via yfinance
- Background task runner for slow/async operations (stock lookups, API calls)
- Snippet manager GUI with tabs for static snippets, dynamic mappings, and reference information

### Changed

- Refactored core expansion logic into modular support files

## [2.0] — 2026-01-XX

### Added

- System tray icon with enable/disable toggle
- Keyboard listener using pynput
- Basic snippet expansion (direct triggers and dynamic patterns)
- `snippets.json` persistence
- Compiled trigger index for O(1) matching
- Support for dynamic mapping containers (`_cpf_numbers`, `_cnpj_numbers`, custom types)

---

## Format Notes

- **Version numbering**: Semantic versioning (MAJOR.MINOR.PATCH)
- **Release dates**: Formatted as YYYY-MM-DD
- **Unreleased section**: Collects changes from work-in-progress branches before they're released
- **Categories**:
  - `Added`: New features
  - `Changed`: Modifications to existing functionality
  - `Fixed`: Bug fixes
  - `Technical`: Internal improvements, test coverage, performance optimizations
  - `Deprecated`: Features that will be removed in a future version
  - `Removed`: Features that have been deleted

## Versioning Strategy

- **Stable channel**: the latest `vMAJOR.MINOR.PATCH` tag and non-prerelease artifact; currently `v3.4.0`.
- **Beta channel**: the next product version with an explicit `beta` channel label; none open after `3.4.0`.
- **Beta tags**: use `vMAJOR.MINOR.PATCH-beta.N` and mark the corresponding GitHub Release as a prerelease.
- **Promotion**: beta becomes stable only after the full supported-OS test matrix and packaged desktop smoke tests pass. Promotion removes the channel suffix without changing the tested product version.
