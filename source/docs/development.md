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

The current stable source tag is `v3.4.0`; no public binary release has been
published from this repository yet. Stable tags use
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

## Windows installer

Install Inno Setup 6, package the application, then compile the installer:

```powershell
build_release.bat
build_installer.bat
```

`build_installer.bat` compiles `installer/sniptype.iss` and writes the versioned
installer under `installer/`. The installer is per-user, does not require
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
identity. Without one, the script uses ad-hoc signing.

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
at import time. Each matrix job has a 10-minute timeout, and a newer commit
cancels older validation for the same branch or pull request.

The workflow does not currently build PyInstaller artifacts, run a linter or
type checker, audit transitive dependencies, or execute real desktop paste and
tray smoke tests. Adding those checks requires an explicit dependency and
support-matrix decision rather than an incidental workflow edit.

## Architecture references

- `AGENTS.md`: current project mechanics and load-bearing platform constraints.
- `source/docs/audit-report.md`: original audit and historical findings.
- `source/docs/improvement-plan.md`: completed phased remediation roadmap.
- `source/docs/macos-threading.md`: Tk/AppKit main-thread ownership.
- `source/docs/macos-insertion.md`: paste timings, focus handoff, and secure input.
- `source/docs/voice-input-plan.md`: voice architecture and verification status.
