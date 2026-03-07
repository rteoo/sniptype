# Txt Xpander

Txt Xpander is a Windows text expander with a system tray app, snippet manager GUI, dynamic snippets, formatted text support, WhatsApp quick-link automation, and a packaged standalone build.

## Project Layout

- [`dist\Txt Xpander\`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/dist/Txt%20Xpander): packaged app folder to run or ship.
- [`source\`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source): editable Python source, assets, launcher, tests, and docs.
- [`source\docs\refactor-plan.md`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/docs/refactor-plan.md): refactor plan kept for future work.

## Run The Packaged App

Use the packaged build here:

- [`dist\Txt Xpander\Txt Xpander.exe`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/dist/Txt%20Xpander/Txt%20Xpander.exe)

Usage notes:

1. Launch `Txt Xpander.exe`.
2. On first launch, the app seeds `snippets.json` beside the executable and uses that file for future edits.
3. Use the tray icon to open `Gerenciar Snippets`, reload snippets, enable or disable expansion, and quit the app.
4. The built-in `xwapp` trigger reads a phone number from the clipboard, creates a `wa.me` link, opens it in the browser, and keeps the final link in the clipboard.
5. If `xwapp` cannot normalize the clipboard content into a valid phone number, it opens a popup for manual phone and optional message entry.
6. Before replacing the packaged folder with a newer build, close any running `Txt Xpander.exe` first.
7. `build_release.bat` now preserves the packaged app's existing `snippets.json` automatically when updating `dist\Txt Xpander`.

### Auto-start with Windows

To have Txt Xpander launch automatically when you sign in:

1. Press **Win + R**
2. Type `shell:startup` and press **Enter**
3. Copy `Txt Xpander.exe` or a shortcut to it into that folder
4. Txt Xpander will now start automatically with Windows

If you use [`build_release.bat`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/build_release.bat), it now stages the build safely, restores the previous packaged `snippets.json` automatically when `dist\Txt Xpander` already exists, and can also create or update the Startup shortcut after the build finishes.

For convenience, the source launcher (`run_txt_xpander.bat`) can install itself into Startup with:

```bat
run_txt_xpander.bat install
```

This copies the batch file to your `%appdata%\Microsoft\Windows\Start Menu\Programs\Startup` folder so it runs on logon. You can remove it later by deleting the shortcut from the same location.


## Work From Source

All editable code now lives in [`source\`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source).

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

Or use the source-side launcher:

- [`source\run_txt_xpander.bat`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/run_txt_xpander.bat)

## Build A New Packaged Release

From the repo root, with `PyInstaller` installed:

```powershell
python -m PyInstaller --noconfirm --clean --windowed --onedir --name "Txt Xpander" --icon source\txt_xpander.ico --add-data "source\snippets.json;." --add-data "source\txt_xpander.ico;." --hidden-import pystray._win32 source\txt_xpander.pyw
```

This produces the shipping folder in [`dist\Txt Xpander\`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/dist/Txt%20Xpander).

## Source Contents

Main source files:

- [`source\txt_xpander.pyw`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/txt_xpander.pyw): main Windows app, tray, listener, GUI, notifications.
- [`source\runtime_support.py`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/runtime_support.py): clipboard insertion, logging helpers, background task support.
- [`source\rich_text_support.py`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/rich_text_support.py): rich-text editing and clipboard payload generation.
- [`source\snippet_utils.py`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/snippet_utils.py): snippet loading, validation, atomic persistence.
- [`source\trigger_index.py`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/trigger_index.py): compiled trigger matching.
- [`source\gui_support.py`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/gui_support.py): GUI reference/filter helpers.
- [`source\bcb_consultor.py`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/bcb_consultor.py): Banco Central data lookups.
- [`source\yf_stocks.py`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/yf_stocks.py): stock and fundamentals lookups.
- [`source\tests\`](/C:/Users/example/.codex/worktrees/5aec/txt_xpander/source/tests): regression tests.

## Release Notes

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
- Added rich-text snippet support with formatting controls in the snippet manager.
- Added `x-hj` as the ISO date snippet.
- Improved the snippet manager layout, resize behavior, search/filtering, and notification history access.
