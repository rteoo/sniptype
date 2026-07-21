# Txt Xpander

Txt Xpander is a Windows text expander with a system tray app, snippet manager GUI, dynamic snippets, formatted text support, WhatsApp quick-link automation, and a packaged standalone build.

## Project Layout

- [`dist\Txt Xpander\`](dist/Txt%20Xpander): packaged app folder to run or ship.
- [`source\`](source): editable Python source, assets, launcher, tests, and docs.
- [`source\docs\`](source/docs): planning notes, plus [`audit-report.md`](source/docs/audit-report.md) (full code audit) and [`improvement-plan.md`](source/docs/improvement-plan.md) (phased roadmap).

## Run The Packaged App

Use the packaged build here:

- [`dist\Txt Xpander\Txt Xpander.exe`](dist/Txt%20Xpander/Txt%20Xpander.exe)

Usage notes:

1. Launch `Txt Xpander.exe`.
2. User data lives in `%USERPROFILE%\.txt_xpander` (override with the `TXT_XPANDER_HOME` environment variable): `snippets.json`, rotating `backups\`, `logs\`, and optional `settings.json`. On first launch the app migrates any legacy `snippets.json` found beside the executable into this folder (the legacy file is left in place as an extra copy) and, failing that, seeds from the bundled sample. The live library is automatically backed up on every save (newest 30 kept) and a corrupt file is quarantined and restored from the newest valid backup instead of being overwritten.
3. Use the tray icon to open `Gerenciar Snippets`, reload snippets, `Backup agora`, `Abrir pasta de dados`, enable or disable expansion, and quit the app. The manager's **Backups** tab lists backups and offers restore, export, and import.
4. By default expansion fires immediately on the last character of a matching trigger. To require a word boundary instead, set `"terminator_mode": true` in `%USERPROFILE%\.txt_xpander\settings.json`: a trigger then expands only when you type a following space or punctuation, which is re-typed after the expansion (Enter is not treated as a terminator).
5. The built-in `xwapp` trigger reads a phone number from the clipboard, creates a `wa.me` link, opens it in the browser, and keeps the final link in the clipboard.
6. The built-in `xlwapp` trigger follows the same validation flow but inserts the generated `wa.me` link into the current field and also keeps that link in the clipboard.
7. The built-in `xpwapp` trigger skips clipboard lookup, opens the popup immediately for phone and optional message entry, then opens the browser and keeps the final link in the clipboard.
8. If `xwapp` or `xlwapp` cannot normalize the clipboard content into a valid phone number, the app opens the same popup for manual phone and optional message entry.
9. Before replacing the packaged folder with a newer build, close any running `Txt Xpander.exe` first.
10. `build_release.bat` keeps a one-time safety copy of any existing packaged `snippets.json` when updating `dist\Txt Xpander`. User data is no longer stored in `dist` — it lives in `%USERPROFILE%\.txt_xpander`, so a rebuild never touches the live library.

### Auto-start with Windows

Right-click the tray icon and tick **Iniciar com o sistema**. Txt Xpander creates the Startup shortcut for the current user (pointing at the packaged executable, or at `pythonw txt_xpander.pyw` when running from source); unticking it removes the shortcut. No admin rights, no registry keys.

The same toggle is the autostart path on macOS (LaunchAgent plist) and Linux (`~/.config/autostart` entry).

[`build_release.bat`](build_release.bat) still offers to create the Startup shortcut after a successful build (skipped automatically if the shortcut already exists), and you can always drop a shortcut into `shell:startup` yourself.

### Cross-platform status

Txt Xpander is Windows-first. The OS-specific couplings are being factored behind [`source/platform_support.py`](source/platform_support.py): the paste modifier (Ctrl+V on Windows/Linux, Cmd+V on macOS), a PID-lockfile single-instance guard for non-Windows (Windows keeps its named mutex), and per-OS autostart install/remove (Startup `.lnk`, macOS LaunchAgent plist, Linux `.desktop`) driven by the tray toggle — the non-Windows writes are covered by tests but unverified on a real host. The keyboard listener (pynput), tray (pystray), GUI (Tk) and the JSON data layer are already portable, and the data directory (`~/.txt_xpander`) is identical on all three OSes.

Clipboard access is factored the same way, behind [`source/clipboard_support.py`](source/clipboard_support.py): Windows keeps the ctypes user32/kernel32 backend (text, HTML and RTF), while macOS uses `pbcopy`/`pbpaste` and Linux uses `wl-copy`/`wl-paste` under Wayland, falling back to `xclip` then `xsel`. The Win32 bindings now load only on Windows, so the app imports cleanly on macOS/Linux. The POSIX backend is plain-text only for now — rich-text snippets paste as their plain text and log the downgrade — and a desktop with none of those tools installed logs a warning rather than failing hard.

CI runs the unit suite on `windows-latest`, `macos-latest` and `ubuntu-latest` (Python 3.12 and 3.14) on every pull request, so the POSIX branches of the clipboard, autostart and single-instance code are exercised on real macOS and Linux hosts rather than only under mocks. Linux runs under `xvfb-run`: pynput and pystray both bind to Xorg at import time and raise without a display.

Remaining before the app runs unmodified on macOS/Linux: rich-text paste off Windows, opening the data folder (`os.startfile` has no POSIX equivalent in place yet), plus platform limits outside our control — on macOS pynput requires granting Accessibility permission, and Wayland restricts global keyboard hooks. What CI does *not* cover is end-to-end behavior on a real desktop session: tray icon, actual paste into another app, and macOS Accessibility permission are still unverified.

## Work From Source

All editable code lives in [`source\`](source).

Typical source workflow:

```powershell
cd source
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Run from source:

```powershell
cd source
pythonw txt_xpander.pyw
```

Or use the source-side launcher, which checks dependencies and starts the app with `pythonw`:

- [`source\run_txt_xpander.bat`](source/run_txt_xpander.bat)

## Build A New Packaged Release

Prefer the automated script — it backs up the packaged `snippets.json`, stages the PyInstaller output, and swaps `dist\Txt Xpander` only on success:

```powershell
build_release.bat
```

The equivalent raw PyInstaller command (note: this does **not** preserve the packaged `snippets.json` — use the script for routine rebuilds):

```powershell
python -m PyInstaller --noconfirm --clean --windowed --onedir --name "Txt Xpander" --icon source\txt_xpander.ico --add-data "source\snippets.json;." --add-data "source\dynamic_snippets.json;." --add-data "source\txt_xpander.ico;." --hidden-import pystray._win32 source\txt_xpander.pyw
```

This produces the shipping folder in [`dist\Txt Xpander\`](dist/Txt%20Xpander).

## Build The Installer (Setup.exe)

For a real install experience — installs to a proper per-user location, adds Start Menu / optional Desktop shortcuts, an optional "start with Windows" checkbox, and a proper entry in **Apps & features** with an uninstaller — build a Windows installer with [Inno Setup](https://jrsoftware.org/isdl.php).

One-time prerequisite: install **Inno Setup 6** (free).

```powershell
build_release.bat      REM 1) package the app into dist\Txt Xpander
build_installer.bat    REM 2) compile installer\Output\TxtXpanderSetup-<version>.exe
```

`build_installer.bat` finds the Inno Setup compiler (`ISCC.exe`) automatically and compiles [`installer\txt_xpander.iss`](installer/txt_xpander.iss).

Running the resulting **Setup.exe**:

- Installs per-user to `%LOCALAPPDATA%\Programs\Txt Xpander` — **no administrator prompt**.
- Creates Start Menu (and optional Desktop) shortcuts and, if you tick the box, a Startup shortcut so it launches at login.
- Registers a real uninstaller (Windows **Apps & features**), which removes the program files but **keeps your data** in `%USERPROFILE%\.txt_xpander`.
- Detects a running instance and asks you to close it before installing/upgrading.

Notes:
- The installer is **unsigned**, so Windows SmartScreen shows a "More info → Run anyway" prompt the first time — expected for a self-built app.
- Upgrading over a previous install replaces the program files in place (same install ID) and never touches your `~/.txt_xpander` data.
- After moving to the installer, you can delete any old `dist\Txt Xpander` copy and its old Startup shortcut; the installer's own shortcut points at the new location.

## Custom Variables (`%%var%%`)

Snippets can include custom variables that are resolved at expansion time:

**Snippet reference** — `%%trigger%%` expands to another snippet's value:

```json
xadds: Rua Pais Leme, 215
xaddc: %%xadds%%, São Paulo - SP

Type xaddc → expands to: Rua Pais Leme, 215, São Paulo - SP
```

**Clipboard paste** — `%%clipboard-paste%%` inserts the current clipboard:

```json
xcattle: uv run python main.py "%%clipboard-paste%%"

With clipboard "myfile.txt" → uv run python main.py "myfile.txt"
```

**Form fields** — `%%fieldname%%` prompts the user before insertion:

```json
aptgyn: Olá, %%nome%%,\nO apartamento está disponível em %%data%%?

Shows a dialog asking for "Nome" and "Data" → substitutes values before inserting
```

All three variable types can be mixed in a single snippet. The snippet manager has three toolbar buttons for them:

- `%%s` — insert a snippet reference (searchable picker)
- `%%cb` — insert clipboard-paste variable
- `%%?` — insert a form field variable

## Source Contents

Main source files:

- [`source\txt_xpander.pyw`](source/txt_xpander.pyw): main Windows app, tray, listener, GUI, notifications.
- [`source\variable_support.py`](source/variable_support.py): `%%var%%` parsing and resolution (snippet refs, clipboard, form fields).
- [`source\runtime_support.py`](source/runtime_support.py): clipboard insertion, logging helpers, background task support.
- [`source\rich_text_support.py`](source/rich_text_support.py): rich-text editing and clipboard payload generation.
- [`source\snippet_utils.py`](source/snippet_utils.py): snippet loading, validation, atomic persistence.
- [`source\trigger_index.py`](source/trigger_index.py): compiled trigger matching.
- [`source\gui_support.py`](source/gui_support.py): GUI reference/filter helpers.
- [`source\whatsapp_support.py`](source/whatsapp_support.py): phone number normalization and `wa.me` URL building.
- [`source\whatsapp_runtime_support.py`](source/whatsapp_runtime_support.py): shared runtime flow for built-in WhatsApp actions.
- [`source\bcb_consultor.py`](source/bcb_consultor.py): Banco Central data lookups.
- [`source\yf_stocks.py`](source/yf_stocks.py): stock and fundamentals lookups.
- [`source\tests\`](source/tests): regression tests.

## Release Notes

### 2026-03-30 (Latest)

- **Added custom variables in snippets** (`%%var%%` syntax):
  - Snippet references: `%%trigger%%` expands inline to another snippet's plain text
  - Clipboard paste: `%%clipboard-paste%%` inserts current clipboard content
  - Form fields: `%%fieldname%%` prompts the user for input before inserting
  - Three new toolbar buttons in the snippet manager to insert variable tokens
- **Fixed tray icon double-click** — now correctly opens a single "Gerenciar Snippets" window (prevents duplicates via Windows API lookup)
- **Fixed snippet loss on rebuild** — `build_release.bat` now syncs `dist\snippets.json` → `source\snippets.json` before PyInstaller runs, ensuring the bundled fallback copy always contains the latest snippets
- **Form-fill variables** route snippets through the async path to show an input dialog before insertion
- **Rich text compatibility**: variables inside rich-text snippets are resolved and spans are clipped/regenerated as needed
- All 85 tests pass, including 32 new variable support tests

### 2026-03-09

- Added `xlwapp` to generate a WhatsApp `wa.me` link from clipboard or popup input, insert it into the active field, and keep the link in the clipboard.
- Added `xpwapp` to skip clipboard lookup, prompt immediately for phone and optional message, and open the browser with the generated link.
- Refactored the built-in WhatsApp runtime flow into a shared helper so all three triggers use the same validation and URL generation rules.

### 2026-03-07

- Added the new `xwapp` dynamic snippet to create WhatsApp `wa.me` links from clipboard phone numbers.
- Added a manual WhatsApp popup fallback when the clipboard does not contain a valid number.
- Kept the generated WhatsApp link in the clipboard instead of restoring the previous clipboard contents for this action.
- Added a WhatsApp reference tab in the snippet manager.
- Hardened `build_release.bat` to stage builds safely and preserve the packaged `snippets.json` during dist updates.

### 2026-03-06

- Added a working standalone PyInstaller build in `dist\Txt Xpander`.
- Fixed packaged startup so the app seeds and uses `snippets.json` beside the executable.
- Fixed the packaged tray icon and tray-backed notifications.
- Switched snippet insertion to clipboard-first behavior for better multiline and chat-app reliability.
- Added `x-hj` as the ISO date snippet.
- Improved the snippet manager layout, resize behavior, search/filtering, and notification history access.
