# Documentation index

Use the [project README](../../README.md) for installation and product behavior,
and [development.md](development.md) for current test and release commands.
This index was checked against tracked source and public issue titles on
2026-09-08. Historical measurements are evidence for their recorded environment,
not certification of the current release.

| Category | Documents and scope |
| --- | --- |
| Active contracts and plans | [Sync format](sync-design.md): implemented desktop export and historical mobile consumer requirements; desktop metadata remains local. [TextExpander features 2–4](textexpander-features-2-4-plan.md): source implementation and automated validation complete; release smoke pending. |
| Implemented design records | [Variables and tray](features-plan.md), [WhatsApp actions](whatsapp-plan.md), and [WhatsApp v2](whatsapp_v2-plan.md). Current behavior is in the linked source/tests, not old rollout commands. |
| Platform design and historical host evidence | [Tk/AppKit threading](macos-threading.md) and [macOS insertion](macos-insertion.md). A new Mac package still needs physical focus, TCC, paste, and startup checks. |
| Historical audits and plans | [July audit](audit-report.md), [phased remediation](improvement-plan.md), [original refactor proposal](refactor-plan.md), and [September cleanup audit](cleanup-audit-2026-09.md). Dates, counts, and unresolved-at-audit labels are snapshots. |

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

The current feature implementation is local/private by default: schema-v1
metadata, groups and application policy, structured forms, favorites,
session-only Recent/edit-last, preview, and optional hotkeys are documented in
the runtime reference and README. No release or physical desktop validation is
claimed here; see the feature plan for the remaining final-validation matrix.

Voice-specific contracts, plans, and research now belong to the independent
Snipvoice project in the sibling `../snipvoice` directory. Its extraction record
is `source/docs/extraction.md`. Sniptype handles text/keyboard input only.
Historical Sniptype audits and changelogs remain here.
