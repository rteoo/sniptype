# Tk manager retirement plan

Status: phase 0 skipped (Teô's call, 2026-11-06); phase 1 in review as stacked PRs

Date: 2026-11-05

Scope: move every manager capability into the Tauri window on Windows and
macOS, then delete the classic Tk manager

SnipType 1.4.0 made the Tauri window (`ui/`, `source/manager_bridge.py`) the
Windows manager. The classic Tk manager in `source/sniptype.pyw` (about 5,000
lines, `_show_manager_window` and everything it builds) still ships. It is the
fallback when the window cannot run and the only manager on macOS. This plan
gets it to zero. Read [the runtime reference](agent-runtime-reference.md)
before touching GUI threading, expansion, or the bridge.

## What "fully off Tk" means here

The goal is to delete the Tk manager. Tk itself stays in the process, and this
plan keeps it there on purpose:

- **Typing-time popups stay Tk.** That covers the ticker prompt
  (`ask_ticker_input`), the WhatsApp input (`ask_whatsapp_input`), form
  fill-in (`form_dialog.FormDialog` and the legacy per-name dialog) and the
  macOS permission window. The 2026-10-29 decision holds: they open
  in-process, instantly, and hand focus back for the paste. A WebView2 window
  costs about 360 MB resident or about 0.5 s per trigger.
- **The Tk runtime pieces stay with them.** `gui_thread.GuiThread`,
  `ui_theme`, and the `ui_widgets` dialog kit (`entry`, `button`,
  `text_area`, `dialog_footer`, `alert`) all stay, and so does
  `gui_support.center_on_screen` and `focus_modal_input`. The bridge also
  answers on the GUI thread (`ManagerProcess._answer` → `app.gui.call`).

Revisit the popups only if a measured, always-resident WebView popup process
becomes acceptable. That is a separate decision with its own memory budget,
and it is not part of this plan.

## Where things stand (audit, 2026-11-05)

### Parity gaps in the Tauri window

The 1.4.0 docs said nothing still needed the Tk manager. That was wrong. These
Tk capabilities have no Tauri equivalent; evidence is the Tk method and an
empty search of `ui/src` and the bridge's method table.

| # | Gap | Tk source | Impact |
|---|---|---|---|
| 1 | Expansion state (ok / paused / down) and Pausar/Retomar in the window; last-expansion line | `_refresh_manager_status`, `toggle_enabled(in_manager=True)`, `_manager_last_expansion_var` | High: the tray still toggles, but the window cannot show or fix the state |
| 2 | InfoBar recovery actions (Retomar, Abrir backups, Abrir pasta, Abrir log, Tentar agora) and dismiss | `_run_health_action`, `_dismiss_health`; `app.info.issues` carries no action id | High: trouble is shown as text with no way to act |
| 3 | Open drafts react to library changes ("A biblioteca mudou…", Usar a versão nova / Manter rascunho) | `EditorSession`, `_show_library_conflict` | High (data): a tray reload or external edit leaves a stale draft with no warning, and the window refreshes lists only on focus |
| 4 | Inserir variável menu and Ctrl+Shift+R / V / F (reference picker, clipboard, form field) | `_create_static_snippets_tab` toolbar | Medium: authors must type `%%…%%` by hand |
| 5 | Workflow hotkeys in Configurações | `_build_hotkeys_card` | Medium: the tray item opens the Tk `hotkey_dialog`, which survives today but must not depend on the manager |
| 6 | Ctrl+K switcher, Ctrl+E edit last, Ctrl+1–5 pages, Ctrl+/ keyboard map, Esc (clear search, then discard with confirmation) | `_bind_manager_commands`, `_show_manager_switcher`, `_show_manager_keyboard_map`, `_escape_manager_editor` | Medium: keyboard-first workflow regressions |
| 7 | Window size, position and last page restored | `_capture_manager_view` / `_restore_manager_view`, `manager_view` setting | Medium |
| 8 | Data card: mirror and sync state lines, Copiar, Tentar agora (`retry_sync`); notification history | `_build_data_card`, `_open_notification_history` | Low–medium: sync retry and history are unreachable on Windows since 1.4.0 |
| 9 | Receipts for tray and hotkey commands, empty-library Importar, "Mostrar na lista", Backups path Copiar | `receipt(in_manager=…)`, empty state, editor header | Low |

`_create_reference_tab` has no caller. It is dead code to delete, not a gap.

### macOS

`build_release_macos.sh` does not package the window, so deleting Tk today
would leave the Mac build with no manager. The audit found:

- **Location:** `find_manager_executable` already looks for `sniptype-manager`
  beside `sys.executable`. Inside the bundle that is `Contents/MacOS/`, so no
  Python change is needed.
- **Export picker:** `exportLibrary` calls `window.showSaveFilePicker`, which
  WKWebView is not expected to provide (unverified). Export would then fail on
  a Mac.
- **Platform hardcoding:** `ui/index.html` hardcodes
  `<body data-platform="windows">`, and the tokens use Segoe and Cascadia.
  Hints say "Ctrl+…", although the shortcuts already accept Meta.
- **Dock and focus:** a bare Tauri binary started by an `LSUIElement` parent
  defaults to a regular activation policy. Expect a Dock icon and possibly a
  window that opens behind others (unverified).
- **Signing:** the binary has to be copied in before the `plutil` edits and
  signed before the bundle. The script uses `codesign --deep` today.
- **Icon:** `tauri.conf.json` lists only `sniptype.ico` as its icon.

### What the bridge still borrows from the Tk code

These `Sniptype` methods are not Tk, but they live next to it and must
survive the deletion:

- `_manager_rows` and `_invalidate_manager_rows`
- `_manager_static_projection` and `_manager_dynamic_triggers`
- `_persist_manager_action` and `_persist_manager_static_action`
- `_manager_issues` and `_pending_manager_target` / `_manager_target`

Both `_persist_*` methods end in `_refresh_manager_lists()`, which belongs to
the Tk block. `_library_replaced` and `_request_health_refresh` push only to Tk
widgets. Three modules the bridge imports for pure logic import `tkinter` at
the top: `group_dialog`, `form_editor_dialog` and `preview_dialog`.

## Plan

Each phase is one or more PRs on the repo's normal loop: branch, tests, PR,
merge on Teô's word. Gates are listed per phase; nothing moves to the next
phase on a red gate.

### Phase 0: restore the way back (1.4.1)

Until phase 1 lands, Windows users have no route to gaps 1–9 except editing
`settings.json` by hand, and even that setting was removed in 1.4.0.

1. Bring back the Gerenciador clássico card in Configurações and
   `app.openClassicManager`. Copy: "Recursos que esta janela ainda não tem
   (inserir variável, atalhos de teclado, histórico de notificações) continuam
   no gerenciador clássico." → verify: bridge test that the method opens
   `_show_manager_window`, and the i18n gate.
2. Correct AGENTS.md and DESIGN.md: list the gaps instead of claiming parity →
   verify: doc review.
3. Ship 1.4.1 stable through the usual release path → verify: full suite and
   the packaged smoke test, and the card opens the Tk manager in the packaged
   build.

Do not bring back the `manager_ui` opt-out: the card is enough, and it goes
away again in phase 3.

### Phase 1: Windows parity (1.5.0-beta.1)

Each gap becomes a bridge method that reuses the existing app method, which is
the rule in AGENTS.md. Order follows impact.

Progress (2026-11-06). Each slice is one PR, stacked in this order; each was
driven in the real window over CDP against an in-process app, not in a
packaged build:

| Gap | Pull request | State |
|---|---|---|
| 1–2 expansion state, health actions, push events | rteoo/sniptype#63 | in review |
| 3 draft conflicts and the stale-save guard | rteoo/sniptype#64 | in review |
| 4 Inserir variável | rteoo/sniptype#62, with #65 (another session; also `%%` completion and new tokens) | merged |
| 5 hotkeys in Configurações | rteoo/sniptype#66 | in review |
| 6 keyboard workflow | rteoo/sniptype#67 | in review |
| 7 window state | rteoo/sniptype#68 | in review |
| 8 data card and notifications | rteoo/sniptype#69 | in review |
| 9 small items | — | empty-library Importar already existed; tray and hotkey receipts on the window's status line and Mostrar na lista remain |

1. **Push events from the app to the window.** Add
   `ManagerProcess.send({"event": "library"})` and `{"event": "health"}` from
   `_library_replaced`, `_request_health_refresh`, `toggle_enabled`, reload and
   save-failure paths. Replace the Tk-only `_refresh_manager_lists` tail in the
   `_persist_*` methods with that push. → verify: bridge tests that each path
   emits once, and that no event is sent with no process.
2. **Expansion state and health actions (gaps 1–2).**
   - `app.info` returns `expansion` (from `health_support.expansion_state`) and
     each issue's `action` and `dismissible`.
   - New `app.toggleEnabled` (`toggle_enabled(in_manager=True)`),
     `health.run(action)` (`_run_health_action`) and `health.dismiss`.
   - The sidebar shows the state and Pausar/Retomar; the InfoBar renders the
     action button.

   → verify: bridge tests per action, and a packaged check that pausing from
   the window updates the tray icon and pausing from the tray updates the
   window.
3. **Draft conflicts (gap 3).** On `library` events and on focus, the window
   asks `snippet.get` / `mapping.get` for the open item's stored value. It then
   applies `editor_session`'s rules: unchanged draft → reload silently; changed
   → "A biblioteca mudou" with Usar a versão nova / Manter rascunho; item gone
   → keep the draft as new. Keep the decision logic in `editor_session` (Python,
   tested) and expose a `draft.reconcile` result, so the TS side only renders
   it. → verify: `test_editor_session` cases driven through the bridge, plus a
   manual run that edits `snippets.json` behind an open draft.
4. **Inserir variável (gap 4).**
   - Add a toolbar menu and Ctrl+Shift+R / V / F to `richtext.ts`, inserting
     `%%trigger%%`, `%%clipboard-paste%%` and `%%field%%` as plain text.
   - The reference picker lists from `library.list` and the dynamic triggers.

   → verify: `npm run build`, and a manual check that the inserted token
   previews correctly through `preview.get`.
5. **Hotkeys in Configurações (gap 5).**
   - `hotkeys.get` and `hotkeys.set` validate with `hotkey_support` and
     re-register through the existing path.
   - Capture the chord in the WebView with keydown; only validated
     combinations are stored.
   - The tray's Configurar atalhos opens the window at Configurações >
     Atalhos.

   → verify: bridge tests for validation, conflicts and clearing, and a
   packaged check that a new hotkey works without restarting.
6. **Keyboard workflow (gap 6).** Add Ctrl+K switcher over `library.list` with
   "Criar …", Ctrl+E (`app.takeTarget` for the last expanded item), Ctrl+1–5
   pages, Ctrl+/ shortcut sheet, and Esc to clear search, then offer to discard
   the draft through `resolveDraft`. → verify: manual keyboard pass with
   Narrator off and on.
7. **Window state (gap 7).** Save size, position, maximized state and last page
   through `settings.set` into the existing `manager_view` key, and restore it
   with `manager_view_support.geometry_intersects_monitors` on the Python side.
   Use no new Tauri plugin. → verify: unit tests for normalization, and a
   manual check that it reopens where it closed and comes back on screen after
   a monitor is unplugged.
8. **Data and history (gap 8).** Add mirror and sync status lines with Copiar
   and Tentar agora (`retry_sync`), and a Notificações page over the existing
   history. → verify: bridge tests, and a packaged check with a mirror
   directory set.
9. **Small items (gap 9)**, batched into one PR.

Gate to beta: full suite, ruff, `npm run build`, packaged smoke, and a written
parity checklist (the gap table above) walked by hand in the packaged build.
Then flip phase 0's card copy to "kept for one more release".

**Testing decision needed.** `ui/` has no test runner. The bridge carries the
logic and is covered by unittest; the TS rendering is covered only by
`tsc --noEmit` and manual runs. Adding Vitest (with jsdom) is a new
devDependency and needs Teô's approval. The other option is a scripted CDP
smoke on the packaged window, driven from Python. That needs no new
dependency, but CDP port 9333 may be taken by SnipVoice, so use 9339. Choose
before phase 1 starts. The recommendation is the CDP smoke, because it tests
the shipped binary.

### Phase 2: macOS window (1.5.0-beta.2)

This phase needs a Mac with the Rust toolchain and the Xcode command line
tools. It cannot be verified from the Windows machine.

1. **Build.** Add a `build_manager_macos.sh` mirroring `build_manager.bat`: npm
   ci, touch `main.rs`, `npx tauri build --no-bundle`, and copy to
   `Contents/MacOS/sniptype-manager`. `build_release_macos.sh` calls it after
   staging and before `plutil`. A failure leaves `dist` untouched. → verify:
   `lipo -info` shows arm64, and the staged bundle contains the binary.
2. **Signing.** Sign the manager binary explicitly, then the bundle; keep
   `codesign --verify --deep --strict`. → verify: script asserts, plus
   `test_tray_startup` and `test_build_release_promotion` text checks for the
   new lines. Keep the existing asserted lines intact.
3. **Activation policy.** In `main.rs` on macOS, set the accessory policy (no
   Dock icon), add a minimal Edit menu so Cmd+C/V/X/A/Z work in fields, and
   activate the app on the `focus` event. → verify: the window opens in front
   from the menu-bar item, no Dock icon appears, and copy and paste work in
   the editor.
4. **Export (decision needed).** Replace `showSaveFilePicker` on macOS. The
   options:
   - `@tauri-apps/plugin-dialog` plus `plugin-fs`: new dependencies, needs
     approval.
   - A small Rust command that uses `rfd` through Tauri's existing dialog
     support: check whether it is already a transitive dependency before
     calling it new.
   - An `<a download>` Blob fallback: no dependency, but WKWebView behavior
     must be verified.

   Recommendation: try the Blob fallback first, and take the plugin only if it
   fails. → verify: export from the packaged Mac app produces the same file as
   on Windows.
5. **Platform look.** Set `data-platform` at startup from the bridge's
   `app.info` (add `platform`). Add a macOS font stack in `app.css`, since the
   tokens are verbatim copies and must not be edited. Show ⌘ in hints on
   macOS. Add `sniptype.icns` or the PNG to `tauri.conf.json` icons. →
   verify: screenshots in light and dark mode.
6. **Docs.** Update AGENTS.md, DESIGN.md (the macOS manager section) and the
   README's macOS status.

Gate to 1.5.0 stable: phase 1 and 2 checklists walked in packaged builds on
Windows and macOS, TCC grants re-checked after the rebuilt bundle, and one beta
soak with no regressions reported.

### Phase 3: delete the Tk manager (1.6.0-beta.1)

This phase starts only after 1.5.0 has shipped stable on both platforms.

1. **Fallback.** `open_manager` calls the Tauri window or reports the problem
   with `notify_error` ("O gerenciador não abriu" plus the log path). It never
   opens a Tk window. Remove the "abrindo o gerenciador clássico" strings and
   phase 0's card.
2. **Split pure logic out of Tk modules first** (its own PR, no behavior
   change). Move `build_group_definition`, `GroupDialogController` and the
   label constants out of `group_dialog`, `FormEditorController` and
   `type_label` out of `form_editor_dialog`, and `build_preview_model` out of
   `preview_dialog`, into Tk-free modules. The bridge must not import
   `tkinter`. → verify: a test that imports `manager_bridge` with `tkinter`
   blocked in `sys.modules`.
3. **Delete the manager block** in `sniptype.pyw`:
   - `_show_manager_window`, `_build_manager_window`, every `_create_*_tab`,
     every `_build_*_card`, `_bind_manager_commands`, the switcher, the
     keyboard map, notification history, the editor header and handle, the
     library-conflict dialog, `_refresh_manager_*` and receipts routing.
   - `manager_window` state and `_release_manager_ui_refs`.
   - Rewrite `notify` routing, `reload_snippets`, `quit_app` and
     `_quit_with_manager` so they never assume a Tk window.

   → verify: full suite; `grep` finds no `_show_manager_window` and no
   `manager_window`; and the app runs from source with no `ui/` build and
   reports the missing window.
4. **Delete the Tk-only modules and code paths:**
   - `run_group_dialog`, `run_form_editor` and `PreviewDialogController` with
     their Tk UI.
   - `gui_support`'s tree and layout helpers; keep `center_on_screen` and
     `focus_modal_input`.
   - `ui_widgets` nav, tree, list, card, InfoBar and `ReceiptLine` (confirm
     each has no popup caller first).
   - `EditorSession`'s Tk-only state, if phase 1 did not move it to the
     bridge.
   - `manager_geometry_for_tk`.
   - `hotkey_dialog`, once phase 1 step 5 has shipped.
5. **Tests.**
   - Delete `test_manager_gui_smoke` (125 tests) and `test_gui_support`, and
     the Tk widget parts of `test_ui_widgets`.
   - Split `test_manager_continuity` and `test_manager_runtime`: keep the
     health facts, registry, projection-cache and edit-last tests, and drop
     timers, rebinding and the status line.
   - Before deleting, port the English-UI leak check (the smoke test builds
     the manager in English and fails on Portuguese) into a check over the
     bridge's strings plus the existing `ui` i18n gate.
6. **Docs.**
   - AGENTS.md: the layout list, the runtime reference sections on manager
     drafts and receipts, and the testing notes about the shared GuiThread for
     GUI smoke.
   - DESIGN.md and the README.
   - Expect roughly 6,000 to 7,000 fewer lines.

Gate to 1.6.0 stable: same as phase 2, plus a week of beta with the
missing-window path tested deliberately (rename the binary in a packaged build).

## Risks

- **Stale drafts (phase 1 step 3)** are the one data-safety item. Today
  `snippet.save` sends only the original trigger, not the value the draft
  started from. Saving an old draft after a tray reload or an outside edit
  therefore overwrites the newer value with no warning. Step 3 should also
  pass that starting value so the bridge can refuse a blind overwrite.
- **macOS work cannot be proven from Windows.** Every macOS claim above is
  unverified until phase 2 runs on a Mac.
- **The macOS bundle identity changes when the binary is added**, so TCC grants
  must be re-granted once, as with any rebuild.
- **Phase 3 is large.** Keep it to deletions and the module split; any behavior
  change belongs in phases 1–2.

## Open decisions for Teô

1. Ship phase 0 as 1.4.1 now, or go straight to phase 1?
2. TS test approach: Vitest (new devDependency) or a CDP smoke on the packaged
   window (recommended).
3. macOS export: Blob fallback first (recommended), or the Tauri dialog
   plugins.
4. Hotkey editing moves into Configurações (recommended), or the tray keeps
   the small Tk dialog as a popup.
