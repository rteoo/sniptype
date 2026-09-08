# Development and release builds

This document contains maintainer workflows. The project overview and user
instructions live in the repository [README](../../README.md).

## Source setup

Run commands from the repository root unless noted otherwise.

```powershell
cd source
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
pythonw sniptype.pyw
```

Use `python sniptype.pyw` when console output is useful. The source-side
`source\run_sniptype.bat` launcher checks the core dependencies and starts the
app with `pythonw`.

Core runtime requirements are in `source/requirements.txt`. Optional voice
capture and native transcription requirements are pinned separately in
`source/requirements-voice.txt`; missing them keeps voice unavailable without
affecting ordinary expansion.

## Release channels

The current stable source tag is `v3.4.0`; the current preview release is
`v3.5.0-beta.2`. Stable tags use
`vMAJOR.MINOR.PATCH`; beta tags use `vMAJOR.MINOR.PATCH-beta.N` and their GitHub
Releases are prereleases. Both channels share the same user-data directory and
installer identity, so they must not run simultaneously.

Do not promote a beta to stable until the supported-OS test matrix and packaged
desktop smoke tests pass. The app docstring owns `Version:` and `Channel:`;
`installer/sniptype.iss` mirrors them as `MyAppVersion` and `MyAppChannel`.

## Windows package

Install the existing build requirements, then use the staging script:

```powershell
python -m pip install -r source\requirements.txt -r source\requirements-voice.txt pyinstaller
build_release.bat
```

The script builds an onedir release in a temporary directory, runs the packaged
`--voice-runtime-probe`, and replaces `dist\Sniptype` only after success. The
hidden import `pystray._win32` and the voice package collection arguments are
required. Generated `build`, `dist`, and spec output must not be edited by hand.

User data is not stored in `dist`; it remains under `~/.sniptype`. The build
keeps a one-time safety copy of any legacy packaged `snippets.json` but never
restores it into the new package.

If a failed promotion leaves `dist\Sniptype.previous`, the next build refuses
to continue. Inspect the restored package and retain that recovery copy until
recovery is confirmed; the build does not silently discard it on retry.

For a packaged manager smoke test, stop the other Sniptype instance, set
`SNIPTYPE_HOME` to a disposable directory containing synthetic data, and start
`dist\Sniptype\Sniptype.exe --show-manager`. The flag opens the manager after
the shared GUI root starts; ordinary startup remains tray-only.

## Windows installer

Install Inno Setup 6, package the application, then compile the installer:

```powershell
build_release.bat
build_installer.bat
```

`build_installer.bat` compiles `installer/sniptype.iss` and writes the versioned
installer under `installer/Output/`. The installer is per-user, does not require
administrator rights, and leaves `~/.sniptype` intact when uninstalling.

The installer is unsigned. Windows SmartScreen therefore warns on first use.
Code signing is a separate release decision.

## macOS package

Use a native Python toolchain for the target architecture:

```bash
python3 -m pip install -r source/requirements.txt -r source/requirements-voice.txt pyinstaller
./build_release_macos.sh
```

Set `PYTHON=/path/to/python` to select an interpreter and
`CODESIGN_IDENTITY="Developer ID Application: ..."` to use a real signing
identity. Otherwise the script tries the local `Sniptype Dev` identity and
falls back to ad-hoc signing when that identity is unavailable or signing fails.

The script builds `dist/Sniptype.app`, asserts that the generated icon is both
present and referenced, adds the `LSUIElement` and microphone metadata, re-signs
after the plist change, and runs the packaged voice probe before promotion. The
selected Python interpreter determines the bundle architecture; the current
Apple Silicon release is ARM64-only.

Ad-hoc rebuilds change the bundle cdhash and invalidate Input Monitoring and
Accessibility grants. A stable signing identity preserves those grants across
builds. The app also restores accessory activation policy after Tk creates the
root, because `LSUIElement` alone does not keep an Aqua Tk app out of the Dock.

## Continuous integration

`.github/workflows/ci.yml` runs the unittest suite on Windows, macOS, and Ubuntu
with Python 3.12 and 3.14. Linux uses Xvfb because pynput and pystray bind to Xorg
at import time. A separate native voice matrix installs the pinned
`requirements-voice.txt`, installs Ubuntu's `libportaudio2`, requires all four
native imports, and runs the runtime/resampler tests without allowing skips; it
does not access a microphone or download a model. The focused lint job installs
the dev-only Ruff pin from `source/requirements-dev.txt` and applies the rules
selected in `ruff.toml` (`F401`, `F811`, and `F821`) to source Python and `.pyw`
files. Each matrix job has a bounded timeout, and a newer commit cancels older
validation for the same branch or pull request.

Run the same focused lint command locally from the repository root:

```powershell
python -m pip install -r source/requirements-dev.txt
python -m ruff check source
```

Ruff is a development-only dependency; its pin is separate from release runtime
requirements. The initial rule set checks unused imports, duplicate definitions,
and undefined names, without formatting churn. Generated output and temporary
test fixtures are excluded.

The native lane targets Python 3.12 and 3.14 on the hosted 64-bit runners. The
pinned native distribution supplies Windows x64, Linux x64, and macOS x64/ARM64
wheels; the CI runner tests its own architecture, not every wheel architecture.
Other interpreter/architecture combinations and microphone permissions are not
established by this lane. The core-only matrix keeps graceful optional-runtime
skips and prints their reasons with verbose unittest output.

The workflow does not build PyInstaller artifacts, run a type checker, audit
transitive dependencies, or execute real desktop paste and tray smoke tests.

## Architecture references

- `AGENTS.md`: current project mechanics and load-bearing platform constraints.
- `source/docs/audit-report.md`: original audit and historical findings.
- `source/docs/improvement-plan.md`: completed phased remediation roadmap.
- `source/docs/macos-threading.md`: Tk/AppKit main-thread ownership.
- `source/docs/macos-insertion.md`: paste timings, focus handoff, and secure input.
- `source/docs/voice-input-plan.md`: voice architecture and verification status.
