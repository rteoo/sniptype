# Txt Xpander — Audit Report

Date: 2026-07-16
Scope: full source review (`source/*.py`, `txt_xpander.pyw`, `build_release.bat`, `Txt Xpander.spec`, `snippets.json` in source and dist), focused on data safety, performance, UI, and cross-platform portability.

Severity legend: **P0** = data loss / silent failure risk, fix first · **P1** = real user-facing impact · **P2** = quality / maintainability · **P3** = nice to have.

---

## 1. Data safety and persistence

### 1.1 [P0] The live snippets file is unversioned, unbacked, and drifting

The runtime file is `dist/Txt Xpander/snippets.json`. It is gitignored (`dist/`), only synced back into `source/snippets.json` when `build_release.bat` runs, and has **no backup of any kind** between builds. Measured drift as of today:

- 6 keys exist **only in dist**: `_fasa_codes`, `brewupdt`, `ccupdt`, `psupdt`, `x9gm`, `x@ac`
- 4 keys exist only in source (stale): `_fict3_codes`, `brewupd`, `psupdate`, `x.ac`
- 6 keys have **different values**: `_openclaw_codes`, `saptu`, `_strateo_codes`, `xgm`, `_prompt_codes`, `_acrn_codes`

A disk failure, a bad OneDrive sync, or an accidental delete in the GUI loses everything created since the last build. This confirms the concern that motivated this audit.

### 1.2 [P0] Corrupted JSON on load is overwritten with defaults

`load_snippets()` ([txt_xpander.pyw:208](../txt_xpander.pyw)) does this on a parse error:

```python
except Exception as e:
    static_snippets = self.get_default_snippets()
    self.save_snippets(static_snippets)   # ← replaces the user's file with 3 sample snippets
```

A single truncated write (OneDrive sync conflict, power loss mid-`os.replace`, cloud-only placeholder file) destroys the entire snippet library on next launch. The corrupt file should be quarantined (renamed with a timestamp), never overwritten, and the app should fall back to the newest backup.

### 1.3 [P0] All logging is lost in the packaged app

`AppLogger` ([runtime_support.py:49](../runtime_support.py)) is `print()`-only. The packaged build is `--windowed` (no console), so every error — including "failed to save snippets.json" — goes nowhere. There is no log file. When something breaks, there is no way to diagnose it after the fact.

### 1.4 [P1] Data lives inside OneDrive

OneDrive is actively hostile to this workload: it can hold file locks during sync (making the atomic `os.replace` in `write_json_atomic` fail with `PermissionError`), can dehydrate files to cloud-only placeholders, and creates sync-conflict duplicates. App data (snippets, future backups, logs) should live in a stable local directory under `$HOME`, with OneDrive used — if at all — as a copy target, not the working location. This also aligns with the planned macOS/Linux migration.

### 1.5 [P1] Personal data is committed to git

`source/snippets.json` (committed) contains real personal data: full name, phone triggers, CPF/CNPJ mappings, SSH host aliases. The build script even syncs the live dist file (with more personal data) into it before each build. The repo copy should be a small anonymized seed; the personal library should live only in the user data directory (plus backups).

Also: `source/snippets_versão de testes.json` is a stray test file committed to the repo.

### 1.6 [P2] Save errors are swallowed

`save_snippets()` catches every exception and only logs (which, per 1.3, is invisible). The GUI then shows "Snippet salvo" via tray notification even when the write failed. Save failures must surface to the user.

### 1.7 [P2] No export / import / restore path

There is no way from the UI to export the library, import one, or restore a previous state. The only "backup" is a temp-file copy that exists during `build_release.bat` and is deleted at the end.

---

## 2. Performance

### 2.1 [P1] Network snippets run synchronously on the keyboard listener thread

Only the stock/WhatsApp triggers are in `slow_snippets`. All BCB triggers (`xdolar`, `xselic`, `xipcam`, `xipca12`, `xcdi`, `xptax`, `xeconomia`) are plain callables, so `expand_snippet()` executes them **inside `on_press()`** ([txt_xpander.pyw:664-668](../txt_xpander.pyw)). On a cache miss:

- each SGS fetch has a 3 s timeout;
- `xeconomia` performs **5 sequential fetches** — up to ~15 s worst case;

during which the pynput listener callback is blocked and every keystroke system-wide is delayed/queued. Any snippet that touches the network (or does anything slower than a few ms) must go through the background path. The cleanest rule: the listener thread only *detects*; all expansion work happens on a worker thread.

### 2.2 [P1] An exception in a callable snippet kills the listener silently

`on_press()` only catches `AttributeError`. `expand_snippet()` calls `snippet()` (line 668) *outside* its internal try/except. If a callable raises (BCB mostly shields this by returning `[Erro: …]` strings, but nothing guarantees it), the exception propagates out of the pynput callback and **stops the listener thread** — the app keeps its tray icon but never expands again until restart, with no error shown (see 1.3). `on_press` needs a broad guard with logging.

### 2.3 [P1] Latent trigger-buffer bug: `max_trigger_length` excludes dynamic mapping triggers on load

Initial load and "Recarregar Snippets" call `refresh_runtime_indexes()` with `include_dynamic_items=False`, so the typed-text buffer is sized only by direct keys. A composed dynamic trigger (`prefix + item name`) longer than the longest direct key gets truncated out of the buffer and **can never match**. Today the longest composed trigger is exactly 15 chars — equal to the longest direct key — so it works by coincidence. Adding one long mapping item breaks it invisibly. The GUI mapping tab already uses `include_dynamic_items=True`; load/reload should too (there is no reason for two modes).

### 2.4 [P1] Slow startup and oversized build from eager `yfinance` import

`import yfinance as yf` at the top of [yf_stocks.py](../yf_stocks.py) drags in pandas/numpy at every launch — seconds of startup time and tens of MB in the PyInstaller dist — to support snippets that are used occasionally and already run on a background thread. Import it lazily inside the fetch methods.

### 2.5 [P2] Per-keystroke work that could be precomputed

- `has_form_variables(extract_plain_text(raw_value))` runs a regex scan on the snippet body on every direct-trigger hit ([txt_xpander.pyw:951](../txt_xpander.pyw)). The trigger index already exists — precompute a `needs_slow` flag per trigger at compile time.
- `find_dynamic_trigger` does a substring scan per prefix per keystroke. Fine at the current scale (<10 prefixes); becomes a candidate for last-char bucketing only if prefixes grow.

### 2.6 [P2] Backspace erase loop blocks ~10–20 ms per character

The erase loop sleeps 10 ms per backspace inside the listener callback (both in `on_press` and `expand_snippet`). With expansion moved off the listener thread (2.1) this stops mattering for input latency; until then it adds up on long triggers.

### 2.7 [P3] Clipboard restore only preserves plain text

`TextInserter._paste_value` saves/restores only `CF_UNICODETEXT`. If the clipboard held an image, file list, or rich text, it is silently lost on every expansion. At minimum this deserves a documented-limitation note; a fuller fix preserves the original format handles.

---

## 3. Correctness / robustness

### 3.1 [P1] Trigger matching is order-dependent when one trigger is a suffix of another

`find_direct_trigger` returns the first match in insertion order. If trigger B is a suffix of trigger A (e.g. `ieban` / `iecban`), whichever comes first in the dict wins — if the shorter one is listed first, the longer one can never fire. There are no such conflicts in today's data (verified), but nothing prevents creating one in the GUI, and nothing warns. Match longest-first, and validate conflicts at save time (see 4.4).

### 3.2 [P1] Documented terminator behavior doesn't exist

CLAUDE.md/README describe expansion as "trigger word followed by a terminator (space, punctuation)", but the code expands **immediately** on the last matching character. Any trigger that is a prefix of a real word misfires mid-word. Either implement optional terminator-gated expansion (per-snippet or global setting) or fix the docs. Given daily use, an opt-in "expand only after space/punctuation" flag is the safer long-term direction.

### 3.3 [P2] Multiple Tk roots across threads

`_show_form_dialog`, `ask_whatsapp_input`, and the manager GUI each create their own `tk.Tk()` mainloop on whatever background thread runs them. Tkinter is not thread-safe; two dialogs alive at once (e.g. a form dialog fires while the manager is open) is a crash/hang risk. A single hidden Tk root on one dedicated GUI thread, with dialogs marshaled onto it, removes the whole class of problem.

### 3.4 [P2] Dead/misleading code

- `self._manager_lock` / `self._manager_open` are set but never actually used to gate anything (`manage_snippets_gui` relies on `FindWindowW` instead).
- `bcb_consultor.py` lines 194–223 are a stale "how to integrate" comment block from when the module was pasted in.
- `markdown>=3.4.0` in requirements.txt is not imported anywhere.
- ~40 blank lines at the tail of `txt_xpander.pyw`.

### 3.5 [P2] GUI allows shadowed/invalid triggers

The static editor accepts a trigger equal to a dynamic snippet name (e.g. `xhj`): it saves to JSON but is silently shadowed at merge time (`merge_snippets` gives dynamics priority) — the user's snippet never fires and there is no warning. It also accepts triggers containing whitespace, and mapping items whose composed trigger collides with a static trigger.

---

## 4. UI / management gaps

### 4.1 [P1] No backup/restore/export surface anywhere

Neither the tray menu nor the manager exposes: backup now, restore from backup, export library, import library, or even "open snippets folder". For a daily-use tool holding irreplaceable data this is the biggest UI gap (pairs with §1).

### 4.2 [P2] Manager list shows keys only

The static list shows just the trigger. A value preview column (first ~40 chars), a count, and a "rich text / has variables" marker would make the library scannable. Same for mapping items.

### 4.3 [P2] Editing friction

- No Ctrl+S to save in the editor; no dirty indicator — switching selection silently discards edits.
- No rename flow (rename = create new + delete old by hand).
- Delete has a confirm but no undo (backups from §1 give a cheap "undo" story).
- No duplicate-to-new-trigger action.

### 4.4 [P2] No validation feedback at save time

Warn on: trigger shadowed by a dynamic snippet (3.5), trigger that is a suffix/prefix of an existing trigger (3.1), whitespace or terminator characters inside a trigger, very short triggers (1–2 chars) likely to misfire.

### 4.5 [P3] Visual polish

Hardcoded light-theme colors, no DPI awareness call (`SetProcessDpiAwareness`) so Tk renders blurry on high-DPI displays, notification history is session-only, reference tabs (Data/Economia/Ações/WhatsApp) are hand-maintained lists in `gui_support.py` that can drift from the actual registered triggers (they would come for free from the registry in §5).

---

## 5. Baked-in dynamic snippets — should they move to JSON?

Verdict: **move the registry to JSON, keep the logic in Python.** The callables themselves (BCB fetch, yfinance, WhatsApp flows) cannot and should not be serialized. But everything *about* them is data and is currently hardcoded in four places that must be kept in sync by hand:

1. trigger names — `get_dynamic_snippets()` dict keys
2. which are slow — `self.slow_snippets` set
3. their descriptions — `DATETIME_SNIPPETS` / `ECONOMY_SNIPPETS` / `STOCK_SNIPPETS` / `WHATSAPP_SNIPPETS` in gui_support.py
4. provider parameters — date formats inline in lambdas, BCB series codes in `BCBConsultor.SERIES`

A `dynamic_snippets.json` shipped with the app (and user-overridable in the data dir) of the form:

```json
{
  "xhj":    {"provider": "datetime", "format": "%d/%m/%Y", "description": "Data de hoje (DD/MM/AAAA)"},
  "xdolar": {"provider": "bcb", "method": "dolar", "slow": true, "description": "Cotação do dólar (PTAX)"},
  "xcot":   {"provider": "stock", "method": "cotacao", "slow": true, "description": "Cotação atual"},
  "xwapp":  {"provider": "whatsapp", "mode": "open", "slow": true, "description": "..."}
}
```

buys: rename/disable triggers without touching code, per-user overrides (e.g. an English date format), the `slow` flag and the GUI reference tabs generated from one source of truth, and BCB timeouts/cache TTLs configurable. Providers register themselves by name; unknown provider → logged warning, trigger skipped.

---

## 6. Portability (OneDrive → `$HOME`, future macOS/Linux)

Current hard Windows couplings, in order of migration effort:

| Area | Where | Portable replacement |
|---|---|---|
| Data location | beside the exe (inside OneDrive) | `~/.txt_xpander/` (works verbatim on all three OSes), `TXT_XPANDER_HOME` env override |
| Clipboard | ctypes user32/kernel32 (`WindowsClipboard`) | platform adapter; pynput stays cross-platform |
| Single instance | `CreateMutexW` | lockfile with PID in the data dir |
| Ticker input dialog | `mshta` VBScript | Tk dialog on the shared GUI thread (also removes an odd dependency on mshta) |
| Manager focus | `FindWindowW` / `SetForegroundWindow` | track the Tk window handle in-process |
| Already-running popup | `MessageBoxW` | Tk messagebox |
| Autostart | Startup-folder .lnk via build script | per-OS adapter (Startup folder / LaunchAgent / autostart .desktop) |
| Paste shortcut | Ctrl+V | Cmd+V on macOS — adapter in `TextInserter` |

The keyboard listener (pynput), tray (pystray), and GUI (Tk) are already cross-platform. The decisive first step for the user's stated goal is the **data directory move** — everything else can follow incrementally.

---

## 7. Alignment with the owner's global agent guidelines

Measured against the global agent guidelines (fail loudly, no dead code, English-only code/comments, `ceiling:` markers, no personal data in git, tests for behavior):

### 7.1 [P1] Systemic silent exception handling

"Fail loudly and early; no silent fallbacks; no `except: pass`" is violated as a pattern, not an incident: ~15 bare `except:` clauses in [yf_stocks.py](../yf_stocks.py) returning `"N/A"`, a bare `except: continue` in [bcb_consultor.py:86](../bcb_consultor.py), and both `_get_cached_or_fetch` implementations converting every exception into a `"[Erro: …]"` string. The user-facing `"N/A"` result is acceptable UX; swallowing the *cause* is not — failures must at least be logged (which requires Phase 1's real logger to be useful).

### 7.2 [P2] Portuguese comments and docstrings

The guideline is English for code and comments (user-facing strings exempt). `txt_xpander.pyw`, `bcb_consultor.py`, and `yf_stocks.py` are mostly Portuguese; the newer support modules are English — the codebase drifted toward compliance but was never brought fully in line.

### 7.3 [P2] "Changed this" comments

`VERSÃO ATUALIZADA`, `(ATUALIZADO para pegar prefixes customizados)`, and similar are the explicitly banned changelog-in-comments style. Git has the history.

### 7.4 [P2] No `ceiling:` markers

Several deliberate simplifications carry no marker naming their limit and upgrade trigger: insertion-order-dependent trigger matching (3.1), plain-text-only clipboard restore (2.7), print-only logging (1.3), BCB calls on the listener thread (2.1).

### 7.5 [P2] Version metadata drift

`txt_xpander.pyw` header says `Versão: 2.6`; CHANGELOG and README describe 2.7.

### 7.6 Already covered elsewhere

Personal data in git → 1.5. Dead code and unused `markdown` dependency → 3.4. Untested main file (hot path, GUI) → grows coverage with Phase 3's hot-path work.

## 8. Summary of findings by priority

| # | Finding | Severity |
|---|---|---|
| 1.1 | Live snippets.json unbacked and drifting from repo | P0 |
| 1.2 | Corrupt JSON overwritten with defaults on load | P0 |
| 1.3 | No log file; all errors invisible in packaged app | P0 |
| 1.4 | App data lives inside OneDrive | P1 |
| 1.5 | Personal data committed to git | P1 |
| 2.1 | BCB snippets block the keyboard listener (up to ~15 s) | P1 |
| 2.2 | Callable exception silently kills the listener | P1 |
| 2.3 | Buffer excludes dynamic mapping triggers (latent) | P1 |
| 2.4 | Eager yfinance import: slow startup, fat build | P1 |
| 3.1 | Suffix-trigger ordering hazard, unvalidated | P1 |
| 3.2 | No terminator gating despite documented behavior | P1 |
| 4.1 | No backup/restore/export UI | P1 |
| 1.6 / 1.7 | Save errors swallowed; no export path | P2 |
| 2.5 / 2.6 | Per-keystroke regex; backspace sleeps | P2 |
| 3.3 | Multiple Tk roots across threads | P2 |
| 3.4 / 3.5 | Dead code; shadowed-trigger saves | P2 |
| 4.2–4.4 | Manager list/editing/validation gaps | P2 |
| 2.7 / 4.5 | Clipboard format loss; DPI/theme polish | P3 |
| 7.1 | Systemic bare `except:` / silent fallbacks | P1 |
| 7.2–7.5 | Portuguese comments; "changed this" comments; no `ceiling:` markers; version drift | P2 |

The companion document [improvement-plan.md](improvement-plan.md) sequences the fixes.
