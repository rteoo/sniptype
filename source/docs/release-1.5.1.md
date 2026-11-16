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
- The initial full run completed 1,749 tests with 2 failures, 110 errors and
  3 skips. Serial reproduction found an X11-only keysym rejected by Windows
  Tk and a label callback converting Tcl distances with Python `int`.
  Both were fixed; the two failing GUI tests and 129 theme/popup/startup tests
  then passed, along with Ruff. The full-suite rerun was stopped after 637
  seconds, exceeding the repository's 10-minute CI job limit; it is incomplete,
  not a pass. Repeated deleted-fixture log-handler errors remained in the output.
- Logging reconfiguration now closes only stale app-owned file handlers while
  preserving caller-owned sinks. Its regression tests pass; the local suite's
  output fell from hundreds of megabytes to hundreds of kilobytes.
- CI was manually disabled and was re-enabled with owner approval. The first
  restored matrix completed all 1,751 tests per lane but failed on a label test
  double missing `winfo_pixels`. The double was corrected, Tcl-distance coverage
  was added, and all 65 widget/runtime-support tests plus Ruff passed locally.
  Current full-matrix results are attached to [PR #81](https://github.com/rteoo/sniptype/pull/81).

## Release gates

- Run the full supported CI matrix: Windows Python 3.12/3.14, macOS Python 3.14,
  and Linux Python 3.14. PR #80 had no attached check results at merge.
- Obtain passing full-matrix results at the final release revision. The initial
  local run failed and its first post-fix rerun exceeded the CI time limit;
  neither is passing evidence. Later fixes and results are recorded above.
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
