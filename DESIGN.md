# SnipType design contract

Adoption record: **Teô Personal DS 2.7.1 — Windows native family** (Ink &
Copper), adopted 2026-10-19. It replaces the Windows Design System 1.0.0
adoption of 2026-09-25. `source/ui_theme.py` and `source/ui_widgets.py` are
the implementation authority for the running Tk interface; this file records
the decisions behind them, the deviations and the gates still open. The
design system's `DESIGN.md`, `native/windows/tokens.css`, `patterns.md` and
`quality.md` are the upstream authority.

## Product, workflow and stack

- **Owner:** the repository owner. Personal-project scope, as the design
  system requires.
- **Primary workflow:** SnipType is a local, keyboard-first text expander that
  lives in the tray. The manager opens on the library, where people find a
  trigger, inspect its value, edit it and save it. Mappings, dynamic actions,
  backups and settings are peer views. The window shows whether expansion is
  active and offers the pause command without a trip to the tray. No
  decorative dashboard precedes the collection.
- **Stack:** Python with Tkinter/ttk (Tcl/Tk 8.6 on Windows), Pillow for the
  drawn control faces, pystray for the tray. No WinUI, no web view.
- **Platforms:** Windows 10 and 11 x64 are the supported desktop. macOS
  (Apple Silicon) is a beta that keeps native Aqua controls. Linux runs the
  same Windows-family theme in CI only.

## Defaults

| Decision | Value | Where |
| --- | --- | --- |
| Appearance | **Dark** on Windows and Linux; Light and System are explicit choices in Configurações > Geral. macOS defaults to System (see Deviations). | `ui_theme.default_preference()` |
| Density | **Compact**: 32 px controls and 32 px list rows at 100% scaling. Settings also offers Comfortable (40/44) and Touch (44/48), persisted after the draft guard and applied on rebuild. | `ui_theme.DENSITY_METRICS` |
| Corner radius | 4 px controls, 8 px cards | `ui_widgets._configure` |
| Spacing | 4 / 8 / 12 / 16 / 24 px | `Theme.space_*` |

An install with no saved appearance, or a malformed one, gets the default and
keeps no explicit choice in `settings.json`.

## Tokens

The family's opaque neutrals carry the hierarchy: the canvas and navigation
sit on `surface`, collections on `card`, editing on `field`. Copper marks the
primary action and selection; it never washes a surface. Every value is pinned
token by token in `source/tests/test_ui_theme.py`, so a change needs review.

| DS role | Dark | Light | Tk token |
| --- | --- | --- | --- |
| Window background / navigation (`--native-bg`, `--native-nav`) | `#292929` | `#E9E8E7` | `surface`, `surface_alt` |
| Collection panel (`--native-panel`) | `#232323` | `#F6F5F4` | `card` |
| Content / field (`--native-content`) | `#1C1C1E` | `#FFFFFF` | `field`, `control` |
| Selection (`--native-selection`) | `#484848` | `#E8E6E3` | `select_bg`, `control_hover`, `surface_alt_active` |
| Line (`--native-line`) | `#454545` | `#D8D8D8` | `border`, `divider`, `card_border` |
| Field border (`--native-field-border`) | `#999CA3` | `#7B8088` | `field_border`, `control_stroke`, `stroke_strong` |
| Primary text | `#F2EFE9` | `#202630` | `text`, `select_fg` |
| Muted text (`--native-muted`) | `#BCBCBC` | `#606060` | `text_muted` |
| Primary action fill / hover / pressed | `#E6A05A` / `#EDB47C` / `#CE8845` | `#E6A05A` / `#D99551` / `#BE7836` | `accent`, `accent_hover`, `accent_active` |
| Primary action label | `#15100A` | `#15100A` | `text_on_accent` |
| Primary border (copper mark) | `#E6A05A` | `#A0520A` | `accent_border` |
| Link | `#EDB47C` | `#A0520A` | `link` |
| Focus ring | `#F0C293` | `#263C56` | `focus_ring` |
| Success fg / bg | `#73E0A1` / `#13271D` | `#16643B` / `#E6F6EC` | `success`, `success_bg` |
| Warning fg / bg | `#FFD27A` / `#342A17` | `#7A4A00` / `#FFF1D6` | `warning`, `warning_bg` |
| Danger fg / bg | `#FF8A85` / `#351718` | `#9B2C2C` / `#FCE8E8` | `danger`, `danger_bg` |
| Info fg / bg | `#ADC1DC` / `#202E40` | `#263C56` / `#E8EEF5` | `info`, `info_bg` |

Tk adaptations, each recorded because the design system has no value for it:

- **Pressed neutral** (`control_active`): `#3A3A3A` dark, `#DEDCD8` light.
  Tk needs a pressed face distinct from hover; it sits one step past hover.
- **Danger hover:** a destructive button hovers on `danger_bg`, because the
  dark danger label measures 4.0:1 on the neutral hover fill.
- **Overlays:** subtle and navigation buttons hover and press through a
  translucent overlay (`overlay`: black in light, white in dark), so they work
  on any surface.
- **Scrollbar thumb:** the muted text tone.
- **Light Windows keeps two system colors:** unpainted labels use
  `SystemButtonText` (`text_native`), and text selected *inside* a field uses
  `SystemHighlight`, so the user's own highlight color survives.

## Type roles

Call sites keep naming a role by its historical point size, and the theme
resolves it. On Windows every role is a negative (pixel) Tk size scaled by
`tk scaling`, because Tk point sizes cannot express 14 px:

| Call-site size | Role | Windows face at 100% |
| --- | --- | --- |
| 9 | Caption | Segoe UI Variable Text, 12 px |
| 10 | Body | Segoe UI Variable Text, 14 px |
| 12 | Heading | Segoe UI Variable Text Semibold, 18 px (bold) |
| 14, 16 | Title | Segoe UI Variable Display (Semibold), 28 px |

A size outside that ramp raises instead of guessing. Windows 10 falls back to
the static Segoe UI faces at the same pixel sizes. Monospace is reserved for
literal triggers and paths: Cascadia Mono, then Cascadia Code, then Consolas.
The Mono cut of Cascadia is preferred because ligatures would disguise the
characters of a trigger. macOS and Linux keep their platform point scale,
shifted so the body role matches the platform's default size.

## Controls, focus and selection

- **Faces.** Rounded faces are Pillow-drawn nine-slice images per palette and
  display scale. A neutral button is the `control` fill inside one 1 px
  `field_border` stroke, with no darker bottom edge. The primary (accent)
  button is a copper fill with no border, as the design system's `DESIGN.md`
  states. Fields draw the same stroke and turn their bottom edge into a 2 px
  `accent_border` underline on focus.
- **Copper marks versus fills.** Copper fills appear only on the primary
  button and on checked check boxes and switches. Marks use `accent_border`:
  the 3 × 16 px pill of the current navigation item, the edge of a checked
  control and the focused field's underline. Raw copper is below 3:1 on the
  light surfaces; the deep tone is not.
- **Focus.** Every focusable face reserves a transparent margin of 3 px at
  100% scaling. Focus draws a 2 px `focus_ring` in its outer part, with a 1 px
  gap of the surface between the ring and the face. This applies to every
  button variant, the combo box, the check box and the switch. Focus composes
  with pressed, selected and hover rather than hiding them: the current
  navigation item keeps its selection fill under the ring. The formatting
  toolbar's buttons never take keyboard focus, so Tab moves between fields;
  they reserve no margin. Gaps between adjacent controls are measured face to
  face (`ui_widgets.face_gap`).
- **Selection.** A selected list row and the current navigation item use the
  neutral `select_bg`. The navigation item adds the copper pill and a
  semibold label.

## Persistence model

| Surface | Model | Behavior |
| --- | --- | --- |
| Text and mapping editors | Explicit save (Salvar, Ctrl+S) | Every save takes a rotating backup and writes atomically. A failure is reported, the in-memory library rolls back and the draft stays for a retry. The editor tracks its draft (see Drafts and saving). |
| Settings switches and choices | Immediate preference | Written to `settings.json` at once; a failed write restores the control and says so. |
| Appearance and language | Immediate preference with a rebuild | Applied at once when no editor holds a draft; a draft asks Salvar · Descartar · Cancelar first. System follows a live Windows switch while the manager is shown. |
| Backups | Explicit restore | Restore and import keep the backup and quarantine guarantees in `AGENTS.md`. |
| Deletes | Immediate, reversible for 10 s | Deleting a snippet, a mapping item or a group saves at once and offers Desfazer, which puts the item and its metadata back through the same save path. Deleting a mapping type asks for its name instead. |

## Components and layout

- The native title bar (dark caption requested from DWM), Windows Snap and
  the system menu stay native. There is no custom title bar.
- The manager shows identity, live expansion state, the pause command and
  five peer views in a left sidebar on the family's neutral navigation
  surface. Ctrl+1 to Ctrl+5 switch views, Ctrl+F focuses the list search and
  Ctrl+S saves the active editor.
- The library and mapping views keep a list/editor split. Empty lists say
  what to do next. Destructive work follows the confirmation ladder below,
  and persistence failures never claim success.
- Collections and editors are flat planes separated by a one-pixel divider.
  Each view has one 28 px page title. The page's New command is primary while
  there is no valid draft to save; a valid dirty draft gives that emphasis to
  Save, with stable labels and button geometry. Delete stays at least 24 px
  from Save, measured between control faces.
- The library's inline filters are All, Favorites, Recent, Disabled and With
  problems. Sidebar counts always name the full collection; list counts name
  the visible subset. Empty libraries offer New and Import; empty searches
  offer Clear search. Recent usage remains session-only.
- The shared Treeview draws a 3 × 16 px `accent_border` selection pill in its
  reserved 6 px image column. Focus keeps the neutral `select_bg`; an unfocused
  selection uses `surface_alt` and keeps the pill. Capability cells show A
  (rich text), ƒ (variables), ▤ (form) and ★ (favorite). Disabled groups and
  dynamic collisions have written row states and muted text. Group cells
  appear from 1400 px; cells use measured ellipses and retain their full values
  for navigation and editing. Types, choosers and form-field lists use the same
  Treeview primitive.
- Below 1300 px, mapping types move into a labeled combobox. Formatting status
  moves below its toolbar when measured control and label widths need it;
  macOS always keeps its stacked path. At 100% Windows scaling the 1180 × 760
  healthy library fits at least 16 complete Compact rows.
- Group management is a labeled **Grupos** button with a drop-down chevron
  beside the group filter, never an icon-only menu.
- The supported Windows minimum is 1180 × 760 and the default is 1280 × 800.
  At the minimum, the text editor's actions fit on one row.

## Deviations

| Area | Design system | SnipType | Why |
| --- | --- | --- | --- |
| Toolkit | WinUI 3 controls | Tk/ttk with drawn faces | The existing stack works; migration has no demonstrated benefit. |
| Accessibility API | UI Automation peers | Tk 8.6 provides no UI Automation peers for its widgets, so Narrator support is limited and untested | Tk limitation. |
| Materials | Mica window base | Opaque surfaces | Tk cannot draw Mica; the family's opaque fallback is used. |
| Control templates | Native templates | Nine-slice images, 128 px tiled middle, per-surface styles | Tk has no rounded primitive; see the runtime reference. |
| Focus geometry | Web: 3 px ring, 3 px offset | 2 px ring, 1 px gap | Tk cannot paint outside a widget. Every pixel of margin widens every control, and 2 px still meets the WCAG 2.4.13 area. |
| macOS | Not part of this family | Native Aqua controls, System default, Aqua dynamic colors, 44 px rows; the current navigation item is marked by a full-height 3 px `accent_border` bar beside its native button instead of the pill | Aqua draws its controls in the OS appearance whatever the app picks. |
| Navigation surface | Web shell uses the slate-navy rail | Family neutral navigation (`#292929` / `#E9E8E7`) | The native family's surfaces take precedence over the web shell. |

## Operations extensions (proposed Teô DS 2.8)

Adopted now as a project extension:

- **Tk/ttk profile.** One theme seam (`ui_theme` and `ui_widgets`) owns
  tokens, metrics and faces. Pixel metrics scale with `tk scaling`. Fonts use
  pixel sizes from the family ramp, and controls follow the active density.
  The focus ring sits in a reserved margin on every face, including the combo
  box, check box and switch, and composes with selection. Marks use the
  primary border tone; copper fills only primary faces and checked fills.
  Contrast-theme handling from that profile is not implemented yet.
- **State vocabulary (§12.1), expansion glossary.** The sidebar names one
  canonical state, and the states never collapse into each other:

  | Key | pt-BR | en | Command | Sidebar mark |
  | --- | --- | --- | --- | --- |
  | `ok` | Expansão ativa | Expansion on | Pausar expansão | 8 px `success` dot, muted word |
  | `paused` | Expansão pausada | Expansion paused | Retomar expansão | `warning` pause icon, bold word |
  | `down` | Captura falhou | Capture failed | Reinicie o SnipType, disabled | `danger` alert icon, bold word |

  `source/health_support.py` owns the three states and their words, and the
  sidebar, the InfoBar and the tray all read them from there. The sidebar has
  no tagline: its first line is the state. After a capture failure, resuming
  is refused with the reason, from the window, the tray and the hotkey alike.
  The tray tells the same story (see Tray state).
- **Attention: the InfoBar slot (OPS-02, §12.5, §12.7).** A row band above
  the pages, written once for every page, shows what stays true until it is
  resolved. `health_support.build_health(facts)` is the pure projection
  behind it, most severe first, one recovery action per issue:

  | Issue | Severity | Action |
  | --- | --- | --- |
  | Captura falhou | error | Abrir log |
  | Usando a biblioteca de exemplo (names the quarantined file) | error | Abrir pasta |
  | Não foi possível salvar a biblioteca | error | Abrir log |
  | Expansão pausada | warning | Retomar |
  | Metadados da biblioteca somente leitura | warning | Abrir pasta |
  | Triggers em conflito com ações dinâmicas | warning | Ver ações dinâmicas |
  | Cópia espelho não gravada · Pacote de sincronização não exportado | warning | Tentar agora |
  | Biblioteca restaurada do backup · {when} | info | Ver cópias de segurança, Dispensar |

  A band uses the DS state fill and text, the tone's icon, a written title,
  what it means and its action. Only `info` can be dismissed (Dispensar, for
  the session, as a labeled button); an error or warning stays until the
  fact stops being true. Only the most severe issue gets the band; the rest
  are named in one line under it ("Também aguardando atenção: Expansão
  pausada · Cópia espelho não gravada") and take the band as each is
  resolved. The bar therefore costs a page one row however much is wrong,
  which keeps the Textos editor's toolbar, content box and buttons inside the
  window at its 1180x760 minimum with every kind of trouble open at once. The
  named line stands in for the shared "Ver tudo (N)" list, which a Tk page has
  no height for; the sidebar's Retomar expansão and the Dados card's Tentar
  agora stay reachable while their issue waits. The producer sets the severity; the view never softens or raises it. A
  failed capture is never also reported as a pause. The facts are session
  memory, recorded where they happen (`library_recovery`, `last_save_error`,
  `last_mirror`, `last_sync`, plus the app's live flags), and nothing is
  persisted. Replacing the library (restore, import) ends a recovery; a
  successful save ends a save failure.
- **No silent failures (§12.7).** Every library command ends in a receipt or
  in an error dialog titled with the action, including errors nobody
  anticipated, which are also logged with their traceback. An exception in
  any Tk callback is logged with its traceback and shown as an error
  notification ("Erro inesperado: …") through `report_callback_exception`,
  so a failing button never does nothing silently. A bound control
  (Favorito, Grupo) that fails returns to the saved value. A mirror or sync
  export that fails is recorded and shown in the InfoBar and the Dados card
  instead of only in the log.
- **Dialog kit (§12.8, §12.16 Tk).** Every prompt is a themed, owned, modal
  Toplevel from `ui_widgets`: `confirm(parent, title, body, primary_label,
  danger=False, typed_word=None, extra=None)`, `ask_text(parent, title,
  label, initial, validate, primary_label=...)`, `alert(parent, title, body,
  tone=...)` and `dialog_footer(...)`. The footer is the primary, then any
  extra choice, then Cancelar, right-aligned; Enter runs the focused button
  or the primary (never inside a multi-line field), and Escape and the close
  box cancel. Focus starts on the field, on the primary, or on Cancelar when
  the primary is destructive, and returns to the control that opened the
  prompt. Choices are named by outcome, never Sim/Não/OK. Field errors show
  under the field while the prompt stays open. Prompts take the cached
  theme of the window they belong to, because the ttk theme is shared by
  every window. A source test bans `messagebox` and `simpledialog` from the
  GUI modules and requires an owner window on every kit prompt. Dialog
  bodies sit on the dialog surface with no card inside (form, group,
  shortcuts, preview, form editor).
- **Confirmation ladder (§12.8).** The consequence sets the friction:

  | Action | Friction |
  | --- | --- |
  | Delete a snippet, a mapping item or a group | None. It saves at once, and the receipt offers Desfazer for 10 s |
  | Restore a backup | One confirmation naming the backup's date, age and the counts it changes |
  | Import: merge | One choice in the import dialog, which shows the counts for both modes |
  | Import: replace everything | A second confirmation that stays disabled until SUBSTITUIR is typed |
  | Delete a mapping type and all its items | A confirmation that stays disabled until the type's name is typed |

  Counts read "Novos: N · Sobrescritos: N · Removidos: N", item by item,
  mapping entries included.
- **Receipt format and routing (§12.8, §12.9).** A receipt names the outcome
  with its time, then the object: "Salvo às 14:32 · xola", "Excluído às
  14:02 · xola", then "Restaurado às 14:03 · xola" after Desfazer. Every page
  has one status line at the bottom: the editors' rests on "Ctrl+S para
  salvar" until the first receipt, and the other pages' is empty. A receipt
  stays until the next one; its action (Desfazer) expires after 10 s. A
  restore, an import or a recovery replaces the library, so every status line
  returns to rest and drops its Desfazer: a receipt never names an item of a
  library that is gone. Pausing or resuming expansion is a command too, with a
  timed receipt ("Expansão pausada às 14:32") that is never held back by the
  toast cooldown, so the line and the sidebar always say the same thing.
  Routine success is quiet:

  | Event | Where it goes |
  | --- | --- |
  | A command the person ran in the manager (save, duplicate, rename, group, mapping type, enable, pause or resume, backup, export, import, shortcuts) | The status line of the page they are on. No toast, no dialog |
  | Another status (tray, hotkey) while the manager is mapped and has the focus | The status line |
  | The same while the manager is minimized, closed or not focused | A tray notification |
  | An error | Always a tray notification, and a dialog where the person is waiting on the answer |

  Success dialogs in Cópias de segurança are gone. Every message, whichever
  way it was shown, is kept in the history with its ISO time (`at`) next to
  the clock (`time`), so history written before `at` existed still renders.
- **Notification history.** "Histórico de notificações" lists the newest
  first with a record stamp in the "Quando" column ("Hoje 11:15", "Ontem
  09:40", "17/10 09:40"; an old entry with only a clock shows the clock). An
  error row has the alert icon, the danger text and the word "Erro", so it
  is told apart by shape and word as well as color. "Somente erros" filters
  to them. An empty list, and an empty filter, say so in a label instead of
  a fake row. Headings are left-aligned.
- **Tray state.** The tray shows the sidebar's state: the shipped icon while
  expansion is on, and the same icon with a corner badge while it is paused
  (two bars, `warning`) or the capture failed (an alert mark, `danger`). The
  badge is drawn at runtime with Pillow in `source/tray_support.py`, so no
  asset ships per state; its colors come from `ui_theme.tray_badge_colors`
  and are the dark palette's, with a ring, because the taskbar is not a
  window of either theme. The tooltip adds the state ("SnipType · Expansão
  pausada"). The first menu line is "Expansão ativa" with the native check
  as its only mark, or a disabled "Captura falhou"; menu labels are sentence
  case ("Gerenciar snippets"). The tray redraws when the state changes, not
  on a timer.
- **Navigation counts and freshness.** The navigation counts the library
  ("Textos (5)") and a search or filter never changes it; the list header
  says how many the list shows ("Snippets: 1 de 5"). The Dados card says what
  the last mirror copy and sync export of this session did ("Última
  exportação Ontem 09:10 · OK", "Nenhuma exportação nesta sessão ainda.");
  after a failure it turns into a warning band with Abrir pasta (the
  destination, which is never created) and Tentar agora.
- **Time vocabulary (§12.6).** `source/time_format.py` is the one formatter:
  a 24-hour local clock, record stamps ("Hoje 14:02", "Ontem 09:10", "qua.
  14/10 09:10", "14/10 09:10", "14/10/2025"; en "Today 14:02", "Wed Oct 14
  09:10", "Oct 14, 2025"), ages ("agora", "há 4 min", "há 3 h", "há 3 d",
  "em 4 min"; a week or more is a stamp) and both together for backups
  ("14/10 09:10 · há 3 h"). Weekday and month names are interface strings.
  Form dates are typed and shown as DD/MM/AAAA; ISO is still read, and an
  invalid date names the field's label.
- **Icons used on their own labels (§12.16).** Segoe Fluent Icons, falling
  back to Segoe MDL2 Assets: U+E70D chevron after "Grupos" (fallback: the
  text "Grupos ▾"), and U+E783 error, U+E7BA warning and U+E946 info beside
  an alert's title (fallback: no icon; the title carries the meaning).
- **Drafts and saving (OPS-11).** The Textos and Mapeamentos editors keep
  an `EditorSession` (`source/editor_session.py`): the saved item they
  show and whether the editor holds unsaved changes.
  - The line under the editor's title names the target: "Editando xola",
    "Editando alice em CPF", "Novo snippet", or "Nenhum snippet aberto"
    with "Selecione um snippet na lista ou clique em Novo." A draft adds
    "• Não salvo" there and a "• " in front of the window title.
  - Salvar is enabled only for a dirty, valid draft; the line names what
    is missing ("Informe um valor para o snippet."). Ctrl+S runs the same
    command and says why it does not save. Duplicar, Renomear, Excluir,
    Favorito, Grupo, Formulário and Prévia act on the editor's saved item
    and are disabled when there is none.
  - Salvar writes the name in the trigger or identifier field, which can
    differ from the open item, so the line under the title says what it
    will do: "Salvar cria xnova; xola continua salvo." for a free name,
    "Salvar substitui xbye." for another saved item. Replacing one asks
    first ("Substituir snippet" or "Substituir item", the destructive
    Substituir beside Cancelar, which has the focus); Cancelar keeps the
    draft and writes nothing.
  - Every exit that would drop a draft asks Salvar · Descartar · Cancelar,
    with Salvar as the default: another list row (Cancelar re-selects the
    open one), Novo, Duplicar, Editar último and the other cross-tab
    jumps, a mapping type change, the close box, Restaurar, Importar,
    Atualizar biblioteca and an appearance or language rebuild. Nothing
    asks when nothing is unsaved.
  - When the library changes under the editor (restore, import, Atualizar
    biblioteca, another view), a clean editor follows it. A draft stays,
    and a warning bar says "A biblioteca mudou: xola tem uma versão salva
    mais nova." with Usar a versão nova and Manter rascunho, or "… não
    existe mais." with Descartar rascunho and Manter rascunho. A kept
    draft stays unsaved until it is saved or discarded.
  - Refreshes and saves keep the list's selection on the editor's item,
    its keyboard focus row and its scroll position; a new filter starts
    at the top. When the filter hides an open item that is still in the
    library the editor says "Oculto pelo filtro atual." and offers Mostrar
    na lista; an item the library dropped is reported only by the warning
    bar ("… não existe mais."). Efetivo is computed from the trigger the
    editor holds.
  - The tray's "Recarregar Snippets" is now "Atualizar biblioteca"
    (glossary: Atualizar re-reads data). A manager that opens while the
    library is being read is refreshed once the read ends.
- **Search ranking.** Library search matches the stored trigger, the
  effective trigger shown after `→`, the group label and the plain content.
  Triggers rank before the group label, and the group label before content;
  within each, exact beats prefix beats substring.

## Accessibility and proof

Body text and labels target 4.5:1, and control boundaries, copper marks and
the focus ring target 3:1. The suite checks, in both palettes:

- text and muted text on every surface and on the selection;
- the primary label on the primary fills;
- danger on its own button states;
- each state color on its own tint;
- field border, copper mark and focus ring on the canvas, panel and field.

State is never conveyed by color alone. Keep labels readable at the minimum
window size and with longer PT-BR text. Do not add a custom title bar, fake
Mica or a second Tk root.

Evidence for this adoption: the unit suite and the manager smoke tests, plus
screenshots of the real windows on an isolated data home with synthetic data,
in Dark and Light at 1180 × 760 and 1600 × 1000, at 100% scaling only.

## Unresolved gates

WP8 secondary views use one searchable, categorized Actions collection, local
backup timestamps with age and separate text/list counts, and immediate guarded
appearance, language and density settings. Read-only paths have Copy controls.
Settings sections retain full-size controls in a scrollbar viewport; wheel and
Tab navigation reveal the focused control at the supported minimum. The backup
path uses measured middle ellipsis beside a reserved Copy command, which copies
the complete value. The hotkey dialog measures its minimum from its actual
language, density and scale, reserves its footer first, and returns focus through
the same explicit handoff as DialogKit.
Tk Treeview has row fonts rather than cell fonts: Actions keeps its state and
description readable in the UI font, so its trigger column uses that same font.
The trigger text and stable registry key remain exact; a per-cell mono face is
deferred until the collection primitive supports it without overlay controls.

Recorded per the family's release gates. A headless or harness pass does not
satisfy any of them.

| Gate | Status |
| --- | --- |
| Appearance: live System change while the manager is open | Implemented: checked every 3 s while the manager is shown; a draft holds the switch and says so. Verified in the smoke test and the harness with the registry read mocked, not by switching the real Windows setting. |
| Appearance: Windows contrast themes | Not tested. Drawn faces ignore system colors. |
| Density: Comfortable and Touch | Implemented in WP8; physical desktop layout and higher DPI remain unverified. |
| Display: 125/150/200% DPI and mixed monitors | Not tested on hardware. Window minimums and spacing are still unscaled pixels. |
| Keyboard: visible focus on list rows | Implemented in WP6: focused selection uses neutral `select_bg`; unfocused selection uses `surface_alt`, retaining a 3 × 16 px copper pill in both states. Verified with the actual Tk focus-state prototype and dark/light harness captures. Physical keyboard traversal and contrast themes remain unverified. |
| Keyboard: formatting commands | Implemented in WP7: Ctrl+Shift+X clears formatting; Ctrl+Shift+R/V/F inserts a reference, clipboard value or form field. Existing Ctrl+B/I/U and code/strikethrough shortcuts remain. Physical keyboard and Narrator verification remain open. |
| Accessibility: Narrator roles, values and announcements | Not tested. |
| Work preservation: drafts across appearance changes and refresh | Passed in the smoke tests and the harness (row change, Novo, Editar último, type change, close, restore, rebuild). Open: quitting from the tray does not ask yet (the close box does), and Excluir on an item with a draft deletes it without asking; Desfazer brings back the saved version, not the draft. |
| Keyboard: Ctrl+Z for Desfazer | Failed. Desfazer is a button in the receipt line, reachable with Tab; no shortcut yet. |
| Status: tray badge on real taskbars | Not tested. The badge is drawn at runtime and differs by shape as well as color, but it was checked as a Pillow render at 16 to 32 px on simulated light and dark taskbar colors, not on a real taskbar. |
| Status: Narrator announcements of a state change | Not tested. The InfoBar and the status line are plain Tk labels, which expose nothing to UI Automation. |
| Status: macOS tray redraw | Not tested. The redraw is queued onto the GUI thread there, as the menu refresh is, but no Aqua run has seen it. |
| Dialogs on macOS main-thread mode | Not tested. The kit's grab and focus handoff were exercised on Windows only. |
| Physical desktop pass at minimum and default size, keyboard only, close and reopen | Not tested for this adoption. |
