# SnipType design contract

Adopted: Windows Design System 1.0.0 (2026-09-25). This document records the
SnipType mapping. `source/ui_theme.py` is the implementation authority for the
running Tk interface; this file explains the decisions behind it.

## Intent and workflow

SnipType is a local, keyboard-first text expander. The manager opens on the
library, where people find a trigger, inspect its value, edit it, and save it.
Mappings, dynamic actions, backups, and settings are peer views. The window
shows whether expansion is active and provides the pause command without
requiring a trip to the tray. Search, selection, and editor content stay in
their view while switching tabs. The interface uses quiet neutral layers,
precise type, and a restrained blue accent. No decorative dashboard precedes
the collection.

## Tokens

The Windows palettes map the design system's semantic roles to Tk tokens:

| Role | Light | Dark | Tk owner |
| --- | --- | --- | --- |
| Canvas | `#F3F3F3` | `#202020` | `surface` |
| Working surface | `#FFFFFF` | `#2B2B2B` | `card` |
| Primary text | `#1A1A1A` | `#F5F5F5` | `text` |
| Supporting text | `#5C5C5C` | `#C4C4C4` | `text_muted` |
| Divider | `#D6D6D6` | `#494949` | `border`, `divider` |
| Control boundary | `#767676` | `#A0A0A0` | `control_border` |
| Main action | `#005FB8` | `#60CDFF` | `accent` |
| Main action text | `#FFFFFF` | `#003047` | `text_on_accent` |
| Selection | `#DCEEFF` | `#153F54` | `select_bg` |
| Focus | `#005FB8` | `#75D5FF` | `focus_ring` |
| Warning text | `#7A4D00` | `#FFD479` | `warning` |
| Destructive action | `#A4262C` | `#FFB4B8` | `danger` |

The full light and dark maps, including hover and pressed values, are pinned
by `source/tests/test_ui_theme.py`. The neutral button fill is `#E6E6E6` in
light mode: this SnipType adaptation separates an idle button from both the
white working surface and the gray canvas. Tk uses one `activebackground` for
hover and press, so it takes the design system's pressed value. A stronger
control boundary and a separate focus ring preserve keyboard focus.

Typography uses Segoe UI Variable on Windows, with Tk's system fallback if
unavailable. The 10 pt default is approximately 13 px at 100% scaling; Tk's
integer point sizes cannot represent the design system's 14 px body exactly.
Monospaced trigger identifiers use Consolas. Spacing follows the 4/8/12/16/24
pixel rhythm; the manager has a 44 px row height. Text, dialogs, and window
chrome must scale with Windows DPI rather than fixed bitmap assets.

## Components and layout

- The native window title bar, ttk tabs, tree selections, scrollbars, and
  combobox semantics remain in place. Buttons use semantic theme helpers;
  the main Save action is the accent action in each editor.
- The manager shows product identity, live expansion state, a command row,
  and the five peer views. Ctrl+1 through Ctrl+5 switches views. Ctrl+F
  focuses search in the Textos and Mapeamentos lists; Ctrl+S saves the active
  editor. The tree and editor remain side by side at supported widths.
- The library and mapping views retain a list/editor split. Empty lists say
  what to do next. Backups and settings keep their existing recovery and
  immediate-preference semantics. Destructive edits name their target in a
  confirmation; persistence failures do not claim success.
- Appearance defaults to System, with explicit Light and Dark choices.
  Changing appearance rebuilds the manager after warning about unsaved editor
  text. macOS System appearance continues to use Aqua's native colors and
  control drawing; this Windows design adoption does not replace them.

## Deliberate limits

The current Tk manager keeps its peer views in a notebook because the mapping
editor needs three columns. Its supported Windows minimum is 1020 × 760;
the design system's small-width overlay layout is not implemented. Revisit
this when the editor supports a list/detail mode. A Windows system theme
change while the manager is open takes effect when the manager is reopened:
rebuilding immediately could discard an unsaved editor draft. Revisit after
draft state is tracked across appearance changes. Compact Tk controls have
not been certified as touch targets; the current product is operated with
keyboard and pointer. These limits must be reported with any release review.

## Accessibility and proof

Normal text and action labels target 4.5:1 contrast; the test suite checks
body, supporting, selected, and button pairs in both opaque palettes. State
must have text as well as color. Focus remains visible on buttons and fields.
Keyboard commands have visible counterparts. Keep labels readable at the
minimum supported window size and with longer PT-BR text. Do not add a
custom title bar, fake Mica, or a second Tk root.

Before shipping UI changes, run the theme and manager tests, the full unit
suite, Ruff, and a real Windows desktop pass at minimum/default size in System,
Light, and Dark. That pass must include keyboard navigation, Narrator, 125%
and 200% scaling, contrast themes, empty and populated libraries, save
failure, and close/reopen. A headless test pass does not satisfy these gates.
