# Changelog

All notable changes to Txt Xpander are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [2.7] — 2026-03-30

### Added

- **Custom variables in snippets** (`%%variable_name%%` syntax):
  - **Snippet references**: `%%trigger%%` expands inline to the plain text of another snippet (one level deep, no recursion)
  - **Clipboard paste**: `%%clipboard-paste%%` inserts the current clipboard content at expansion time
  - **Form fields**: `%%fieldname%%` prompts the user with a labeled input dialog before inserting the snippet
  - Three new toolbar buttons in the snippet manager GUI to insert variable tokens:
    - `%%s` — searchable picker for snippet references
    - `%%cb` — insert clipboard-paste variable directly
    - `%%?` — prompt for a form field name to insert
- **Tray icon double-click** opens the "Gerenciar Snippets" window directly (Windows default action on `default=True` menu item)
- **Form-fill detection** in keyboard listener: snippets containing `%%field%%` variables are routed through the async path to show a form dialog
- **Form dialog** (`_show_form_dialog`): modal Tkinter window with labeled entry fields, OK/Cancel buttons, centered on screen
- **Variable support module** (`variable_support.py`):
  - `find_variable_names()` — extracts unique `%%var%%` names in order
  - `classify_variable()` — determines type (clipboard, snippet_ref, form_field)
  - `has_form_variables()` — checks if a snippet needs a form dialog
  - `resolve_inline()` — resolves clipboard + snippet refs (safe on hot path, no dialogs)
  - `resolve_form_variables()` — substitutes form field values after dialog collection
- **Rich text compatibility** for variables:
  - `rebuild_rich_text()` helper in `rich_text_support.py` handles variable resolution inside rich-text snippets
  - Spans are automatically clipped to new text length and HTML/RTF regenerated
- **32 new unit tests** in `test_variable_support.py` covering all variable functionality

### Changed

- **Expansion pipeline** now includes variable resolution stage:
  - Fast path (direct/dynamic snippets): resolve inline variables only, insert immediately
  - Slow path (rich-text, stock lookups, form-fill variables): show dialogs/fetch data, then resolve all variables
- **`expand_snippet()`** now calls `resolve_inline()` to handle `%%clipboard-paste%%` and `%%trigger%%` substitutions
- **`run_slow_snippet()`** extended to handle non-callable static snippets (those with form variables):
  - Detects form field names, shows input dialog, collects values, substitutes, inserts
  - Callable snippets (stock actions) continue with their existing flow
- **`on_press()`** keyboard listener detects form variables at trigger time and routes to slow path if needed

### Fixed

- **Tray icon double-click** now prevents opening duplicate manager windows by using Windows API `FindWindowW()` to detect an existing window and restore it instead
- **Snippet data loss on rebuild**: `build_release.bat` now syncs `dist\snippets.json` → `source\snippets.json` before PyInstaller runs, ensuring the bundled fallback copy in `_internal/snippets.json` contains the latest user snippets
- Circular reference protection in variable resolution (guards against `%%xself%%` referencing itself)

### Technical

- All 85 tests pass (53 existing + 32 new variable tests)
- No breaking changes to public API or snippet file format
- Backward compatible: existing snippets without variables work unchanged

## [2.6] — 2026-03-09

### Added

- `xlwapp` trigger: generate WhatsApp `wa.me` link from clipboard or fallback popup, insert into active field, keep link in clipboard
- `xpwapp` trigger: skip clipboard lookup, prompt immediately for phone and optional message, open browser with generated link
- Refactored WhatsApp runtime flow into shared `whatsapp_runtime_support.py` helper so all three triggers (`xwapp`, `xlwapp`, `xpwapp`) use consistent validation and URL generation

### Changed

- WhatsApp action modes now use a centralized helper for phone normalization, link generation, and error handling

## [2.5] — 2026-03-07

### Added

- `xwapp` dynamic snippet: read phone number from clipboard, create `wa.me` link, open in browser, keep link in clipboard
- Manual WhatsApp popup fallback when clipboard content is not a valid phone number
- WhatsApp reference tab in the snippet manager GUI showing trigger usage and examples
- `build_release.bat` improvements:
  - Safely stages builds to temporary directory before replacing `dist\Txt Xpander`
  - Preserves the packaged app's existing `snippets.json` during distribution updates
  - Adds optional Windows Startup shortcut creation after successful build

## [2.4] — 2026-03-06

### Added

- **Working PyInstaller standalone build** in `dist\Txt Xpander`:
  - Single-directory bundle with bundled Python runtime and all dependencies
  - User-editable `snippets.json` beside the executable (seeded on first run)
  - Standalone `.exe` with packaged icon and resources
- **Snippet insertion via clipboard** (clipboard-first behavior):
  - Copy snippet text to clipboard, paste with Ctrl+V
  - Better multiline snippet reliability (each line stays intact)
  - Improved compatibility with chat applications and text fields
- **Rich-text snippet support**:
  - Snippets can now contain formatting spans (bold, italic, underline, code, strikethrough)
  - Generates HTML and RTF payloads for clipboard compatibility
  - Rich-text editing and preview in the snippet manager GUI
  - Formatting toolbar with buttons: B, I, U, S, <>, ⌫ (clear)
  - Keyboard shortcuts: Ctrl+B (bold), Ctrl+I (italic), Ctrl+U (underline), Ctrl+Shift+C (code), Ctrl+Shift+S (strikethrough)
- `x-hj` dynamic snippet: ISO date format (YYYY-MM-DD)
- Improved snippet manager GUI:
  - Better layout and resizing behavior
  - Search/filter functionality for snippets and mappings
  - Notification history viewer (🔔 button)
  - Reference tabs for date/time, economy, stocks, and WhatsApp triggers

### Fixed

- Packaged startup: app now correctly seeds and persists `snippets.json` beside the executable
- Tray icon: fixed packaged app tray icon display and notifications
- Snippet manager: improved scrollbar and resize behavior

## [2.3] — 2026-02-XX

### Added

- Dynamic economic indicators (`xdolar`, `xselic`, `xipcam`, `xcdi`, etc.) via Brazilian Central Bank API
- Dynamic stock fundamentals (`xcot`, `xplucro`, `xcap`, etc.) via yfinance
- Background task runner for slow/async operations (stock lookups, API calls)
- Snippet manager GUI with tabs for static snippets, dynamic mappings, and reference information

### Changed

- Refactored core expansion logic into modular support files

## [2.0] — 2026-01-XX

### Added

- System tray icon with enable/disable toggle
- Keyboard listener using pynput
- Basic snippet expansion (direct triggers and dynamic patterns)
- `snippets.json` persistence
- Compiled trigger index for O(1) matching
- Support for dynamic mapping containers (`_cpf_numbers`, `_cnpj_numbers`, custom types)

---

## Format Notes

- **Version numbering**: Semantic versioning (MAJOR.MINOR.PATCH)
- **Release dates**: Formatted as YYYY-MM-DD
- **Unreleased section**: Collects changes from work-in-progress branches before they're released
- **Categories**:
  - `Added`: New features
  - `Changed`: Modifications to existing functionality
  - `Fixed`: Bug fixes
  - `Technical`: Internal improvements, test coverage, performance optimizations
  - `Deprecated`: Features that will be removed in a future version
  - `Removed`: Features that have been deleted

## Versioning Strategy

- **2.x**: Stable feature releases (snippets, variables, formatting, WhatsApp actions)
- **Patch versions** (e.g., 2.7.1): Bug fixes and minor improvements
- **Pre-release tags** (if used): `-alpha`, `-beta` suffixes for testing versions
