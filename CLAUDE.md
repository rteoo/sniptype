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

The application is a Windows system tray text expander. Typing a trigger word replaces the typed text with an expanded value via clipboard paste (Ctrl+V). Expansion fires **immediately** on the last character of a matching trigger — there is no terminator (space/punctuation) wait, so triggers that are prefixes of real words will misfire mid-word.

**Entry point:** `source/txt_xpander.pyw` — the `TextExpander` class (~2000+ lines) bootstraps everything: single-instance mutex, keyboard listener (pynput), system tray (pystray), GUI windows (Tkinter), and snippet loading.

**Keyboard hot path:** `on_press()` appends each keystroke to a buffer, then checks the compiled trigger index for a suffix match. The index is pre-compiled at load time into buckets keyed by the trigger's last character (`direct_by_last_char`), so each keystroke only scans that bucket. Slow snippets (network calls, dialogs, form fills) are dispatched to background threads; note that BCB economy triggers currently run synchronously on the listener thread (see `source/docs/audit-report.md` §2.1).

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
- [whatsapp_support.py](source/whatsapp_support.py) — phone number normalization, wa.me URL building
- [whatsapp_runtime_support.py](source/whatsapp_runtime_support.py) — `xwapp`/`xlwapp`/`xpwapp` action modes
- [gui_support.py](source/gui_support.py) — GUI filtering helpers, dialog centering, reference lists for the manager tabs
- [bcb_consultor.py](source/bcb_consultor.py) — Brazilian Central Bank API (5-min cache)
- [yf_stocks.py](source/yf_stocks.py) — yfinance wrapper (10-min cache); the ticker prompt itself is a VBScript/mshta dialog in `txt_xpander.pyw` (`ask_ticker_input`)

## Snippet Types

**Static:** Simple key→string pairs in `snippets.json`, editable via GUI.

**Dynamic (runtime-only, not persisted):** Callables registered at startup — date/time, BCB economic indicators, yfinance stock fundamentals, WhatsApp link generators. Merged over static snippets at load time.

**Rich text:** Value is a dict `{"__kind__": "rich_text", "text": "...", "spans": [...], "html": "...", "rtf": "..."}`. Spans encode style ranges (bold/italic/etc.).

**Dynamic mapping containers:** Keys prefixed with `_` (e.g., `_cpf_numbers`, `_cnpj_numbers`, `_custom_codes`) create pattern-based triggers. `cpfperson1` looks up `_cpf_numbers["person1"]`.

## Snippets File

`snippets.json` lives beside the executable (packaged) or in `source/` (dev). On first run, it is seeded from the bundled copy. User edits persist here — never overwrite it without backing it up. The build script preserves it across builds.

**The live user library is `dist/Txt Xpander/snippets.json`** — it is gitignored and only synced back to `source/snippets.json` when `build_release.bat` runs, so the two copies drift between builds. Treat the dist copy as the source of truth for user data; never regenerate or clobber it. Ad-hoc safety copies go in `backups/` (gitignored).

## Docs

Planning and analysis documents live in `source/docs/`: feature/refactor/WhatsApp plans, plus [audit-report.md](source/docs/audit-report.md) (full code audit, findings ranked P0–P3) and [improvement-plan.md](source/docs/improvement-plan.md) (phased plan: data safety → $HOME migration → hot path → dynamic registry → UI → cross-platform).

## Tests

Tests are in `source/tests/`. Temp artifacts go in `source/tests/tmp/` (gitignored). Tests are self-contained and do not require a running instance or Windows APIs (mock where needed).

## Build Notes

[Txt Xpander.spec](Txt Xpander.spec) uses `--onedir` (not `--onefile`). Hidden import `pystray._win32` is required. `snippets.json` and the icon are bundled as data files but the user-editable copy in `dist/Txt Xpander/` is separate from `_internal/`.
