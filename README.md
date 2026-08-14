# Txt Xpander

Txt Xpander is a Windows text expander with a system tray app, snippet manager GUI, dynamic snippets, formatted text support, WhatsApp quick-link automation, and a packaged standalone build.

## Release Channels

- **Stable — `v3.3.0`**: the current production release. Stable tags use `vMAJOR.MINOR.PATCH` with no suffix; Windows produces `TxtXpanderSetup-3.3.0.exe`.

Beta tags use `vMAJOR.MINOR.PATCH-beta.N` and the corresponding GitHub Release must be marked as a prerelease. Beta and stable builds share the same data directory and installer identity, so an upgrade preserves `~/.txt_xpander`; do not run both channels simultaneously. Promote a beta to stable only after the full supported-OS test matrix and packaged desktop smoke tests pass.

## Project Layout

- [`dist\Txt Xpander\`](dist/Txt%20Xpander): packaged app folder to run or ship (`dist/Txt Xpander.app` on macOS — see [Build on macOS](#build-on-macos)).
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
5. The delays in the insertion path have per-OS defaults and can each be overridden in `settings.json`: `clipboard_settle_delay` (clipboard write → paste shortcut; 0.05 s on Windows and Linux, 0.02 s on macOS, where `pbcopy` only returns after the pasteboard is written), `paste_restore_delay` (paste → restoring the previous clipboard; 0.12 s everywhere) and `erase_key_delay` (between the backspaces that erase the trigger; 0.01 s everywhere). Values must be numbers between 0 and 2 seconds — anything else is ignored, logged at startup, and the platform default is used. Details and the macOS measurements are in `source/docs/macos-insertion.md`.
6. The built-in `xwapp` trigger reads a phone number from the clipboard, creates a `wa.me` link, opens it in the browser, and keeps the final link in the clipboard.
7. The built-in `xlwapp` trigger follows the same validation flow but inserts the generated `wa.me` link into the current field and also keeps that link in the clipboard.
8. The built-in `xpwapp` trigger skips clipboard lookup, opens the popup immediately for phone and optional message entry, then opens the browser and keeps the final link in the clipboard.
9. If `xwapp` or `xlwapp` cannot normalize the clipboard content into a valid phone number, the app opens the same popup for manual phone and optional message entry.
10. Before replacing the packaged folder with a newer build, close any running `Txt Xpander.exe` first.
11. `build_release.bat` keeps a one-time safety copy of any existing packaged `snippets.json` when updating `dist\Txt Xpander`. User data is no longer stored in `dist` — it lives in `%USERPROFILE%\.txt_xpander`, so a rebuild never touches the live library.

### Auto-start with Windows

Right-click the tray icon and tick **Iniciar com o sistema**. Txt Xpander creates the Startup shortcut for the current user (pointing at the packaged executable, or at `pythonw txt_xpander.pyw` when running from source); unticking it removes the shortcut. No admin rights, no registry keys.

The same toggle is the autostart path on macOS (LaunchAgent plist) and Linux (`~/.config/autostart` entry).

[`build_release.bat`](build_release.bat) still offers to create the Startup shortcut after a successful build (skipped automatically if the shortcut already exists), and you can always drop a shortcut into `shell:startup` yourself.

### Cross-platform status

Txt Xpander is Windows-first. The OS-specific couplings are factored behind [`source/platform_support.py`](source/platform_support.py): the paste modifier (Ctrl+V on Windows/Linux, Cmd+V on macOS), a PID-lockfile single-instance guard for non-Windows (Windows keeps its named mutex), per-OS autostart install/remove (Startup `.lnk`, macOS LaunchAgent plist, Linux `.desktop`) driven by the tray toggle, which event loop owns the main thread (see below), and the `PYSTRAY_BACKEND=win32` pin, now applied on Windows only. The pin previously ran unconditionally, forcing a backend that cannot import off Windows and killing startup before any seam had a chance to run. The keyboard listener (pynput), tray (pystray), GUI (Tk) and the JSON data layer are portable, and the data directory (`~/.txt_xpander`) is identical on all three OSes. The macOS LaunchAgent is now verified to actually start the app (`launchctl bootstrap` against the plist the toggle writes); the Linux `.desktop` entry is still covered only by its write tests.

macOS gives Tk and AppKit a single main thread between them, which is the one place the two OSes genuinely diverge (issue #24, [`source/docs/macos-threading.md`](source/docs/macos-threading.md)). On Windows `icon.run()` blocks the main thread and the shared Tk root lives on a worker; on macOS the root is created on the main thread first, pystray is handed the `NSApplication` Tk just created, the tray goes up with `run_detached()`, and `mainloop()` blocks. The `GuiThread.call`/`submit` contract is identical in both modes, so the manager GUI and every dialog open on macOS.

Clipboard access is factored the same way, behind [`source/clipboard_support.py`](source/clipboard_support.py): Windows keeps the ctypes user32/kernel32 backend (text, HTML and RTF), while macOS uses `pbcopy`/`pbpaste` and Linux uses `wl-copy`/`wl-paste` under Wayland, falling back to `xclip` then `xsel`. The Win32 bindings now load only on Windows, so the app imports cleanly on macOS/Linux. Rich text works on macOS too — `pbcopy` cannot carry HTML, so a rich payload is written by piping an AppleScript pasteboard record through `osascript`, falling back to plain text if that fails. Linux is still plain-text only (rich snippets paste as their plain text and log the downgrade), and a desktop with none of those tools installed logs a warning rather than failing hard.

CI is configured to run the unit suite on `windows-latest`, `macos-latest` and `ubuntu-latest` (Python 3.12 and 3.14) on every pull request, so the POSIX branches of the clipboard, autostart and single-instance code are exercised on real macOS and Linux hosts rather than only under mocks. Linux runs under `xvfb-run`: pynput and pystray both bind to Xorg at import time and raise without a display. When hosted runners are unavailable, a beta may be prepared from local evidence, but it is not promoted to stable until this matrix or equivalent physical hosts pass.

On macOS the app also has to ask for permission before it can work at all: **Input Monitoring** for the global listener and **Accessibility** for the synthesized Cmd+V. pynput reports neither — an untrusted listener starts, stays alive and simply never delivers a key — so [`source/macos_permissions.py`](source/macos_permissions.py) probes both directly (`IOHIDCheckAccess` and `AXIsProcessTrusted`) at startup. When one is missing the app logs it, notifies from the tray, keeps a `⚠ Permissões do macOS` entry in the menu and opens a window that deep-links the exact System Settings pane. A re-check button confirms the grant and asks for a restart rather than pretending a refused listener came back to life. Nothing here runs off macOS.

macOS **Secure Keyboard Entry** (Terminal's menu item, a focused password field, the login window) is a separate gate that cannot be granted: while it is on the system drops synthesized keystrokes in both directions. The app checks for it *before* erasing the trigger, so a snippet typed into a password field is left exactly as typed — never half-erased — and the tray explains why nothing expanded. The insertion delays themselves are per-OS and settings-overridable; the values, the measurements behind them and the manual matrix still to be run on a granted Mac are in [`source/docs/macos-insertion.md`](source/docs/macos-insertion.md).

macOS has a packaged build of its own — a menu-bar-only `.app` produced by [`build_release_macos.sh`](build_release_macos.sh), see [Build on macOS](#build-on-macos). Remaining before the app runs unmodified on macOS/Linux: rich-text paste on Linux, opening the data folder (still `os.startfile`, with no POSIX equivalent in place yet; `open_url_in_browser` only uses it as a fallback behind the portable `webbrowser` path), plus the platform limit outside our control — Wayland restricts global keyboard hooks. The Tk smoke tests stay skipped on macOS because they drive the *worker-thread* root, which AppKit does not permit — the app itself uses the main-thread mode above, so this is a test-harness limit, not an app one. What CI does *not* cover is end-to-end behavior on a real desktop session: tray icon, actual paste into another app, and expansion after the macOS grants are still unverified.

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

### Voice input (unreleased)

Voice is **not** in the stable `v3.3.0` packaged build. The module lives on
`feat/voice-input` (PR #66): default-off, optional, and isolated from
expansion. Enabling **Entrada por voz** without the optional `sounddevice` +
`transcribe-cpp` backend reports unavailable — that is expected. Only the
Balanced/Parakeet profile is user-selectable. Status, gates, and what is still
unproven are in [`source/docs/voice-input-plan.md`](source/docs/voice-input-plan.md).

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

### Build on macOS

[`build_release_macos.sh`](build_release_macos.sh) is the macOS counterpart. It builds `dist/Txt Xpander.app` — a **menu-bar-only** bundle (`LSUIElement`, so no Dock icon and no app menu), with the `.icns` generated from the shipped `.ico` at build time. `LSUIElement` alone is not enough: Aqua Tk sets the Regular activation policy while it creates the root, which overrides the plist at runtime, so the app puts the policy back to *accessory* right after (`platform_support.hide_dock_icon()`) — that is what actually keeps it out of the Dock, and it applies to a source checkout too.

```bash
python3 -m pip install -r source/requirements.txt pyinstaller
./build_release_macos.sh
```

Use `PYTHON=/path/to/venv/bin/python ./build_release_macos.sh` to build with a specific interpreter, and `CODESIGN_IDENTITY="Developer ID Application: …"` to sign with a real identity instead of ad-hoc.

Like the Windows script it stages into a temp folder and swaps `dist` only on success, and it refuses to run while the app is running. It deliberately does **not** port the Windows-only steps: there is no Startup shortcut to offer (macOS autostart is the LaunchAgent the tray toggle writes) and no packaged `snippets.json` to preserve (user data lives in `~/.txt_xpander`).

The script produces the native architecture of the selected Python interpreter. The current `3.3.0` bundle is built on Apple Silicon and is **ARM64-only**; it does not run on Intel Macs. An Intel or universal release requires a matching Python/dependency toolchain and a separate verified build.

First launch, Gatekeeper and permissions:

1. Without an accessible signing identity the bundle falls back to **ad-hoc signing**. If Gatekeeper blocks the first launch, right-click the app → **Open** once, or run `xattr -dr com.apple.quarantine "dist/Txt Xpander.app"`.
2. Grant **Input Monitoring** and **Accessibility** in *System Settings → Privacy & Security* — pynput cannot see keystrokes without them, and the app logs `This process is not trusted!` until they are granted.
3. **TCC grants are tied to the bundle's signing identity.** Under ad-hoc signing there is no identity, so macOS pins the grant to the binary's *cdhash* and every rebuild silently revokes it: the switch still shows as on, the app still probes `denied`. Removing the stale row (the **−** button) and adding the rebuilt app again is the manual fix — the permanent one is a stable identity, below.

#### A stable signing identity (stops the permission churn)

Create a self-signed code-signing certificate once, and every later build keeps the grants:

```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 3650 -nodes \
  -subj "/CN=Txt Xpander Dev" \
  -addext "basicConstraints=critical,CA:false" \
  -addext "keyUsage=critical,digitalSignature" \
  -addext "extendedKeyUsage=critical,codeSigning"
openssl pkcs12 -export -out identity.p12 -inkey key.pem -in cert.pem -name "Txt Xpander Dev" \
  -certpbe PBE-SHA1-3DES -keypbe PBE-SHA1-3DES -macalg sha1 -passout pass:txpdev
security import identity.p12 -k ~/Library/Keychains/login.keychain-db -P txpdev -T /usr/bin/codesign
security add-trusted-cert -r trustRoot -p codeSign -k ~/Library/Keychains/login.keychain-db cert.pem
```

`security import` needs an unlocked login keychain, so run it in your own terminal session (the legacy PKCS#12 algorithms are required — macOS cannot read OpenSSL 3's defaults). The build script picks the identity up automatically when `security find-identity -v -p codesigning` lists **Txt Xpander Dev**, and falls back to ad-hoc when it does not; `CODESIGN_IDENTITY` still overrides. Signing with an identity is what makes the app's designated requirement reference the *certificate* instead of the cdhash, so the TCC rows keep matching after a rebuild. Grant the permissions once more after the first signed build — that grant is the last one you need.

Autostart: tick **Iniciar com o sistema** in the menu-bar menu. Inside a bundle `sys.executable` is `Txt Xpander.app/Contents/MacOS/Txt Xpander`, so the LaunchAgent (`~/Library/LaunchAgents/com.txt-xpander.plist`, `RunAtLoad`) runs that path directly — no `open -a` wrapper needed; launchd starting it that way still gets the bundle's Info.plist and identity. Verified by loading the generated plist with `launchctl bootstrap gui/$UID`; survival across a real reboot has not been tested.

## Build The Installer (Setup.exe)

For a real install experience — installs to a proper per-user location, adds Start Menu / optional Desktop shortcuts, an optional "start with Windows" checkbox, and a proper entry in **Apps & features** with an uninstaller — build a Windows installer with [Inno Setup](https://jrsoftware.org/isdl.php).

One-time prerequisite: install **Inno Setup 6** (free).

```powershell
build_release.bat      REM 1) package the app into dist\Txt Xpander
build_installer.bat    REM 2) compile installer\Output\TxtXpanderSetup-<version>-<channel>.exe
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
