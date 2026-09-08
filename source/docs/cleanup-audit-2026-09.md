# September 2026 cleanup audit

Baseline: `853d558d4fa3f6b4ed931772037d9595329349be`, matching `origin/main`.
The starting checkout was clean. All major directories were inspected, with
independent source review, caller searches, focused checks, and a full Windows
test run. This report distinguishes the small implemented cleanup from larger
findings filed for focused remediation.

## Changes and removal evidence

| Change | Evidence and preserved behavior |
| --- | --- |
| Reject dynamic renames beginning with `_` ([#34](https://github.com/rteoo/sniptype/issues/34)) | Before the fix, `_broken` passed validation and bound a provider, but was excluded from the compiled trigger index. A new regression failed before the guard. A renamed stable registry key with internal `_` still binds and matches. The GUI already returns before persistence on validation errors; stored overrides and mapping semantics are unchanged. |
| Print startup counts without library content ([#37](https://github.com/rteoo/sniptype/issues/37)) | A synthetic trigger/payload stdout regression failed before removing the preview loop. Static counts retain the same non-mapping/non-callable predicate. No real library was opened to verify this. |
| Remove `Sniptype.get_all_dynamic_prefixes()` | Full repository search found only its definition. Callers use `get_dynamic_prefixes()` directly; the indexed keyboard path remains intact. |
| Remove `calculate_max_trigger_length()` | Only its own obsolete tests/import referenced it. Production uses `calculate_max_trigger_length_with_mappings()`; its empty-input and composed-trigger boundaries remain tested. |
| Remove one duplicate saveable-snippets test | The two test bodies had identical ASTs and stateless inputs/assertions. The earlier live-value-over-shadow regression remains. |
| Remove unused `URLError` import | No production consumer used the imported name. BCB exception-path tests import their own exception and still pass. |
| Remove stale hotpath defect comments | Enter/backspace regressions already pass; the assertions remain, with comments claiming a current known defect removed. |
| Correct current documentation/output text | GitHub release metadata confirms beta.2; installer `OutputDir=Output` confirms the real destination. README tab labels match the manager, and macOS signing text matches its existing fallback. Old audit/roadmap instructions are explicitly historical. |

No dependency, model, snippet seed, generated package, release channel, or
runtime insertion/voice lifecycle behavior was changed by the cleanup.

## Directory coverage

The baseline contains 116 tracked files: 38 source Python modules, 43 test/helper
files, 17 source documents, plus packaging, metadata, data seeds, and assets.

| Area inspected | Review/disposition and improvement tracking |
| --- | --- |
| Root build scripts, README, changelog, license/notices | Read Windows/macOS staging, promotion, installer invocation and source launcher; corrected output/release/signing text. Recovery-path follow-up: [#35](https://github.com/rteoo/sniptype/issues/35). Notice inventory remains a release responsibility. |
| `.github/workflows` | Reviewed the full six-job OS/Python matrix, dependency installation, timeouts, and cancellation. Optional runtime coverage: [#31](https://github.com/rteoo/sniptype/issues/31); focused lint adoption: [#32](https://github.com/rteoo/sniptype/issues/32). |
| `installer` | Reviewed `sniptype.iss`, metadata, output destination, files, shortcuts, mutexes, and uninstall data boundary. Corrected output descriptions; no installer was built or run. |
| `source` core/data | Reviewed paths, backups, persistence, settings, registry, indexed matching, variables, rich text, clipboard/insertion, sync export, WhatsApp, BCB and stock helpers, and their callers. Reserved rename fixed; registry boolean semantics tracked in [#36](https://github.com/rteoo/sniptype/issues/36). |
| `source` manager/platform | Reviewed `sniptype.pyw`, GUI helpers/thread, themes, platform support and macOS permissions. Removed unused wrapper; startup output fixed. Mapping validation: [#41](https://github.com/rteoo/sniptype/issues/41); early secure-input notice: [#42](https://github.com/rteoo/sniptype/issues/42). |
| `source` voice | Reviewed capture/resampler, provider/runtime, model catalog/downloads, controller, dispatch, history, settings/text replacements, hotkeys, indicators/overlay, probes, and related tests/docs. Lifecycle findings: [#38](https://github.com/rteoo/sniptype/issues/38), [#39](https://github.com/rteoo/sniptype/issues/39), [#40](https://github.com/rteoo/sniptype/issues/40). Readiness/old harness: [#43](https://github.com/rteoo/sniptype/issues/43). |
| `source/tests` | Scanned exact duplicate test AST bodies, checked fixture differences and production consumers, and reviewed behavioral/platform tests. Removed only one duplicate and tests exclusive to a dead helper. Added regressions for the two fixes. |
| `source/docs` | Inspected current architecture, voice research/contracts, sync design, completed feature plans and historical roadmap. Historical issue numbers need repair: [#33](https://github.com/rteoo/sniptype/issues/33). |
| `dist`, `installer/Output`, caches and test temporary files | Inventoried as generated/local artifacts. Kept packaged copies, prior release artifacts and caches intact. These were not treated as dead source or deployed for this audit. |
| `.git`, `.claude/worktrees`, ignored root files | Inspected repository/worktree metadata and local directory inventory. Git reports this checkout as the only registered worktree. Preserved local leftovers; the private history backup bundle and user data were excluded from content inspection/publication. |

## Findings requiring follow-up

| Priority | Issue | Verified evidence / completion condition |
| --- | --- | --- |
| P1 | [#35 — package recovery](https://github.com/rteoo/sniptype/issues/35) | Independently reviewed failure branch ignores restore `robocopy` status and deletes the previous package. `/e` can retain extra staged files. Requires failure injection and exact rollback/retention proof in a disposable output tree. No live package failure was induced. |
| P1 | [#38 — voice startup race](https://github.com/rteoo/sniptype/issues/38) | Event-gated fake capture: release during start returned false and left recording active. Concurrent presses opened two captures. Reserve/serialize the starting session and cover release/cancel/shutdown. |
| P1 | [#39 — late insertion after cancellation](https://github.com/rteoo/sniptype/issues/39) | Blocked fake target restoration, cancelled, then resumed: insertion callback still received the transcript while outcome was cancelled. Recheck session validity at side-effect boundaries. |
| P1 | [#40 — stale retry](https://github.com/rteoo/sniptype/issues/40) | A delayed fake transcription returned after a language change and still completed history/copied text. Fence all retry side effects by generation, not a reusable cancel event alone. |
| P2 | [#41 — mapping input validation](https://github.com/rteoo/sniptype/issues/41) | Source review/replayed assignment shows `__prefix__` treated as metadata; real helpers prove duplicate prefixes hide the earlier mapping and new static collisions produce no warning. Add actual manager-action tests before changing saves. |
| P2 | [#36 — registry booleans](https://github.com/rteoo/sniptype/issues/36) | String `"false"` is truthy, explicitly characterized by existing tests. Define invalid-value and migration behavior before changing runtime/GUI/export interpretation. |
| P2 | [#43 — voice readiness/probes](https://github.com/rteoo/sniptype/issues/43) | Capture availability is not used as a readiness gate; the standalone harness has a stale callback and no tracked consumers. Consolidate diagnostics and test production capture readiness with fake hardware. |
| P2 | [#31 — native runtime CI](https://github.com/rteoo/sniptype/issues/31) | CI installs only core requirements; the real SoXR assertion can skip. Add a supported optional-runtime lane where that test is required. |
| P3 | [#42 — startup notice](https://github.com/rteoo/sniptype/issues/42) | Source ordering starts the listener before the icon; direct notification can be dropped. Queue the existing notice and test startup flush/cooldown; physical macOS timing remains unverified. |
| P3 | [#32 — lint](https://github.com/rteoo/sniptype/issues/32), [#33 — documentation provenance](https://github.com/rteoo/sniptype/issues/33) | Adopt a narrowly configured development linter with explicit tooling approval; repair historical issue links without exposing private material. |

The concurrency reproductions used fake capture/providers/targets and isolated
temporary history. Clipboard/insertion observations were in-memory callbacks.
These are implementation-level failures, not physical-device recordings.

## Candidates deliberately retained

- The identical no-collision bodies in `test_data_safety.py` have different
  static-versus-mapping fixtures; both protect meaningful behavior.
- GUI-thread closures, theme methods, platform adapters and Cocoa focus barriers
  encode OS/lifecycle constraints. A small wrapper is not sufficient removal proof.
- Static rename rejects an existing destination as overwrite protection. Its
  difference from confirmed static/dynamic coexistence on save is not a proven bug.
- Hidden streaming and model adoption gates remain intentionally disabled or
  unverified; historical plans do not prove unfinished runtime defects.
- The standalone voice harness remains pending the diagnostic decision in #43;
  it was not silently replaced with another compatibility wrapper.

## Verification

- Baseline in the sandbox: `python -m unittest discover -s tests -v` — 1,335 tests,
  58 skips, no failures. The extra GUI skips were caused by sandbox access to Tcl.
- Outside the sandbox, the installed Tcl probe returned **8.6.15**, allowing real
  Windows Tk tests without a runtime/configuration change.
- Final full suite, native Windows Python **3.14.6**:
  `python -m unittest discover -s tests -v -f` — **1,336 tests**, **5 skips**, no
  failures, **19.666 seconds**. Four skips are platform-specific; the remaining
  SoXR skip is covered by the separate native DSP run below.
- Native DSP: all **5** `tests.test_voice_resampler` tests passed using the already
  present isolated SoXR **1.1.0** runtime, including streaming equivalence and
  alias-band rejection. Nothing was installed.
- Focused registry/snippet/BCB modules: **134 passed**; sync export: **109 passed**;
  hotpath: **52 passed**; final startup suite: **23 tests, 1 platform skip**.
- One intermediate full native run was stopped after repeated manager GUI
  timeouts. The isolated manager suite then passed **26/26**, and the final full
  run above passed. The transient timeout's root cause remains unconfirmed.
  Independent review also caught a mismatched shared-test-helper call introduced
  during this cleanup; it was corrected before the final full run.
- AST syntax parsing and standard-library `tabnanny` indentation lint cover all
  **81 tracked Python files**, including `.pyw`; `git diff --check` and Bash syntax
  checking of `build_release_macos.sh` pass. A recursive attempt hit inaccessible
  ignored caches; the successful check was rerun on tracked files only.
- No Ruff/pyflakes/project lint configuration is available. The checks above are
  syntax/indentation/whitespace checks, not a claim of full semantic lint coverage.
- Packaged builds, installation, physical cross-application paste/voice,
  macOS TCC/focus, and Wayland behavior were not exercised. This cleanup is not a
  release-promotion or desktop certification.
