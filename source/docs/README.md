# Documentation index

Use the [project README](../../README.md) for installation and product behavior,
and [development.md](development.md) for current test and release commands.
This index was checked against tracked source and public issue titles on
2026-09-08. Historical measurements are evidence for their recorded environment,
not certification of the current release.

| Category | Documents and scope |
| --- | --- |
| Active contracts | [Sync format](sync-design.md): implemented desktop export and historical mobile consumer requirements. [Voice behavior](voice-behavior-contract.md): offline probe and failure boundaries. |
| Implemented design records | [Manager voice controls](manager-voice-controls-plan.md), [variables and tray](features-plan.md), [WhatsApp actions](whatsapp-plan.md), and [WhatsApp v2](whatsapp_v2-plan.md). Current behavior is in the linked source/tests, not old rollout commands. |
| Platform design and historical host evidence | [Tk/AppKit threading](macos-threading.md) and [macOS insertion](macos-insertion.md). A new Mac package still needs physical focus, TCC, paste, and startup checks. |
| Mixed implementation status and remaining measurements | [Voice input plan](voice-input-plan.md). Physical microphone-to-paste, device loss, target-machine latency/accuracy, and Mac package validation remain distinct from offline tests. |
| Historical audits and plans | [July audit](audit-report.md), [phased remediation](improvement-plan.md), [original refactor proposal](refactor-plan.md), and [September cleanup audit](cleanup-audit-2026-09.md). Dates, counts, and unresolved-at-audit labels are snapshots. |
| Research snapshots | [Model value comparison](voice-model-value-research.md), [ASR candidate triage](asr-trending-candidate-triage.md), [Gemma evaluation](gemma-4-asr-evaluation.md), and [Voxtype review](voxtype-speech-to-text-research.md). These do not change the shipped model catalog or prove live ASR quality. |

## Historical reference audit

The original work items predate this public repository's issue sequence.
The numerical references in the following documents were checked against the
current public destinations and replaced with source links or descriptive work
names. No private repository links are needed to preserve the design evidence.

| Document | Old numbers | Current destinations and repair |
| --- | --- | --- |
| macOS threading | 24 | Now the installed voice-model digest PR. Link to `gui_thread.py` and `platform_support.py` instead. |
| macOS insertion | 27 | Now the clipboard-variable failure PR. Link to `runtime_support.py` and `platform_support.py` instead. |
| Sync format | 30, 31, 32, 34, 43 | Now voice capture, native CI, lint, reserved dynamic renames, and voice diagnostics. Replace with desktop exporter, original bundle design, iOS keyboard/import plan, and static-preservation descriptions. |
| September cleanup audit | 31–43 | Verified current issue subjects match the recorded findings; keep these public links as the audit trail. |

The sync producer is [sync_export.py](../sync_export.py), with
[behavioral tests](../tests/test_sync_export.py). The iOS sections describe an
external consumer contract; this repository does not verify an iOS application.
