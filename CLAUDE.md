# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run from source (development):**

```bash
cd source
python -m pip install -r requirements.txt
pythonw txt_xpander.pyw          # Run app (no console window)
python txt_xpander.pyw           # Run with console for debug output
```

**Run tests:**

```bash
cd source
python -m unittest discover -s tests -v   # All tests
python -m unittest tests.test_snippet_utils -v   # Single module
```

**Build packaged release:**

```bash
build_release.bat    # Automated: backs up snippets.json, builds, swaps dist/, optional startup shortcut
```

## Architecture

The application is a Windows system tray text expander. Typing a trigger word followed by a terminator (space, punctuation) replaces the typed text with an expanded value via clipboard paste (Ctrl+V).

**Entry point:** `source/txt_xpander.pyw` — the `TextExpander` class (~2000+ lines) bootstraps everything: single-instance mutex, keyboard listener (pynput), system tray (pystray), GUI windows (Tkinter), and snippet loading.

**Keyboard hot path:** `on_press()` appends each keystroke to a buffer, detects terminators, then checks the compiled trigger index. Index is pre-compiled at load time into bucketed suffix lookups (`direct_by_last_char`) for O(1) matching. Background threads handle slow snippets (network calls, dialogs, form fills).

**Expansion pipeline:**

1. Detect trigger (direct or dynamic pattern)
2. Check if snippet has form variables — if yes, route to slow (async) path
3. Fast path: resolve inline variables (`%%clipboard-paste%%`, `%%snippet_ref%%`) before insertion
4. Slow path: show form dialog, collect values, resolve all variables, insert
5. Insert via clipboard paste (Ctrl+V) for reliability with multiline and chat apps

**Support modules:**

- [trigger_index.py](source/trigger_index.py) — pre-compiled index; never do O(n) trigger scanning
- [snippet_utils.py](source/snippet_utils.py) — JSON load/save with atomic writes (`os.replace`)
- [runtime_support.py](source/runtime_support.py) — clipboard, Windows API, threading, logging
- [rich_text_support.py](source/rich_text_support.py) — HTML/RTF formatting, variable-safe span rebuild
- [variable_support.py](source/variable_support.py) — variable parsing (`%%var%%`), classification, resolution
- [whatsapp_runtime_support.py](source/whatsapp_runtime_support.py) — `xwapp`/`xlwapp`/`xpwapp` action modes
- [bcb_consultor.py](source/bcb_consultor.py) — Brazilian Central Bank API (5-min cache)
- [yf_stocks.py](source/yf_stocks.py) — yfinance wrapper; prompts for ticker via VBScript dialog

## Snippet Types

**Static:** Simple key→string pairs in `snippets.json`, editable via GUI.

**Dynamic (runtime-only, not persisted):** Callables registered at startup — date/time, BCB economic indicators, yfinance stock fundamentals, WhatsApp link generators. Merged over static snippets at load time.

**Rich text:** Value is a dict `{"__kind__": "rich_text", "text": "...", "spans": [...], "html": "...", "rtf": "..."}`. Spans encode style ranges (bold/italic/etc.).

**Dynamic mapping containers:** Keys prefixed with `_` (e.g., `_cpf_numbers`, `_cnpj_numbers`, `_custom_codes`) create pattern-based triggers. `cpfperson1` looks up `_cpf_numbers["person1"]`.

## Snippets File

`snippets.json` lives beside the executable (packaged) or in `source/` (dev). On first run, it is seeded from the bundled copy. User edits persist here — never overwrite it without backing it up. The build script preserves it across builds.

## Tests

Tests are in `source/tests/`. Temp artifacts go in `source/tests/tmp/` (gitignored). Tests are self-contained and do not require a running instance or Windows APIs (mock where needed).

## Build Notes

[Txt Xpander.spec](Txt Xpander.spec) uses `--onedir` (not `--onefile`). Hidden import `pystray._win32` is required. `snippets.json` and the icon are bundled as data files but the user-editable copy in `dist/Txt Xpander/` is separate from `_internal/`.
