# AGENTS.md

This file is the canonical agent contract for this repository — it guides Claude Code, Codex, and any other coding agent. `CLAUDE.md` is a thin pointer here; make all edits to project guidance in this file.

## Project Overview

Txt Xpander is a Windows system tray text expander. Typing a trigger word replaces the typed text with an expanded value, usually by placing the payload on the clipboard and sending Ctrl+V. Expansion fires immediately on the last character of a matching trigger; there is no terminator (space/punctuation) gating.

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

The build script backs up and restores the packaged `snippets.json`, stages the PyInstaller output, swaps `dist\Txt Xpander`, and can update the Windows Startup shortcut.

Build details: the release is `--onedir` (not `--onefile`); the hidden import `pystray._win32` is required; `snippets.json` and the icon are bundled as data files, but the user-editable copy in `dist\Txt Xpander\` is separate from the bundled fallback in `_internal\`.

## Repository Layout

- `source\txt_xpander.pyw` is the main entry point. `TextExpander` owns startup, single-instance handling, snippet loading, keyboard events, tray actions, GUI windows, and snippet expansion.
- `source\trigger_index.py` compiles trigger lookup data. Preserve the indexed lookup path; do not replace it with full O(n) trigger scans in the keyboard hot path.
- `source\snippet_utils.py` loads, validates, merges, and atomically saves snippets.
- `source\variable_support.py` parses and resolves `%%var%%` tokens, including snippet references, clipboard-paste variables, and form fields.
- `source\rich_text_support.py` builds and normalizes rich-text payloads, including HTML/RTF generation and style-span handling.
- `source\runtime_support.py` contains clipboard integration, insertion helpers, background task support, logging, and notification formatting.
- `source\whatsapp_support.py` normalizes phone numbers and builds WhatsApp URLs.
- `source\whatsapp_runtime_support.py` runs the `xwapp`, `xlwapp`, and `xpwapp` action flows.
- `source\bcb_consultor.py` fetches Brazilian Central Bank API values with caching.
- `source\yf_stocks.py` wraps yfinance stock/fundamentals lookups. The ticker prompt itself is a VBScript/mshta dialog in `txt_xpander.pyw` (`ask_ticker_input`), not in this module.
- `source\gui_support.py` contains GUI filtering and dialog helpers, plus the reference lists shown in the manager's Data/Economia/Ações/WhatsApp tabs.
- `source\tests\` contains unit tests.
- `source\docs\` contains planning notes for refactors and features, plus `audit-report.md` (full code audit) and `improvement-plan.md` (phased roadmap).
- `source\run_txt_xpander.bat` is the source-side launcher. It checks/install dependencies and starts the app with `pythonw`.
- `dist\Txt Xpander\` is the packaged application folder. Treat `build\`, `dist\`, and `dist_staging\` as generated output unless the task is explicitly about packaging.

## Architecture Notes

The keyboard hot path is `TextExpander.on_press()`. It appends keystrokes to a buffer and checks the compiled trigger index for a suffix match on every keystroke — expansion fires as soon as the buffer ends with a trigger. The index is pre-compiled at load time into buckets keyed by the trigger's last character (`direct_by_last_char`), so each keystroke only scans that bucket. Slow work such as network calls, dialogs, and form fill prompts must run outside the hot path (stock/WhatsApp triggers and form-variable snippets already do; BCB economy triggers currently do not — see `source/docs/audit-report.md` §2.1 before touching this area).

Expansion flow:

1. Detect a direct or dynamic trigger.
2. Route snippets with form variables to the slow async path.
3. Resolve inline variables such as `%%clipboard-paste%%` and `%%snippet_ref%%`.
4. Resolve form variables after collecting user input.
5. Insert text or rich text through clipboard paste for reliable multiline and chat-app behavior.

Dynamic snippets are registered at startup and merged over static snippets. `source\snippets.json` currently has a small user-editable dataset plus mapping containers; do not assume it is disposable fixture data. Mapping containers with keys prefixed by `_`, such as `_cpf_numbers`, `_cnpj_numbers`, and `_custom_codes`, create pattern-based triggers like `cpfperson1`.

Rich-text snippets are dictionaries shaped like:

```json
{"__kind__": "rich_text", "text": "...", "spans": [...], "html": "...", "rtf": "..."}
```

Style spans are range based. When text changes, keep spans normalized and clipped through `rich_text_support.py` helpers.

## Runtime Notes

This is a Windows-only app using `pynput` for keyboard hooks, `pystray` for the tray icon, `tkinter` for GUI, `ctypes` for Win32 clipboard and mutex calls, and clipboard paste as the primary insertion path.

Single-instance enforcement uses the Win32 mutex `Local\TxtXpanderSingleton`.

Network-backed helpers use short caches: BCB lookups cache for about 300 seconds and yfinance stock fundamentals cache for about 600 seconds.

## Snippets File Safety

`snippets.json` is user data. In development it lives under `source\`. In the packaged app it lives beside `Txt Xpander.exe`, separate from the bundled fallback copy in `_internal`; on first run the app seeds it from that bundled copy.

Never overwrite a user-editable `snippets.json` without backing it up first. Ad-hoc safety copies go in `backups\` at the repo root (gitignored). Preserve the build script behavior that syncs/restores snippets during release builds.

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
- `markdown` (listed in requirements.txt but not imported anywhere — candidate for removal)

PyInstaller is needed to build releases.

## Agent Workflow

Before changing behavior, read the relevant support module and nearby tests. For changes in `txt_xpander.pyw`, also check whether the behavior already has extracted helpers in `source\*_support.py`.

When editing:

- Keep changes scoped to the requested behavior.
- Add or update tests in `source\tests\` for behavior changes.
- Do not modify generated build artifacts unless the task is explicitly about packaging or release output.
- Do not edit user snippets casually. If a task requires snippet data changes, explain the risk and preserve a backup.
- Watch for stale project metadata: the `txt_xpander.pyw` header still says version 2.6 while the changelog and README describe 2.7-era behavior. `Txt Xpander.spec` hardcodes absolute repo paths, but it is regenerated by `build_release.bat` (`--specpath`), so do not hand-edit it expecting the change to survive a build.
- `dist\Txt Xpander\snippets.json` is the live user library and drifts from the committed `source\snippets.json` between builds. `source\snippets_versão de testes.json` is a stray committed test file. See `source\docs\audit-report.md` for the full list of known issues before "fixing" something that is already documented.
