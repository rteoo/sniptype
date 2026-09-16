# TextExpander benchmark features 2–4: implementation plan

Status: source implementation and automated validation complete; release smoke pending

Date: 2026-09-16

Scope: richer fill-ins, groups/application policy, and workflow shortcuts

Use this plan when implementing items 2–4 from the
[TextExpander benchmark](textexpander-benchmark.md#recommended-implementation-order-for-sniptype).
Read [the runtime reference](agent-runtime-reference.md) before changing form
dialogs, trigger detection, expansion dispatch, GUI threading, clipboard
insertion, or macOS focus handling.

This status records the current implementation state, not a release
certification. The source and focused tests cover the metadata boundary,
richer forms, groups/application policy, workflow state, preview, and optional
hotkeys. The complete source suite passes (1,319 tests, 53 platform/display
skips), including disposable-data recovery/import, mirror, and sync contracts.
Ruff was unavailable in the validation environment. Packaged smoke and physical
cross-application/platform checks remain required before calling the feature
set release-ready.

## Outcome

Implement the three features without changing the default behavior of an
existing metadata-free library:

1. Richer fill-ins: defaults, multiline input, choices, optional content,
   repeated named values, and a date picker.
2. Groups and application policy: labels, notes, runtime prefixes, enable
   state, terminator policy, and Windows executable allow/deny rules.
3. Workflow shortcuts: safe preview, metadata-aware duplicate, edit last
   expanded, favorites/recent, and configurable action hotkeys.

The implementation remains local and offline. It adds no account, hosted sync,
passive phrase harvesting, persistent raw-keystroke history, or new runtime
dependency.

## Locked design decisions

### One embedded metadata boundary

Store new definitions under a reserved `__sniptype__` root entry in
`snippets.json`. Split that entry from snippet content before runtime merge and
reassemble it before the existing atomic save.

```json
{
  "xhello": "Hello %%name%%",
  "__sniptype__": {
    "kind": "sniptype_metadata",
    "schema_version": 1,
    "groups": {
      "3c59901d-1ff9-4c9e-aab8-26330519800c": {
        "label": "Work",
        "notes": "",
        "prefix": "w",
        "enabled": true,
        "terminator": "inherit",
        "applications": {
          "mode": "all",
          "executables": []
        }
      }
    },
    "items": {
      "static": {
        "xhello": {
          "group_id": "3c59901d-1ff9-4c9e-aab8-26330519800c",
          "favorite": false,
          "form": {
            "fields": []
          }
        }
      },
      "mappings": {}
    }
  }
}
```

This location makes the existing atomic write, rotating backups, mirror, and
JSON import/export protect content and metadata together. The reserved key is
not a snippet, variable reference, or mapping container. Mobile sync continues
to omit it.

`Ungrouped` is implicit and is not serialized. Missing metadata means current
behavior. A future schema version is preserved and loaded in read-only
compatibility mode: snippets still work, while metadata mutations are disabled
with a visible warning.

### Stable identity and effective trigger

The stored snippet key remains its identity and the name used by
`%%snippet_ref%%`. A group prefix changes only the effective trigger compiled
for keyboard matching:

```text
stored key:        xhello
group prefix:      w
effective trigger: wxhello
```

Moving a snippet or editing a group prefix must not rewrite snippet keys or
references. The manager displays both values. Exact effective-trigger
collisions block the mutation; prefix/suffix reachability hazards use the
existing warn-and-confirm pattern.

Groups initially apply to direct static snippets. Dynamic mappings and
registry-backed dynamic snippets retain their current tabs, prefixes, enable
state, and global terminator behavior.

### Deep module interfaces

Add focused support modules instead of growing `Sniptype`:

- `library_metadata.py`: metadata schema, normalization, split/join, import
  merge, and item/group mutations.
- `form_support.py`: field validation, legacy inference, compilation, and pure
  rendering.
- `form_dialog.py`: Tk controls and a standard-library calendar picker; GUI
  thread only.
- `preview_support.py`: side-effect-free preview resolution.
- `hotkey_support.py`: hotkey normalization and press/release routing.

`sniptype.pyw` remains the orchestrator. `trigger_index.py` remains the owner of
compiled keyboard lookup structures. `platform_support.py` owns Windows
foreground executable discovery.

## Current implementation seams

- `variable_support.py` classifies `%%name%%`; clipboard and snippet references
  take precedence over form fields.
- `trigger_index.py` compiles last-character buckets, slow triggers, form
  triggers, and mapping prefixes. Matching is longest-first.
- `Sniptype._handle_char` currently chooses one global immediate/terminator
  branch. Mixed group policies require compiled buckets rather than per-key
  metadata scans.
- `Sniptype.run_slow_snippet` resolves inline variables, obtains form values,
  rebuilds rich text, and inserts on a worker.
- `_show_form_dialog` currently creates one `Entry` per unique unknown
  variable. `_run_modal_dialog` serializes dialogs and owns focus restoration.
- `rich_text_support.rebuild_rich_text` remaps spans through substitutions.
- The static manager already has Duplicate; extend that action rather than
  creating a second duplication path.
- `_run_expansion` is the shared success boundary. Add workflow history there;
  `last_expansion_time` remains failure-throttling state.

## Ordered checkpoints

Each checkpoint is one implementation commit unless the changed diff is too
large to review safely. Every checkpoint ends with its focused tests green and
leaves the full suite runnable.

### 1. Establish the metadata boundary

Change:

- Add `library_metadata.py` with:
  - `split_library_document(document)`;
  - `build_library_document(snippets, metadata)`;
  - `normalize_metadata(metadata, available_items)`;
  - `merge_metadata(existing, imported, import_result)`.
- Split metadata before static/dynamic merge in `Sniptype.load_snippets`.
- Reassemble metadata inside the current save path before `write_json_atomic`.
- Exclude the reserved entry from snippet counts, manager lists, variable
  classification, trigger indexes, and sync export.
- Make backup restore and replace/merge import metadata-aware.
- Preserve unknown fields within schema version 1.
- Load valid snippet content when metadata is malformed. Preserve the malformed
  raw block and disable metadata edits instead of quarantining the entire
  library.

Import rules:

- Replace import replaces both content and metadata; a legacy file yields empty
  metadata.
- Merge import keeps the current content rule: imported values win on duplicate
  snippet keys.
- Identical group IDs/definitions are reused.
- A conflicting imported group ID receives a new UUID and its imported item
  assignments are remapped.
- Imported metadata wins for a snippet whose imported content wins.

Validate:

- Add `test_library_metadata.py` for missing, valid, malformed, future-version,
  Unicode, rich-text, mapping, orphan, split/join, and merge cases.
- Extend snippet persistence, backup/import, GUI count, variable, trigger-index,
  and sync-export tests.
- Prove a metadata-free library round-trips with unchanged runtime semantics.

Completion criterion: the reserved entry survives save, backup, restore,
mirror, replace import, merge import, and export while remaining absent from
every runtime trigger surface.

### 2. Compile and render richer forms

Change:

- Add `form_support.py` with field types:
  - `text`;
  - `multiline`;
  - `choice`;
  - `date`;
  - `optional`.
- Continue using `%%name%%` in snippet content; store field definitions in item
  metadata.
- Treat unresolved legacy variables without metadata as implicit `text`
  fields.
- Reuse one field value for every repeated placeholder of the same name.
- For `optional`, substitute configured literal content when selected and an
  empty string otherwise.
- Store selected dates as ISO dates and render through an explicit
  `output_format`, default `%d/%m/%Y`.
- Reject duplicate definitions and names that resolve as clipboard, static,
  mapping, or dynamic references; those names are unreachable under current
  variable precedence.
- Render structured values in one regex pass so user-entered `%%...%%` text is
  literal. Preserve the legacy chaining behavior for metadata-free forms.
- Teach trigger compilation to identify metadata-defined forms once per index
  rebuild.

Validate:

- Add `test_form_support.py` for defaults, multiline values, choices, invalid
  defaults, dates, optional content, repeated names, Unicode, missing/extra
  definitions, collisions, and malformed specs.
- Extend trigger-index and rich-text tests for structured form detection and
  span remapping after multiline/optional substitution.

Completion criterion: pure compilation and rendering cover every field type,
and trigger detection needs no metadata or regex scan per keystroke.

### 3. Add the form editor and expansion controls

Change:

- Add `form_dialog.py` and pass a compiled form specification to
  `_show_form_dialog`.
- Render:
  - `Entry` for text;
  - scrollable `Text` for multiline;
  - read-only `ttk.Combobox` for choices;
  - `Checkbutton` for optional content;
  - editable date entry plus a month-grid picker built with `calendar` and
    `datetime`.
- Prefill defaults. Keep the dialog open and focus the offending control after
  validation errors.
- Retain `_run_modal_dialog`, the one-dialog lock, native focus barriers, and
  cancel semantics. A cancellation inserts no text and re-emits no terminator.
- Add a form-definition editor to static snippets. Reuse it for mapping items
  after the static path is green.

Validate:

- Extend `test_manager_gui_smoke.py` through its shared `GuiThread` root. Never
  create a disposable in-process `tk.Tk()` probe.
- Exercise every widget, default submission, invalid date, cancel, keyboard
  submission, dialog serialization, and rich expansion.
- Run `test_gui_thread.py` and `test_ui_theme.py`.

Completion criterion: every structured form can be authored, persisted,
reopened, completed, cancelled, and expanded without touching Tk outside the
GUI thread.

### 4. Add group management and prefix compilation

Change:

- Add a group filter/sidebar to the Snippets tab and a focused group settings
  dialog.
- Support create, edit, delete, assign, and move-to-Ungrouped operations.
- Add a group selector to the static editor.
- Show stored and effective triggers in the list/editor.
- Compile `group.prefix + stored_key` as the direct runtime trigger.
- Remove disabled groups from the runtime index while keeping them editable.
- Keep metadata for a static key shadowed by a dynamic trigger; the dynamic
  entry retains runtime precedence.
- Roll back in-memory group/item mutations when persistence fails.

Validate:

- Test CRUD, assignment, deletion-to-Ungrouped, prefix changes, shadowed
  statics, exact collisions, reachability warnings, import remapping, and save
  rollback.
- Add manager smoke coverage for group filtering, selection, effective trigger
  display, and persisted reopening.

Completion criterion: group changes are atomic with the library document,
references retain their stored identities, and only enabled groups contribute
effective triggers.

### 5. Support mixed terminator policies on the indexed hot path

Change:

- Add an `ExpansionTarget` value carrying effective trigger, source kind, and
  stable source identity. Keep compatibility wrappers for existing trigger
  helper callers.
- Compile separate longest-first buckets for immediate and terminated direct
  triggers.
- Resolve policy in this order:
  1. group `immediate` or `terminator`;
  2. group `inherit` uses global `terminator_mode`;
  3. mappings/dynamic snippets use global `terminator_mode`.
- On each character, test an immediate match against the full buffer. On a
  terminator, test a terminated match against the body when no immediate match
  fired.
- Pass a snapshot `ExpansionTarget` to the worker so a concurrent manager
  refresh cannot redirect queued work.

Validate:

- Extend `test_trigger_index.py` and `test_hotpath.py` for mixed policies,
  prefixes, long triggers, punctuation-ending triggers, disabled groups,
  terminator re-emission, collision precedence, and refresh races.
- Assert the hot path performs no disk access, GUI work, or linear group scan.

Completion criterion: mixed group policies preserve longest-first matching and
current buffer/worker barriers with no extra per-key persistence work.

### 6. Enforce Windows executable policy before erasure

Change:

- Add a Windows foreground-identity helper to `platform_support.py` using
  `GetForegroundWindow`, `GetWindowThreadProcessId`, `OpenProcess`,
  `QueryFullProcessImageNameW`, and `CloseHandle`.
- Persist only a case-folded executable basename such as `outlook.exe`; never
  persist full paths.
- Cache results by HWND/PID in a small bounded cache.
- Resolve identity only after a candidate trigger matches and before erasing
  the typed text.
- Apply:
  - `all`: allow;
  - `allow`: allow listed executables and fail closed on unknown/unsupported
    identity;
  - `deny`: block listed executables and allow unknown identity.
- When the longest match is denied, leave the typed text intact and do not fall
  through to a shorter trigger.
- Label executable rules as Windows-only in the manager. An allowlist copied to
  an unsupported platform fails closed.
- Document basename matching as an accidental-expansion control, not an
  authentication boundary.

Validate:

- Extend `test_platform_support.py` for success, access denied, vanished
  process, handle closure, Unicode paths, case normalization, cache behavior,
  and non-Windows behavior.
- Hot-path tests prove no identity query occurs without a trigger candidate and
  denied triggers are neither erased nor dispatched.
- Manually verify an allowed and denied group across at least Notepad, a
  browser, and one additional Windows application.

Completion criterion: every scoped expansion decision occurs before erasure,
with bounded candidate-only OS work and deterministic unknown-identity rules.

### 7. Add workflow state and manager navigation

Change:

- Introduce a `SnippetRef` for static, mapping, and registry-backed items.
- Extend manager opening with an optional target that selects the correct tab
  and row whether the manager is new or already open.
- Record successful insertions centrally in `_run_expansion`.
- Add a separately locked `last_successful_item`; keep
  `last_expansion_time` dedicated to failure throttling.
- Maintain a session-only, bounded recent deque of 20 item references. Store no
  content and write no recent history to disk.
- Add Favorites and Recent virtual filters.
- Persist favorites for static and mapping items. Dynamic actions can appear in
  the session Recent view but are not persistent favorites in version 1.

Validate:

- Test success/failure/cancel recording, bounded ordering, concurrent workers
  completing out of order, deleted targets, and absence of recent-history disk
  writes.
- Test target navigation into an existing and a newly built manager.

Completion criterion: edit-last and Recent always identify the latest
successful insertion, never a cancelled/failed/action-only attempt.

### 8. Complete preview, duplicate, and edit-last

Change:

- Add `preview_support.py` with a pure preview resolver.
- Resolve static and mapping references locally. Render explicit placeholders
  for clipboard and dynamic values.
- Preview may collect form values or use defaults, then show plain/rich output
  in a read-only `Text` widget.
- Preview never reads the clipboard, invokes a provider, opens a URL, writes to
  a target application, or mutates usage state.
- Extend the existing Duplicate action to copy content, form definitions, and
  group assignment. Require a new stored key. Start the copy as non-favorite
  and absent from Recent.
- Add Edit last expanded to the tray and manager. A removed item produces a
  concise unavailable notice.

Validate:

- Use clipboard, provider, browser, and inserter spies to prove zero preview
  side effects.
- Test plain/rich/form preview, duplicate persistence and rollback, and
  edit-last for static, mapping, dynamic, removed, cancelled, and failed items.

Completion criterion: preview is observational, duplicate preserves all
content behavior without copying workflow state, and edit-last navigates to the
correct surviving item.

### 9. Add configurable workflow hotkeys

Change:

- Add `hotkey_support.py` and optional settings for:
  - open manager;
  - edit last expanded;
  - toggle enabled.
- Leave all bindings unset by default.
- Add an `Atalhos…` dialog from the manager header.
- Reject duplicate bindings, modifier-only bindings, and unmodified printable
  keys.
- Wire `on_press` and `on_release` into `pynput.keyboard.Listener`.
- Process hotkeys before ordinary trigger characters. A consumed hotkey clears
  the typed buffer.
- Hotkey callbacks dispatch worker actions or `GuiThread.submit`; they perform
  no Tk or disk work on the listener thread.

Validate:

- Add `test_hotkey_support.py` for parsing, duplicate rejection, modifier
  order, press/release state, repeat suppression, AltGr-adjacent cases, and
  disabled bindings.
- Extend listener tests to prove hotkey characters cannot fire a snippet.
- Extend settings tests for malformed bindings, unknown-key preservation, and
  atomic save failure.

Completion criterion: configured actions fire once per chord, ordinary typing
is unchanged when no bindings exist, and the listener thread retains its
current safety contract.

### 10. Close compatibility and documentation

Change:

- Update the README, runtime reference, sync design, and documentation index.
- Document metadata recovery, group prefix semantics, form field types,
  executable-policy limits, hotkeys, and privacy behavior.
- State that mobile sync version 1 still exports form field names but not
  desktop widget definitions/defaults.
- Add fixtures for legacy JSON, metadata JSON, old backups, and merge conflicts.

Validate:

- Exercise metadata-free and metadata-aware backup, restore, export, replace
  import, merge import, mirror, and sync export under a disposable
  `SNIPTYPE_HOME`.
- Inspect the full task-owned diff and final repository status.

Completion criterion: every persisted representation has a tested upgrade,
round-trip, merge, and failure path, and public documentation matches observed
runtime behavior.

## Dependencies and compatibility

- Add no package dependency. Use Tk/ttk, `calendar`, `datetime`, `uuid`, and the
  existing `pynput` runtime.
- The first metadata-aware save adds the reserved entry lazily; there is no
  bulk migration.
- Current flat libraries load unchanged. Legacy imports become Ungrouped and
  infer existing single-line forms.
- Global `terminator_mode` remains the fallback for Ungrouped, `inherit`,
  mappings, and dynamic snippets.
- The mobile bundle schema remains version 1. Structured desktop field types
  are not a mobile contract in this implementation.
- Windows is the supported executable-policy backend. macOS/Linux behavior is
  explicit and fail-closed for allowlists.

## Edge cases that must stay visible

- A shorter immediate trigger can make a longer terminated trigger unreachable.
- Two groups can compile different stored keys to the same effective trigger.
- A dynamic trigger can continue to shadow a static key carrying metadata.
- A foreground process can close between HWND, PID, and executable queries.
- Rich spans around a placeholder may expand across multiline inserted text.
- A form default can become invalid after choice options or date format change.
- An imported group ID can collide with a different local definition.
- A future metadata schema can be understood by neither the current UI nor
  runtime; preserving it is safer than rewriting it.
- A hotkey chord can overlap AltGr or an application shortcut.
- A previewed snippet can contain clipboard or dynamic references whose real
  value is intentionally unavailable in preview.

## Safe implementation delegation

Lock the metadata schema in checkpoint 1 before parallel work. After that,
independent agents may own:

- `form_support.py` and its pure tests;
- Windows executable identity and platform tests;
- `hotkey_support.py` and settings tests;
- preview resolution and side-effect tests;
- compatibility fixtures and documentation after interfaces stabilize.

Use one integration owner for `sniptype.pyw`, `trigger_index.py`, and manager
GUI wiring. Those surfaces share runtime state and should not receive
overlapping parallel edits.

## Final validation

Run from the repository root:

```powershell
cd source
python -m unittest discover -s tests -v
cd ..
python -m ruff check source
```

Then run a disposable-`SNIPTYPE_HOME` Windows desktop matrix:

- legacy library with no metadata;
- every form control, default, repeat, invalid input, and cancel path;
- prefix, disabled group, and mixed terminator policies;
- executable allow/deny across Notepad, a browser, and one denied application;
- preview with clipboard/network/action spies or observable equivalents;
- duplicate, edit-last, favorites, Recent, and every configurable hotkey;
- backup, restore, export, replace import, merge import, mirror, and sync export;
- source-run cross-application insertion and packaged PyInstaller smoke.

## Definition of done

All focused and full automated checks pass; metadata-free libraries preserve
their current behavior; no new runtime dependency or external data flow exists;
the listener performs no disk or GUI work; application policy is decided before
erasure; all metadata has tested recovery/import/export behavior; and the
packaged Windows app passes the physical cross-application matrix.
