# SnipType 1.5.1 stable candidate

Prepared for Windows x64; not tagged or published. Source and installer declare
1.5.1 stable for candidate packaging. The latest published stable remains 1.4.0.

Includes the 1.5.0 beta manager/features, PR #80's popup placement and startup
preparation, the subsequent structured-form monitor capture, and Teô DS 3.0.1
manager styling. The Python engine, Tk popups, and vanilla TypeScript stack stay.

## Preparation evidence

- 79 focused popup, startup, package-promotion and MSIX tests passed.
- Pinned Ruff correctness check, UI translation gate, TypeScript check and
  Vite production build passed. Tauri manager and PyInstaller package built.
- Inno Setup compiled `dist/candidate-1.5.1/SniptypeSetup-1.5.1.exe` from the
  repository installer script with isolated candidate input/output paths.
- Executable archive inspection confirmed embedded 1.5.1 stable metadata and
  the captured-monitor helper. The copied manager matches the built binary;
  the package contains no top-level user snippet library.
- No secret scanner was available. Source/metadata received manual privacy
  review; generated packages are retained locally and excluded from commits.

## Release gates

- Run the full supported CI matrix: Windows Python 3.12/3.14, macOS Python 3.14,
  and Linux Python 3.14. PR #80 had no attached check results at merge.
- Resolve or classify the local full-suite fixture logging errors. The earlier
  full run was interrupted and is not a pass.
- Verify the packaged Windows application: startup, immediate/terminator
  expansion, forms on multiple monitors, focus restoration, rich text and key
  steps, manager editing/save/conflict recovery, themes, backup/import/export,
  and installer upgrade with library preservation.
- Check physical Windows 10/11 support. Existing documentation's unverified
  accessibility, DPI and macOS behavior remain unverified.
- Run the clean-main release preparation helper after the candidate is merged.
  Review outgoing source and artifacts for private data before publishing.

The Store submission and macOS preview are separate release operations. Do not
create the stable tag or publish assets until the required gates pass.
