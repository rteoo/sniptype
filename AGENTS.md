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

**Build the Windows installer (Setup.exe):**

```powershell
build_release.bat      # produce dist\Txt Xpander first
build_installer.bat    # compile installer\Output\TxtXpanderSetup-<version>.exe
```

`build_installer.bat` requires the Inno Setup 6 compiler (`ISCC.exe`) and compiles `installer\txt_xpander.iss`: a per-user install to `%LOCALAPPDATA%\Programs\Txt Xpander` (no admin), Start Menu/Desktop/Startup shortcuts, and a proper uninstaller that leaves `~/.txt_xpander` user data intact. Bump `MyAppVersion` in the `.iss` alongside the app version.

The build script backs up and restores the packaged `snippets.json`, stages the PyInstaller output, swaps `dist\Txt Xpander`, and can update the Windows Startup shortcut.

Build details: the release is `--onedir` (not `--onefile`); the hidden import `pystray._win32` is required; `snippets.json` and the icon are bundled as data files, but the user-editable copy in `dist\Txt Xpander\` is separate from the bundled fallback in `_internal\`.

## Repository Layout

- `source\txt_xpander.pyw` is the main entry point. `TextExpander` owns startup, single-instance handling, snippet loading, keyboard events, tray actions, GUI windows, and snippet expansion.
- `source\trigger_index.py` compiles trigger lookup data (longest-first buckets, `form_triggers`). Preserve the indexed lookup path; do not replace it with full O(n) trigger scans in the keyboard hot path.
- `source\snippet_utils.py` loads, validates, merges, and atomically saves snippets.
- `source\app_paths.py` resolves the user data directory and handles one-time legacy migration.
- `source\backup_support.py` creates rotating backups and quarantines corrupt files.
- `source\settings_support.py` loads/saves the optional `settings.json`.
- `source\dynamic_registry.py` binds the `dynamic_snippets.json` registry to named providers.
- `source\variable_support.py` parses and resolves `%%var%%` tokens, including snippet references, clipboard-paste variables, and form fields.
- `source\rich_text_support.py` builds and normalizes rich-text payloads, including HTML/RTF generation and style-span handling.
- `source\runtime_support.py` contains clipboard integration, insertion helpers, background task support, logging, and notification formatting.
- `source\whatsapp_support.py` normalizes phone numbers and builds WhatsApp URLs.
- `source\whatsapp_runtime_support.py` runs the `xwapp`, `xlwapp`, and `xpwapp` action flows.
- `source\bcb_consultor.py` fetches Brazilian Central Bank API values with caching.
- `source\yf_stocks.py` wraps yfinance stock/fundamentals lookups. The ticker prompt itself is a VBScript/mshta dialog in `txt_xpander.pyw` (`ask_ticker_input`), not in this module.
- `source\gui_support.py` contains GUI filtering and dialog helpers. The manager's Data/Economia/Ações/WhatsApp reference tabs are generated from the dynamic registry, not from hardcoded lists.
- `source\tests\` contains unit tests.
- `source\docs\` contains planning notes for refactors and features, plus `audit-report.md` (full code audit) and `improvement-plan.md` (phased roadmap).
- `source\run_txt_xpander.bat` is the source-side launcher. It checks/install dependencies and starts the app with `pythonw`.
- `installer\txt_xpander.iss` is the Inno Setup script; `build_installer.bat` compiles it into `installer\Output\` (gitignored). The per-user install location is independent of where user data lives (`~/.txt_xpander`), which is what makes a Program-Files-style install safe.
- `dist\Txt Xpander\` is the packaged application folder. Treat `build\`, `dist\`, and `dist_staging\` as generated output unless the task is explicitly about packaging.

## Architecture Notes

The keyboard hot path is `TextExpander.on_press()`. It appends keystrokes to a buffer and checks the compiled trigger index for a suffix match on every keystroke. The index is pre-compiled at load time into buckets keyed by the trigger's last character (`direct_by_last_char`), ordered longest-first so a trigger that is a suffix of another cannot shadow it; it also precomputes `form_triggers` so the form-variable regex never runs per keystroke. The listener only detects and erases the trigger; all expansion work (callable execution including BCB fetches, variable resolution, dialogs, clipboard, paste) runs on a worker thread via `_run_expansion`, so no keystroke is ever blocked and a raising callable can never kill the listener. The buffer length always includes composed dynamic mapping triggers plus a margin (`TRIGGER_BUFFER_MARGIN`).

Expansion flow:

1. Detect a direct or dynamic trigger.
2. Route snippets with form variables to the slow async path.
3. Resolve inline variables such as `%%clipboard-paste%%` and `%%snippet_ref%%`.
4. Resolve form variables after collecting user input.
5. Insert text or rich text through clipboard paste for reliable multiline and chat-app behavior.

Dynamic snippets are described in `source\dynamic_snippets.json` (bundled) plus an optional per-user override at `~/.txt_xpander\dynamic_snippets.json`. `source\dynamic_registry.py` binds each entry's `provider` (`datetime`/`bcb`/`stock`/`whatsapp`) to a callable; `slow_snippets` and the manager's reference tabs are derived from this registry, not hardcoded. An unknown provider/method or a disabled entry is logged and skipped, never fatal. The callables (BCB/yfinance fetches, WhatsApp flows) stay in Python — only their metadata is data. Add a new dynamic trigger by adding a registry entry whose provider already exists; add a new provider by registering a factory in `PROVIDERS`.

Static snippets are merged under dynamic ones at load. `source\snippets.json` is an anonymized seed plus mapping containers; do not assume it is disposable fixture data. Mapping containers with keys prefixed by `_`, such as `_cpf_numbers`, `_cnpj_numbers`, and `_custom_codes`, create pattern-based triggers like `cpfalice`.

Rich-text snippets are dictionaries shaped like:

```json
{"__kind__": "rich_text", "text": "...", "spans": [...], "html": "...", "rtf": "..."}
```

Style spans are range based. When text changes, keep spans normalized and clipped through `rich_text_support.py` helpers.

## Runtime Notes

This is a Windows-first app using `pynput` for keyboard hooks, `pystray` for the tray icon, `tkinter` for GUI, `ctypes` for Win32 clipboard and mutex calls, and clipboard paste as the primary insertion path. OS-specific decisions are centralized in `source\platform_support.py` (paste modifier, single-instance strategy, autostart builders); adding a macOS/Linux backend should extend that module rather than scatter `sys.platform` checks. The remaining hard Windows coupling is the Win32 clipboard in `runtime_support.py` (loaded at import) — a non-Windows clipboard backend is the next cross-platform step.

Single-instance enforcement uses the Win32 mutex `Local\TxtXpanderSingleton` on Windows; other platforms use a PID lockfile in the data dir.

Network-backed helpers use short caches: BCB lookups cache for about 300 seconds and yfinance stock fundamentals cache for about 600 seconds.

## Snippets File Safety

`snippets.json` is user data. It lives in the per-user data directory resolved by `source\app_paths.py`: `TXT_XPANDER_HOME` if set, otherwise `~/.txt_xpander`. Layout: `snippets.json`, `settings.json` (optional), `backups\`, `logs\`. The committed `source\snippets.json` is an **anonymized seed only** — do not add personal data to it. On first launch the app migrates a legacy exe-side `snippets.json` (from older builds) into the data dir, leaving the legacy file untouched; if none exists it seeds from the bundled sample.

The data layer already protects the library and the app must keep these guarantees:

- Every `save_snippets` takes a rotating backup of the prior file first (newest 30 kept in `backups\`) and returns success/failure; GUI call sites surface failures and roll back in-memory state.
- A corrupt `snippets.json` is quarantined (`snippets.corrupt-<ts>.json`) and restored from the newest **valid** backup — never overwritten with defaults while a backup exists.
- A corrupt file is never copied into the backup set (it could otherwise rank newest by mtime and defeat recovery).
- `backup_support.py` owns backup/quarantine helpers; `app_paths.py` owns path resolution and migration; `settings_support.py` owns `settings.json`.

`build_release.bat` no longer syncs `dist`→`source` or restores data into `dist` (user data is not in `dist` anymore); it keeps a one-time safety copy of any pre-existing packaged `snippets.json`. The optional `settings.json` key `mirror_dir` makes each successful save also copy to a write-only mirror.

## Testing Guidance

The test suite is under `source\tests\` and uses `unittest`. Source modules are imported as flat sibling files from `source\`, not as an installed package. Tests are designed to avoid a running app instance and should mock Windows APIs, clipboard, dialogs, browser calls, and network-dependent behavior where needed.

Use focused tests for narrow changes and run the full suite before finalizing changes that touch trigger detection, snippet persistence, variable resolution, rich text, runtime insertion, or WhatsApp flows.

Temporary test artifacts belong in `source\tests\tmp\`, which is gitignored.

There is no repo-local `pyproject.toml`, `pytest`, `ruff`, `black`, `mypy`, or `tox` configuration at the time of writing.

## Coding Guidance

- Prefer small support modules over expanding `TextExpander` further when adding isolated behavior.
- Keep keyboard listener work fast and deterministic.
- Preserve atomic JSON writes via `os.replace`.
- Avoid persisting runtime-only dynamic snippets.
- Keep GUI work on the appropriate Tkinter thread.
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

`source\requirements.txt` holds exactly these four runtime dependencies. PyInstaller is needed to build releases and is installed separately (`pip install pyinstaller`); it is not in `requirements.txt`.

## Agent Workflow

Before changing behavior, read the relevant support module and nearby tests. For changes in `txt_xpander.pyw`, also check whether the behavior already has extracted helpers in `source\*_support.py`.

When editing:

- Keep changes scoped to the requested behavior.
- Add or update tests in `source\tests\` for behavior changes.
- Do not modify generated build artifacts unless the task is explicitly about packaging or release output.
- Do not edit user snippets casually. If a task requires snippet data changes, explain the risk and preserve a backup.
- `Txt Xpander.spec` hardcodes absolute repo paths, but it is regenerated by `build_release.bat` (`--specpath`), so do not hand-edit it expecting the change to survive a build.
- The live user library lives in `~/.txt_xpander\snippets.json`, not in `dist`. The committed `source\snippets.json` is an anonymized seed. See `source\docs\audit-report.md` and `source\docs\improvement-plan.md` for the known-issues backlog and the phase status before "fixing" something that is already documented or already done.
