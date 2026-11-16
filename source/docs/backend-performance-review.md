# Backend performance review

Scope: trigger detection, dispatch, insertion, background work and idle GUI
activity. Review and synthetic measurements on Windows, 2026-11-16. An
independent read-only review agreed on the fixed insertion wait and lookup
scaling as the highest-value changes.

## Implemented

- Removed three unconditional 50 ms waits before insertion. Erasure still
  finishes before worker dispatch; modal focus restoration still completes
  before insertion; TextInserter's configurable clipboard settle and restore
  delays, clipboard lock and cancellation checks are unchanged.
- Added length-based suffix hashes for dense direct-trigger buckets. Sparse
  buckets and buckets with mostly distinct lengths retain the existing scan.
  Longest-match priority, first-source ties, separate terminator modes, and
  denied-longest blocking remain unchanged.
- Compiled effective-trigger identities for successful-expansion bookkeeping,
  avoiding a full-library scan before terminator/cursor completion. Partial
  legacy indexes retain their previous fallback behavior.

## Measurements and costs

Five samples of 100 lookups each, median per call; synthetic equal-length
triggers sharing one final character. These are component measurements and
do not establish physical keyboard-to-paste latency or idle CPU reduction.

| Triggers | Miss before / after | Last hit before / after |
| --- | --- | --- |
| 100 | 4.48 / 0.27 microseconds | 11.84 / 0.26 microseconds |
| 1,000 | 53.48 / 0.30 microseconds | 58.48 / 0.28 microseconds |
| 10,000 | 535.99 / 0.26 microseconds | 566.47 / 0.23 microseconds |

The first hit of the 10,000-item bucket stayed approximately 0.23–0.25
microseconds. Index compilation measured 61 ms before and 71 ms after in
that sample; compilation is outside the listener. Added lookup containers
occupied about 416 KB for 10,000 triggers, excluding already-owned strings
and target objects. This is the explicit memory-for-lookup-work tradeoff.

The real fast-expansion method, with insertion mocked and a synthetic library,
measured 50.51 ms before and 0.017 ms after (median of 12 runs). Clipboard and
desktop input were excluded; the actual paste still pays its existing delays.

Reproduce lookup comparisons from `source`:

```powershell
python -m tests.benchmark_trigger_lookup
```

## Preserved or deferred

- Keep the 40 ms GUI pump: backing off would add popup latency, and a native
  wakeup needs separate Windows/macOS lifecycle verification. No measurement
  establishes that its 25 scheduled callbacks/second cause material CPU use.
- Keep worker isolation. A single pool queue could let slow network requests
  delay plain snippets. Dropping superseded work would change the existing
  manual-clipboard recovery behavior. Provider request coalescing is a future
  bounded change, requiring failure/cache/concurrency contracts first.
- Mapping-prefix rescans remain. The independent review measured an artificial
  many-prefix stress case, but its unusually long buffer does not establish a
  typical typing bottleneck.
- No dependency changes, provider-output changes, live-library edits, or
  clipboard timing reductions are part of this patch.

## Verification

Focused trigger/hot-path/cancellation/runtime tests and Ruff passed. New coverage
compares dense lookup with the old scan using deterministic inputs in both
terminator modes, including Unicode, ties, denied longest matches, sparse-length
fallback, compiled workflow identities and all three ready-payload routes.
The full local Windows/Python 3.12 suite passed: 1,758 tests in 305.7 seconds,
with 3 expected platform skips. Ruff passed. Cross-platform CI and native
desktop acceptance are separate evidence: component timing and unit tests
cannot certify every target application's paste behavior or physical macOS
focus/insertion. The installed executable was not rebuilt by this review.
