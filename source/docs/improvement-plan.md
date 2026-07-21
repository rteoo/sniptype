# Txt Xpander — Improvement Plan

> **Status (2026-07-20):** Phases 0–4 fully implemented; Phases 5–6 implemented except two items that need a running app / non-Windows host to verify. Full unittest suite green (261 tests). Phase 5.1 (single Tk root, audit 3.3) and Phase 6 clipboard backend split (`clipboard_support.py`, last hard Win32 coupling) both landed 2026-07-20 — the POSIX backend is plain-text only and unverified on a real macOS/Linux host. Phase 5 Treeview list/preview (4.2) landed 2026-07-20; the autostart adapter is wired to a tray toggle and the ticker dialog moved to Tk with Phase 5.1, closing the adapter follow-ups. Remaining, tracked follow-up: Phase 6 rich-text paste off Windows.

Companion to [audit-report.md](audit-report.md). Seven phases (0–6), ordered so that guideline compliance and data safety land before anything else and each phase ships independently. Constraint honored throughout: **JSON files only — no database.**

Rule of thumb for sequencing: Phase 0 brings the codebase in line with the owner's global agent guidelines; Phases 1 and 2 protect the data; 3 fixes real bugs; 4–6 make the app better. Do not start Phase 4+ before 1–2 are done.

Cross-cutting rules for every phase (from the global guidelines): every bug fix ships with a regression test that fails before the fix; conventional-commit branches (`chore/…`, `fix/…`, `feat/…`, `refactor/…`); one logical change per commit; never commit to `main` directly; no dependency changes as a side effect of another task.

---

## Phase 0 — Guideline compliance refactor (fixes audit 7.1–7.5, 3.4)

Goal: the existing code follows the owner's global agent guidelines before new behavior is built on top of it. **Zero behavior change** — provable, see verification below.

Branch: `chore/guideline-compliance`.

1. **Delete dead code:** stale integration comment block in `bcb_consultor.py` (lines 194–223), unused `_manager_lock`/`_manager_open` in `txt_xpander.pyw`, trailing blank lines, the stray committed `source/snippets_versão de testes.json` (recoverable from git history).
2. **English-only comments and docstrings** in `txt_xpander.pyw`, `bcb_consultor.py`, `yf_stocks.py`. User-facing strings (UI labels, notifications, console/log messages) stay Portuguese — they are product surface, not code commentary. Remove "changed this" comments (`VERSÃO ATUALIZADA` etc.) outright instead of translating them.
3. **Narrow bare `except:` to `except Exception:`** in `yf_stocks.py` and `bcb_consultor.py`. Returned `"N/A"` / `"[Erro: …]"` values are unchanged (behavior preserved); wiring the swallowed causes into a real logger lands with Phase 1's logging.
4. **Add `ceiling:` markers** at the known deliberate simplifications, each naming its upgrade trigger: insertion-order trigger matching (→ longest-first in Phase 3), plain-text-only clipboard restore (→ format-preserving restore if rich clipboard loss bites), print-only logger (→ Phase 1), BCB callables on the listener thread (→ Phase 3).
5. **Metadata fixes:** `txt_xpander.pyw` header version 2.6 → 2.7; remove the unused `markdown` entry from `requirements.txt` (it is imported nowhere — verified).

Verification: full unittest suite before and after, plus an AST-equivalence check (parse old and new modules, strip docstrings, compare dumps) proving comment/docstring-only edits changed no code paths.

Effort: small. Ships first — it makes every later diff cleaner to review.


## Phase 1 — Data safety (fixes 1.1, 1.2, 1.3, 1.6)

Goal: it becomes impossible to lose the snippet library through a crash, a bad save, a corrupt file, or a sync conflict.

1. **Rotating backups on every save.**
   - In `save_snippets()`, before `write_json_atomic`, copy the current file to `backups/snippets-YYYYMMDD-HHMMSS.json` (skip if content unchanged).
   - Keep the newest N=30 by mtime, prune the rest. Plain files, greppable, restorable by hand with zero tooling.
   - Also take one backup at startup if the newest backup is older than 24 h (catches "many edits, app never restarted" windows).
2. **Quarantine instead of overwrite on corrupt load.**
   - In `load_snippets()`, on parse failure: rename the bad file to `snippets.corrupt-YYYYMMDD-HHMMSS.json`, then try the newest backup; only if no backup exists fall back to defaults. Never call `save_snippets(defaults)` over a file that existed.
   - Notify via tray: "snippets.json estava corrompido; restaurado do backup de <ts>".
3. **Real file logging.**
   - Replace `AppLogger`'s prints with `logging` + `RotatingFileHandler` writing to `<data_dir>/logs/txt_xpander.log` (1 MB × 3). Keep console echo when stdout exists (dev mode).
4. **Surface save failures.** `save_snippets()` returns success/failure; GUI shows an error messagebox and the tray notifies on failure instead of claiming success.

Tests: backup rotation and pruning; corrupt-file quarantine + backup restore (write garbage JSON, load, assert original bytes preserved under quarantine name); save-failure propagation (mock `write_json_atomic` to raise).

Effort: small-medium. No behavior change for the happy path.

## Phase 2 — Move data out of OneDrive to `$HOME` + migration/restore UX (fixes 1.4, 1.5, 1.7, 4.1)

Goal: app data lives in `~/.txt_xpander/`, identical layout on Windows/macOS/Linux, with a one-time automatic migration and a visible backup/restore surface.

1. **Data directory resolver** (new small module, e.g. `app_paths.py`):
   - `TXT_XPANDER_HOME` env var override → else `Path.home() / ".txt_xpander"`.
   - Layout: `snippets.json`, `dynamic_snippets.json` (Phase 4), `backups/`, `logs/`, `settings.json` (future).
2. **One-time migration on startup:** if `~/.txt_xpander/snippets.json` doesn't exist and a legacy exe-side file does, copy it in (and drop a `migrated-from.txt` breadcrumb + first backup). The legacy file is left untouched as an extra safety copy. Tray notification announces the move and the new path.
3. **Simplify the build pipeline:** `build_release.bat` stops syncing dist→source and stops restoring snippets into the new dist — user data no longer lives in dist at all. The bundled `snippets.json` becomes a small **anonymized seed** (sample entries only).
4. **De-personalize the repo:** replace `source/snippets.json` content with the seed; delete `source/snippets_versão de testes.json`. (Optionally rewrite git history later — separate decision; at minimum stop adding new personal data.)
5. **Backup/restore/export UI:**
   - Tray menu: "Abrir pasta de dados", "Backup agora".
   - Manager: new "Backups" tab — list of backups (timestamp, size, #snippets), buttons: Restaurar (with confirm; current file is backed up first), Exportar… (save-as copy of current library), Importar… (file picker; validates JSON; merge-or-replace choice; auto-backup before applying).
6. **Optional OneDrive mirror:** a `settings.json` key `mirror_dir` — when set, every successful save also copies the file there (write-only mirror, never read). Gives cloud redundancy without OneDrive being in the write path.

Tests: resolver with/without env override; migration idempotence (second launch doesn't re-migrate); import validation rejects non-dict JSON; restore takes pre-restore backup.

Effort: medium. This is the phase that fulfills the OneDrive → `$HOME` requirement.

## Phase 3 — Hot-path performance and correctness (fixes 2.1–2.6, 3.1, 3.2)

Goal: keystrokes are never blocked, the listener can't die, matching is deterministic.

1. **Listener detects, worker expands.** `on_press()` only matches and erases the trigger; the entire expansion (callable execution, variable resolution, clipboard, paste) moves to `task_runner`. This makes the fast/slow split mostly disappear: everything is async, and `slow_snippets` degenerates into "needs a dialog first" metadata.
2. **Broad exception guard in `on_press`** (and in the worker): catch `Exception`, log, notify with cooldown. The listener must be unkillable.
3. **Buffer fix:** always compute `max_trigger_length` with mapping items (`include_dynamic_items=True` becomes the only path; delete the other), plus a small safety margin (+8 chars).
4. **Precompute per-trigger metadata in `compile_trigger_index`:** `needs_form_dialog` flag (regex scan at compile time, not per keystroke); longest-first candidate ordering within each last-char bucket (fixes suffix-order hazard 3.1 deterministically).
5. **Lazy-import yfinance** inside `B3FundamentosConsultor` fetch methods; measure startup before/after and record it in the PR.
6. **Optional terminator mode** (global setting in `settings.json`, default off to preserve current muscle memory): when on, a matched trigger expands only after space/Enter/punctuation, and the terminator is re-typed after the expansion. Fix README/CLAUDE.md to describe the actual behavior either way.

Tests: index metadata (longest-first, needs_form flags); buffer length includes composed dynamic triggers; a raising callable doesn't stop matching (simulate); terminator mode unit tests on the matcher.

Effort: medium-large. Highest-risk phase — touch the hot path with the regression suite green before/after and a few days of daily-driving before building a release.

## Phase 4 — Dynamic snippet registry in JSON (fixes §5, part of 4.5)

Goal: one data file describes every dynamic trigger; code only provides named providers.

1. **`dynamic_snippets.json`** bundled with the app; user copy in `~/.txt_xpander/` overrides/extends it (bad entries: log + skip, never crash). Schema per trigger: `provider`, provider params (`format`, `method`, `mode`…), `slow`/`dialog` flag, `description`, `enabled`.
2. **Provider registry in code:** `datetime`, `bcb`, `stock`, `whatsapp` register factory functions; `get_dynamic_snippets()` becomes "read registry file → bind providers".
3. **Generate the GUI reference tabs** (Data/Hora, Economia, Ações, WhatsApp) from the registry — delete the hand-maintained lists in `gui_support.py`.
4. **Manager additions:** the dynamic tabs get an enable/disable checkbox and editable trigger name per entry (writes to the user override file, reload applies).
5. BCB series codes, timeouts, and cache TTLs move into the registry entries.

Tests: registry parsing (unknown provider, duplicate trigger vs static, disabled entry); reference-tab data derives from registry; date-format override round-trip.

Effort: medium. Independent of Phase 3; requires Phase 2's data dir.

## Phase 5 — Manager UI improvements (fixes 3.3, 3.5, 4.2–4.4)

1. **Single Tk root architecture — done.** `gui_thread.GuiThread` owns one hidden root on a dedicated GUI thread started in `run()`; all dialogs (form fill, WhatsApp, ticker input, manager, notification history) are `Toplevel`s marshaled onto it via a queue pumped by `root.after`. Workers block on `GuiThread.call`; the manager uses fire-and-forget `submit` plus in-process window tracking. Dropped `mshta`/VBScript and the `FindWindowW` focus trick (both Phase 6 wins).
2. **Save-time validation with warnings:** trigger shadowed by a dynamic trigger; trigger is prefix/suffix of an existing one; whitespace/terminators inside the trigger; 1–2 char triggers. Warn-and-confirm, don't hard-block.
3. **List quality — done.** The static and mapping-item lists are `ttk.Treeview`s with trigger/value-preview/markers columns (`RT` for rich text, `%%` for variables), built by `gui_support.snippet_row_values`; the notebook tab titles carry item counts — the static tab counts what the search shows, the mappings tab counts every item across all types so the title can't shift when you click a type. The mapping *types* list stays a Listbox (short labels only). Restore/import now replay registered list refreshers so the tabs can't show a stale library.
4. **Editing flow:** Ctrl+S saves; dirty-state indicator with confirm-on-switch; rename action; duplicate action.
5. **Polish:** `SetProcessDpiAwareness` at startup (per-monitor v2) for crisp Tk on high-DPI; persist notification history to a small JSON ring file; centralize colors in one theme dict.

Effort: medium-large, but each item ships independently. Item 1 first — the rest builds on it.

## Phase 6 — Cross-platform groundwork (fixes §6, 2.7 partially)

Goal: `python txt_xpander.pyw` runs on macOS/Linux with graceful degradation; Windows behavior unchanged.

1. **Platform adapter module** (`platform_support.py`) with a Windows implementation extracted from today's code and interfaces for: clipboard (get/set text+HTML+RTF), single-instance guard (lockfile+PID replaces mutex), paste shortcut (Ctrl+V vs Cmd+V), "already running" message, autostart install/remove.
2. **Replace remaining Windows-only calls** in the main file: `FindWindowW` focus trick → in-process window tracking (**done** with Phase 5.1); `MessageBoxW` → Tk.
3. **Clipboard adapters for macOS/Linux** (pasteboard / `xclip`-or-`wl-copy` shim or a small dependency — decide then; plain-text-first is acceptable v1).
4. **Autostart adapter — done.** `install_autostart` / `remove_autostart` / `is_autostart_enabled` in `platform_support.py` write the Startup `.lnk` (Windows, via the same `WScript.Shell` COM object the build script uses), the LaunchAgent plist (macOS) or the `~/.config/autostart/*.desktop` entry (Linux), driven by the tray check item "Iniciar com o sistema". `build_release.bat` keeps its install-time prompt for packaged convenience; the tray toggle is the canonical runtime path. macOS/Linux writes are covered by mocked-OS tests only — unverified on a real host. The enabled check compares the entry's argv against `default_autostart_command()` (`classify_autostart`) instead of testing for the file's presence, resolved once at startup and cached for the menu; an entry whose target is gone is repaired, one owned by another live install is reported stale and left alone.
5. Document per-OS caveats (macOS Accessibility permission for pynput; Wayland limitations) in README.

Effort: large, but Phases 2 and 5 will have already removed most couplings. Ship Windows-refactor first (adapter with only a Windows backend), then add OS backends opportunistically.

---

## Suggested order and checkpoints

| Order | Phase | Ships when | Risk |
|---|---|---|---|
| 0 | Guideline compliance | tests green + AST-equivalence check | very low |
| 1 | Data safety | backups + quarantine + logs verified by tests | low |
| 2 | `$HOME` move + backup UI | migration tested on the real machine; build script simplified | low-medium |
| 3 | Hot path | full test suite + several days of daily use | medium-high |
| 4 | Dynamic registry JSON | registry drives triggers + GUI tabs | medium |
| 5 | Manager UI | single-root refactor stable | medium |
| 6 | Cross-platform | Windows unchanged; adapters in place | medium |

Each phase = one branch, one PR, tests included (`python -m unittest discover -s tests -v` green). Phases 1+2 can be combined into a single release since both are prerequisites for trusting the data layer; everything after that is incremental.

Immediate manual step (before any code lands): copy `dist/Txt Xpander/snippets.json` somewhere safe today — it is currently the only copy of the live library.
