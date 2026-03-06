# Txt Xpander

Txt Xpander is a Windows text expander with a system tray app, snippet manager GUI, dynamic snippets, formatted text support, and a packaged standalone build.

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
4. Before replacing the packaged folder with a newer build, close any running `Txt Xpander.exe` first.

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

### 2026-03-06

- Added a working standalone PyInstaller build in `dist\Txt Xpander`.
- Fixed packaged startup so the app seeds and uses `snippets.json` beside the executable.
- Fixed the packaged tray icon and tray-backed notifications.
- Switched snippet insertion to clipboard-first behavior for better multiline and chat-app reliability.
- Added rich-text snippet support with formatting controls in the snippet manager.
- Added `x-hj` as the ISO date snippet.
- Improved the snippet manager layout, resize behavior, search/filtering, and notification history access.
