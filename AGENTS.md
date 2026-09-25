# AGENTS.md

This file is the canonical agent contract for this repository — it guides Claude Code, Codex, and any other coding agent. `CLAUDE.md` is a thin pointer here; make all edits to project guidance in this file.

## Project Overview

Sniptype is a Windows system tray text expander. Typing a trigger word replaces the typed text with an expanded value, usually by placing the payload on the clipboard and sending Ctrl+V. By default expansion fires immediately on the last character of a matching trigger. An opt-in terminator mode (`settings.json` key `terminator_mode: true`, default off) instead expands only after a word-ending character (space/punctuation) and re-emits that character; Enter is not a terminator.

Sniptype accepts text/keyboard input only. Voice capture, transcription, model management, recording history, and voice controls belong to the independent Snipvoice project at `../snipvoice`. Do not add voice listeners, microphone permissions, or transcription dependencies back to Sniptype. Previously published binaries retain their historical behavior until rebuilt and released.

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
pythonw sniptype.pyw
```

Use `python sniptype.pyw` instead when debug console output is useful.

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
build_release.bat      # produce dist\Sniptype first
build_installer.bat    # compile installer\Output\SniptypeSetup-<version>.exe
```

`build_installer.bat` requires the Inno Setup 6 compiler (`ISCC.exe`) and compiles `installer\sniptype.iss`: a per-user install to `%LOCALAPPDATA%\Programs\Sniptype` (no admin), Start Menu/Desktop/Startup shortcuts, and a proper uninstaller that leaves `~/.sniptype` user data intact. Bump `MyAppVersion` and `MyAppChannel` in the `.iss` alongside the app release metadata.

**Build the Microsoft Store package (MSIX):**

```powershell
build_release.bat                  # produce dist\Sniptype first
python packaging\build_msix.py     # write dist\msix\Sniptype-<version>.0-x64.msix
```

`packaging\build_msix.py` needs `makeappx.exe` from the Windows SDK (or `SNIPTYPE_MAKEAPPX`). The upload is unsigned; the Store signs it on ingestion. The package identity (`Strateo.SnipType`, publisher `CN=95CECFD0-…`, display name `SnipType`) is the Partner Center reservation and is hardcoded; Partner Center rejects a package whose `DisplayName` differs. The package version is the docstring `Version:` plus a Store-reserved `.0`, and Store versions must strictly increase, so a beta and its stable release cannot share a version. The manifest declares `runFullTrust` (restricted; Partner Center asks for a justification) and an opt-in startup task: under package identity (`platform_support.is_msix_packaged()`) the tray's "Iniciar com o sistema…" opens Settings > Startup apps instead of writing a Startup `.lnk`, because packaged AppData writes are virtualized and the install path moves on every update. User data stays in `~/.sniptype`, which is outside the virtualized AppData and survives uninstall. The packer refuses a `dist` holding a top-level `snippets.json`, which would ship a user library to every install.

Release channels are explicit. The published Windows stable channel is the latest
plain `vMAJOR.MINOR.PATCH` tag (`v5.1.0`); current source is `5.2.0` on the
`beta` channel for the Windows `v5.2.0-beta.1` prerelease. The macOS ARM64
package is the `v5.0.4-beta.1` preview,
built from `main` after v5.0.3; its bundle still reports 5.0.3 stable.
The app docstring owns `Version:` and
`Channel:` for the running build, and `installer\sniptype.iss` mirrors both
as `MyAppVersion` and `MyAppChannel`. Beta installers are named
`SniptypeSetup-<version>-beta.exe`; beta tags use
`vMAJOR.MINOR.PATCH-beta.N`. Do not promote beta to stable until the supported-OS
test matrix and packaged desktop smoke tests pass.

The build script backs up and restores the packaged `snippets.json`, stages the PyInstaller output, swaps `dist\Sniptype`, and can update the Windows Startup shortcut.

Build details: the release is `--onedir` (not `--onefile`); the hidden import `pystray._win32` is required; `snippets.json` and the icon are bundled as data files, but the user-editable copy in `dist\Sniptype\` is separate from the bundled fallback in `_internal\`.

`build_release_macos.sh` mirrors the same staging discipline (build into a temp dist, promote `dist/Sniptype.app` only on success, refuse to run while the app is running) and drops the Windows-only steps — no Startup shortcut (macOS autostart is the LaunchAgent the tray toggle writes), no packaged `snippets.json` to preserve. macOS specifics worth knowing before touching it: the bundle icon is the committed `source/sniptype.icns`, copied as-is. It is deliberately not converted from `source/sniptype.ico`: the Windows tile runs edge to edge, which renders ~24% larger than other Mac icons, and the `.ico` stops at 256px. The `.icns` holds the same tile on Apple's grid (824px body centered on a 1024px canvas, drop shadow in the margin) with every slot up to 512@2x, and `test_tray_startup` asserts both the copy and the grid margin — regenerate it from the same tile whenever the Windows icon changes. The script asserts that the staged bundle both contains and references the icon. PyInstaller emits the selected Python interpreter's native architecture; the current Apple Silicon build is ARM64-only, and Intel/universal artifacts require a matching toolchain plus separate verification. `LSUIElement` is written with `plutil` *after* the build because PyInstaller has no CLI flag for extra Info.plist keys, which breaks the seal PyInstaller put on the bundle and is why the script re-signs afterwards (ad-hoc, or `CODESIGN_IDENTITY` when set). Inside the bundle `sys._MEIPASS` is `Contents/Frameworks` and `sys.executable` is `Contents/MacOS/Sniptype`, so `get_runtime_resource_dir()` and `default_autostart_command()` both work unchanged — the LaunchAgent runs that binary directly and needs no `open -a` wrapper. An ad-hoc rebuild changes the bundle's cdhash and invalidates its TCC grants; consistently using the same stable signing identity preserves them, while changing identities invalidates them.

`LSUIElement` in the plist does not by itself keep the app out of the Dock: Aqua Tk sets `NSApplicationActivationPolicyRegular` on the shared `NSApplication` while creating the root, and a runtime policy beats the plist. `platform_support.hide_dock_icon()` puts it back to accessory and `run()` calls it **after** the root exists (order asserted in `test_tray_startup`) — reversing it earlier would just be overwritten. Failure there only warns: a Dock icon is cosmetic and must not take the tray down.

## Repository Layout

- `source\sniptype.pyw` is the main entry point. `Sniptype` owns startup, single-instance handling, snippet loading, keyboard events, tray actions, GUI windows, and snippet expansion.
- `source\trigger_index.py` compiles trigger lookup data (longest-first buckets, `form_triggers`). Preserve the indexed lookup path; do not replace it with full O(n) trigger scans in the keyboard hot path.
- `source\snippet_utils.py` loads, validates, merges, and atomically saves snippets.
- `source\app_paths.py` resolves the user data directory and handles one-time legacy migration.
- `source\backup_support.py` creates rotating backups and quarantines corrupt files.
- `source\settings_support.py` loads/saves the optional `settings.json`.
- `source\dynamic_registry.py` binds the `dynamic_snippets.json` registry to named providers.
- `source\variable_support.py` parses and resolves `%%var%%` tokens: clipboard-paste variables, form fields, and references to every snippet kind — static snippets, dynamic mapping triggers (`cpffulano`), and runtime dynamic snippets (the callable is invoked). Resolving a dynamic reference can block or open a dialog, so `resolve_inline` is worker-thread only.
- `source\rich_text_support.py` builds and normalizes rich-text payloads, including HTML/RTF generation and style-span handling.
- `source\runtime_support.py` contains insertion helpers (`TextInserter`), background task support, logging, and notification formatting.
- `source\win_input.py` injects the Windows trigger erase and paste chord as single tagged `SendInput` batches and provides the listener filter that hides them from `on_press`; see the runtime reference before touching it.
- `source\clipboard_support.py` owns the clipboard backends and exports the `Clipboard` instance selected for the running OS. The Win32 ctypes bindings live behind that selection and never execute off Windows.
- `source\sync_export.py` compiles the static library plus dynamic registry into the versioned mobile bundle (`sniptype_bundle.json`) described by `source\docs\sync-design.md`. `build_bundle` is pure and provably never invokes a provider: dynamic triggers are mapped to a sentinel callable purely so `classify_variable` still returns `dynamic_ref` for them.
- `source\macos_permissions.py` probes the two macOS TCC grants the app depends on (Input Monitoring for the listener, Accessibility for the synthesized paste) and owns the PT-BR onboarding copy, the System Settings deep-links and the re-check decision. Inert off macOS: every check answers `unknown` and the decision layer then asks for nothing.
- `source\whatsapp_support.py` normalizes phone numbers and builds WhatsApp URLs.
- `source\whatsapp_runtime_support.py` runs the `xwapp`, `xlwapp`, and `xpwapp` action flows.
- `source\bcb_consultor.py` fetches Brazilian Central Bank API values with caching.
- `source\yf_stocks.py` wraps yfinance stock/fundamentals lookups. The ticker prompt itself is a Tk dialog in `sniptype.pyw` (`ask_ticker_input`), not in this module.
- `source\gui_thread.py` owns the process's only `tk.Tk()` root. Worker threads never touch Tk: they pass a callable to `GuiThread.call` (blocks, returns the result, re-raises errors) or `GuiThread.submit` (fire-and-forget), and a `root.after` pump runs it on the GUI thread. The keyboard listener must never call into it. *Which* thread that is depends on the OS: a dedicated worker thread on Windows (`ensure_started`), the main thread on macOS (`adopt_main_thread` + `run_mainloop`, selected by `platform_support.tk_runs_on_main_thread`). The marshaling contract is identical in both modes — only the thread the pump ticks on changes.
- `source\gui_support.py` contains GUI filtering and dialog helpers. The manager's single "Snippets Dinâmicos" tab (sections for Data/Hora, Economia, Ações and WhatsApp) is generated from the dynamic registry, not from hardcoded lists; each row can be enabled/disabled and renamed in place.
- `source\ui_theme.py` resolves the GUI's colors and fonts per OS. Every `bg=`/`fg=`/`font=` in `sniptype.pyw` goes through it (`ui = ui_theme.bind(root)` in a window builder, `ui_theme.theme()` in a tab builder); a literal `"#RRGGBB"` or `"Segoe UI"` back in the GUI is a regression, and `tests\test_ui_theme.py` fails on one. It also owns the light/dark palettes and the `appearance` preference (Configurações > Geral); every new `tk.Toplevel` must call `ui_theme.prepare_window(window, ui)` right after creation or it renders light controls in dark mode.
- `source\tests\` contains unit tests.
- `source\docs\` contains planning notes for refactors and features, plus `audit-report.md` (full code audit) and `improvement-plan.md` (phased roadmap).
- `source\run_sniptype.bat` is the source-side launcher. It checks/install dependencies and starts the app with `pythonw`.
- `installer\sniptype.iss` is the Inno Setup script; `build_installer.bat` compiles the versioned installer into `installer\Output\` (gitignored). The per-user install location is independent of where user data lives (`~/.sniptype`), which is what makes a Program-Files-style install safe.
- `build_release_macos.sh` is the macOS build script; it produces `dist/Sniptype.app` (menu-bar-only bundle).
- `dist\Sniptype\` is the packaged application folder. Treat `build\`, `dist\`, and `dist_staging\` as generated output unless the task is explicitly about packaging.

## Runtime architecture

Before changing trigger detection, expansion, variables/forms, GUI threading or appearance, tray startup, macOS permissions, clipboard/insertion, or autostart, read [the runtime reference](source/docs/agent-runtime-reference.md). It preserves the ordering barriers, failure semantics, and platform constraints for those paths.

## Snippets File Safety

`snippets.json` is user data. It lives in the per-user data directory resolved by `source\app_paths.py`: `SNIPTYPE_HOME` if set, otherwise `~/.sniptype`. Layout: `snippets.json`, `settings.json` (optional), `backups\`, `logs\`. The committed `source\snippets.json` is an **anonymized seed only** — do not add personal data to it. On first launch the app migrates a legacy exe-side `snippets.json` (from older builds) into the data dir, leaving the legacy file untouched; if none exists it seeds from the bundled sample.

The data layer already protects the library and the app must keep these guarantees:

- Every `save_snippets` takes a rotating backup of the prior file first (newest 30 kept in `backups\`) and returns success/failure; GUI call sites surface failures and roll back in-memory state.
- A corrupt `snippets.json` is quarantined (`snippets.corrupt-<ts>.json`) and restored from the newest **valid** backup — never overwritten with defaults while a backup exists.
- A corrupt file is never copied into the backup set (it could otherwise rank newest by mtime and defeat recovery).
- A static snippet whose name collides with a dynamic trigger is never dropped by a save. `merge_snippets` is `{**static, **dynamic}`, so the callable replaces the static value in the merged map the app saves from; `find_shadowed_statics` records those values at load and `build_saveable_snippets(snippets, preserved)` writes them back. Every path that creates the collision (static editor, enable toggle) asks for confirmation first, and the dynamic snippet is what expands.
- `backup_support.py` owns backup/quarantine helpers; `app_paths.py` owns path resolution and migration; `settings_support.py` owns `settings.json`.

`build_release.bat` no longer syncs `dist`→`source` or restores data into `dist` (user data is not in `dist` anymore); it keeps a one-time safety copy of any pre-existing packaged `snippets.json`. The optional `settings.json` key `mirror_dir` makes each successful save also copy to a write-only mirror.

The optional key `sync_export_dir` turns on the mobile sync bundle: every path that changes the live library (`save_snippets`, `restore_backup`, `import_library`, and both registry writers) calls `export_sync_bundle()`, which re-reads `snippets.json` and the registry **from disk** — `self.snippets` is stale between a restore/import write and its reload, and `self.dynamic_registry` is reassigned only after the registry writers persist. Absent key = feature off, zero behavior change. Unlike `mirror_dir`, a missing export directory is **never created**: a typo'd path would otherwise silently publish the user's full plaintext CPF/CNPJ library somewhere they never chose. Skip-if-unchanged is driven by `~/.sniptype\sync_export.state` (content digest excluding `exported_at`/`generator`, plus the recorded path and an existence check) so the bundle is not rewritten on every save; the export is best-effort and never turns a persisted save into a reported failure.

## Testing Guidance

The test suite is under `source\tests\` and uses `unittest`. Source modules are imported as flat sibling files from `source\`, not as an installed package. Tests are designed to avoid a running app instance and should mock Windows APIs, clipboard, dialogs, browser calls, and network-dependent behavior where needed.

Use focused tests for narrow changes and run the full suite before finalizing changes that touch trigger detection, snippet persistence, variable resolution, rich text, runtime insertion, or WhatsApp flows.

Never probe Tk availability by building a throwaway `tk.Tk()` in the test process. On macOS Tk 9.0.3 a root created and destroyed outside any mainloop leaves the Aqua interpreter in a state where a *later* root destroyed from inside an `after` callback traps the whole runner (SIGTRAP, no Python traceback). `test_gui_thread` probes out of process for exactly this reason; the app itself is unaffected because it only ever builds one root.

Do not give each GUI test its own `GuiThread` either. On Windows (Python 3.14.6, Tcl/Tk 8.6.15; also seen on CI's 3.12) creating a fresh Tk interpreter on a new thread over and over eventually leaves one thread's event loop wedged: no `after` timer fires and cross-thread calls go unanswered, so every later `GuiThread.call` times out. It reproduces with plain tkinter and no app code after ~100–400 interpreters, and never on the first root of a process. `test_manager_gui_smoke` therefore shares one module-level GuiThread and resets its children between tests; only `test_gui_thread`, which exists to exercise the lifecycle, creates its own.

Temporary test artifacts belong in `source\tests\tmp\`, which is gitignored.

Focused Ruff correctness rules are configured in `ruff.toml`; install the pinned development tool from `source/requirements-dev.txt` and run `python -m ruff check source` from the repository root. The same command runs in CI. There is no configured formatter or type checker.

## Coding Guidance

- Prefer small support modules over expanding `Sniptype` further when adding isolated behavior.
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

`source\requirements.txt` holds exactly these four core runtime dependencies. Sniptype release builds do not collect or probe voice runtimes and do not request microphone access. The transcription requirements and packaged voice-runtime probe live in Snipvoice. PyInstaller is installed separately and is not in the runtime requirements file.

## Agent Workflow

Before changing behavior, read the relevant support module and nearby tests. For changes in `sniptype.pyw`, also check whether the behavior already has extracted helpers in `source\*_support.py`.

When editing:

- Keep changes scoped to the requested behavior.
- Add or update tests in `source\tests\` for behavior changes.
- Do not modify generated build artifacts unless the task is explicitly about packaging or release output.
- Do not edit user snippets casually. If a task requires snippet data changes, explain the risk and preserve a backup.
- `Sniptype.spec` hardcodes absolute repo paths, but it is regenerated by `build_release.bat` (`--specpath`), so do not hand-edit it expecting the change to survive a build.
- The live user library lives in `~/.sniptype\snippets.json`, not in `dist`. The committed `source\snippets.json` is an anonymized seed. See `source\docs\audit-report.md` and `source\docs\improvement-plan.md` for the known-issues backlog and the phase status before "fixing" something that is already documented or already done.

## Public repository privacy gate

This repository is public. Treat committed files, commit/tag messages and
identities, PR descriptions, CI logs, and release assets as permanent disclosures.

Before committing or publishing:

- Stage only explicit task-owned paths. Inspect the full staged diff and file
  list, including untracked additions and binary contents/metadata. Do not commit
  generated artifacts, installers, archives, diagnostic dumps, or backups merely
  because they were produced during the task.
- Never include credentials, tokens, cookies, private keys, signing material,
  `.env` contents, live settings, recordings/transcripts, clipboard/snippet data,
  personal emails, phones, addresses, CPF/CNPJ identifiers, household/device
  details, private network endpoints, confidential client data, or private
  product/roadmap details. Use synthetic fixtures and generic paths (`$HOME`,
  `%USERPROFILE%`); sanitize screenshots and examples. Preserve legitimate public
  license/copyright attribution. Documented synthetic test credentials are allowed
  only for their narrow fixture purpose; never broadly allowlist real secrets.
- Run the available secret scanner on staged content before committing and on
  every outgoing commit/ref before pushing. Manually review privacy data and
  metadata that scanners miss. If no scanner is available, disclose the gap and
  complete a documented manual review; never claim a scanner ran. Separately run
  `git diff --cached --check` for formatting.
- Set repository-local `user.email = rteoo@users.noreply.github.com` and
  `user.useConfigOnly = true`. Verify effective author/committer identities before
  each commit and tagger identity before an annotated tag, including environment
  and command-line overrides. New owner-authored metadata must use that noreply
  address. Preserve legitimate third-party contributor attribution.
- Before an authorized push, inspect the exact remote/refspecs and every outgoing
  commit/tag, message, and reachable history. Never merge or push a pre-redaction
  branch/tag that reintroduces private identities or data. `.gitignore`, noreply
  configuration, and a clean working tree do not prove tracked files or history
  safe. Preserve hooks, signing, secret-scanning push protection, and branch
  protections; never bypass them.
- If a leak is found, stop committing/publishing the affected material. Report
  only redacted categories and locations, never the sensitive value. Deleting a
  file later does not erase Git/PR/release history. Credential rotation, history
  rewrites, force pushes, ref deletions, and external cleanup need explicit
  authorization for exact targets. This policy grants no push, PR, release, or
  history-rewrite authorization.
