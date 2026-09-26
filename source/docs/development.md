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

Core runtime requirements are in `source/requirements.txt`. Voice transcription
now belongs to the separate Snipvoice project; its dependencies are not required
by current Sniptype source or release builds.

## Release channels

The current Windows stable release is `v1.0.0`, also published to the
Microsoft Store. The macOS ARM64 package is the
`v0.14.4-beta.1` preview pending its packaged desktop validation. Stable tags use
`vMAJOR.MINOR.PATCH`; beta tags use `vMAJOR.MINOR.PATCH-beta.N` and their GitHub
Releases are prereleases. Both channels share the same user-data directory and
installer identity, so they must not run simultaneously.

Do not promote a beta to stable until the supported-OS test matrix and packaged
desktop smoke tests pass. The app docstring owns `Version:` and `Channel:`;
`installer/sniptype.iss` mirrors them as `MyAppVersion` and `MyAppChannel`.

## Windows package

Install the existing build requirements, then use the staging script:

```powershell
python -m pip install -r source\requirements.txt pyinstaller
build_release.bat
```

The script builds an onedir release in a temporary directory and replaces
`dist\Sniptype` only after success. The hidden import `pystray._win32` is
required. Voice runtime collection and its packaged probe now belong to Snipvoice.
Generated `build`, `dist`, and spec output must not be edited by hand.

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
python3 -m pip install -r source/requirements.txt pyinstaller
./build_release_macos.sh
```

Set `PYTHON=/path/to/python` to select an interpreter and
`CODESIGN_IDENTITY="Developer ID Application: ..."` to use a real signing
identity. Otherwise the script tries the local `Sniptype Dev` identity, then
the pre-rebrand `Txt Xpander Dev` certificate, and falls back to ad-hoc signing
when neither is available or signing fails. Over SSH, `codesign` usually cannot
reach the private key (`errSecInternalComponent`); build from a Terminal on the
Mac once and allow the keychain prompt.

The script builds `dist/Sniptype.app`, asserts that the generated icon is both
present and referenced, adds `LSUIElement`, and re-signs after the plist change
before promotion. The
selected Python interpreter determines the bundle architecture; the current
Apple Silicon release is ARM64-only.

Ad-hoc rebuilds change the bundle cdhash and invalidate Input Monitoring and
Accessibility grants. A stable signing identity preserves those grants across
builds. The app also restores accessory activation policy after Tk creates the
root, because `LSUIElement` alone does not keep an Aqua Tk app out of the Dock.

## Continuous integration

`.github/workflows/ci.yml` runs the unittest suite on Windows with Python 3.12
and 3.14, plus Python 3.14 on macOS and Ubuntu. This pairwise matrix covers each
platform path and both supported Python lines without testing every redundant
combination. Linux uses Xvfb because pynput and pystray bind to Xorg at import
time, and that same lane runs the pinned Ruff checks selected in `ruff.toml`
(`F401`, `F811`, and `F821`). Each matrix job has a bounded timeout, and a newer
commit cancels older validation for the same branch. CI runs on every branch
push so its checks attach to the exact commit used by branch protection;
`workflow_dispatch` remains available for diagnostic reruns.

Run the same focused lint command locally from the repository root:

```powershell
python -m pip install -r source/requirements-dev.txt
python -m ruff check source
```

Ruff is a development-only dependency; its pin is separate from release runtime
requirements. The initial rule set checks unused imports, duplicate definitions,
and undefined names, without formatting churn. Generated output and temporary
test fixtures are excluded.

The workflow does not build PyInstaller artifacts, run a type checker, audit
transitive dependencies, or execute real desktop paste and tray smoke tests.

## Architecture references

- `AGENTS.md`: current project mechanics and load-bearing platform constraints.
- `source/docs/audit-report.md`: original audit and historical findings.
- `source/docs/improvement-plan.md`: completed phased remediation roadmap.
- `source/docs/macos-threading.md`: Tk/AppKit main-thread ownership.
- `source/docs/macos-insertion.md`: paste timings, focus handoff, and secure input.
- Sibling Snipvoice project (`../snipvoice`): extracted voice architecture and verification status.
