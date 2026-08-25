# Refactor Plan: Preserve Behavior, Improve Performance and UX

Date: 2026-03-06

## Summary

This refactor should not change how the app behaves for the user today. All existing triggers, output formats, tray actions, popup flows, and `snippets.json` compatibility must remain intact. The work should focus on internal structure, performance on the keyboard hot path, robustness of persistence and GUI logic, and additive usability improvements that are disabled by default unless they are guaranteed not to alter current behavior.

## Implementation Changes

### 1. Freeze current behavior before structural changes

- Define the current app behavior as the baseline contract for the refactor.
- Preserve all existing trigger names, output strings, JSON keys, tray menu actions, and prompt flows.
- Add regression coverage for pure logic before moving code:
  - snippet loading and merge behavior
  - dynamic prefix resolution
  - direct trigger matching
  - slow-snippet routing
  - max trigger length calculation
- Create a short manual verification checklist for Windows-specific runtime behavior:
  - typing in common apps
  - tray enable/disable
  - reload snippets
  - GUI save/delete flows
  - stock ticker popup and insertion

### 2. Split the monolith without changing behavior

- Keep `sniptype.pyw` as the executable entry point only.
- Extract the current responsibilities into modules:
  - app bootstrap and runtime wiring
  - snippet repository and validation
  - matching/expansion engine
  - built-in dynamic snippet registration
  - tray UI
  - management GUI
  - ticker/input dialogs
- Preserve method behavior and return strings while moving code.
- Introduce lightweight models for runtime state, mapping definitions, and built-in snippet descriptors.

### 3. Optimize the keyboard hot path

- Replace full trigger scans on every keystroke with a precompiled trigger index built at load/reload time.
- Compile and cache direct triggers, slow triggers, dynamic prefixes, and maximum input window once per reload.
- Use suffix-oriented matching so each keypress only evaluates relevant trigger candidates.
- Keep the current backspace and typing timing unchanged in the first implementation pass.
- Recompute matching structures only when snippets are loaded, reloaded, or changed through the GUI.

### 4. Make persistence safer while keeping the same file format

- Keep `snippets.json` fully backward-compatible.
- Separate persisted data from runtime-injected callable snippets.
- Add validation when loading JSON:
  - root must be an object/dict
  - mapping containers must be dicts
  - `__prefix__` remains reserved
  - internal `_...` groups remain protected from static-trigger editing rules
- Save atomically by writing to a temporary file and replacing the original file only after success.
- Keep failure behavior conservative: if save fails, preserve the last valid file and surface the error.

### 5. Stabilize and simplify the GUI

- Extract each Tkinter tab into a dedicated class/component with explicit refresh methods.
- Replace deeply nested callbacks with controller methods that operate on shared app state.
- Fix latent GUI bugs without changing the visible workflow.
- Keep existing labels, tab structure, and core actions the same in the first pass.
- Improve reliability of list refresh, selection loading, and delete/save flows.

### 6. Improve responsiveness and internal robustness

- Replace ad hoc thread spawning with a small task runner abstraction for slow snippets.
- Centralize timeout, cache, and error-handling behavior for BCB and stock lookups.
- Keep console logging behavior but route it through one internal logging utility for consistency.
- Reuse service instances deliberately instead of recomputing dynamic metadata on the hot path.

### 7. Add user-friendly features only as additive, safe improvements

- Add GUI search/filter for snippets and dynamic mappings.
- Improve validation and error messages so they explain the problem clearly.
- Add optional backup/restore and import/export helpers for snippet data.
- Add quality-of-life actions such as duplicate snippet and quick trigger preview.
- Any new behavior that could alter the current workflow must be opt-in and disabled by default.

## Public Interfaces and Compatibility Rules

- `snippets.json` schema remains unchanged and must load all current data without migration.
- Existing built-in triggers must remain unchanged:
  - date/time triggers
  - BCB economic triggers
  - stock/fundamental triggers
  - dynamic mapping triggers based on existing prefixes
- Tray actions remain unchanged:
  - enable/disable
  - manage snippets
  - reload snippets
  - quit
- Stock snippets must still erase the typed trigger first, ask for a ticker, fetch data, and insert the result.
- Current output text formatting must remain unchanged unless a future change explicitly opts into new formatting.

## Test Plan

### Automated tests

- Load valid and invalid snippet files and verify fallback behavior.
- Verify static snippets are persisted while runtime callables are not.
- Verify direct trigger expansion and dynamic mapping expansion produce the same strings as today.
- Verify custom prefixes using `__prefix__` resolve identically to the current implementation.
- Verify the computed maximum trigger/input window covers all existing trigger forms.
- Verify slow triggers are routed to background execution and not expanded inline by the normal path.

### Manual tests

- Type common static triggers in Notepad and confirm replacement matches current behavior.
- Type dynamic mapping triggers such as `cpf...`, `cnpj...`, and custom prefixes and confirm replacement.
- Trigger built-in date and BCB snippets and confirm output formatting.
- Trigger stock snippets, enter a ticker, and confirm insertion flow remains the same.
- Open the management GUI, add/edit/delete static and dynamic items, reload snippets, and confirm persistence.
- Toggle the tray enabled state and confirm the listener respects it.

## Assumptions and Defaults

- Windows remains the only supported runtime target.
- The refactor is incremental, not a rewrite.
- Backward compatibility takes priority over code-style purity or aggressive redesign.
- Existing trigger names, JSON structure, and user-visible text are treated as fixed contracts.
- New usability improvements are additive and must not change current default behavior.
