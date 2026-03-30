# Features Plan: Tray Double-Click & Custom Variables

## Overview

Four additions to the existing architecture:

1. **Tray double-click** → opens Gerenciar Snippets window (one-line change)
2. **Snippet reference variables** `%%trigger%%` → inline expansion of another snippet
3. **Clipboard paste variable** `%%clipboard-paste%%` → inserts current clipboard content
4. **Form fill variables** `%%fieldname%%` → shows a dialog to collect user input before insertion

---

## Feature 1 — Tray Double-Click

**File:** `txt_xpander.pyw` (menu setup, ~line 1755)

`pystray` supports `default=True` on a `MenuItem`, which becomes the action triggered by
double-clicking the tray icon on Windows.

```python
# Change this:
pystray.MenuItem("Gerenciar Snippets", self.manage_snippets_gui),

# To this:
pystray.MenuItem("Gerenciar Snippets", self.manage_snippets_gui, default=True),
```

No other changes needed.

---

## Feature 2–4 — Custom Variables (`%%...%%`)

### Syntax

Variables are written as `%%name%%` inside any static snippet value (plain text or rich text).
Three kinds are resolved at expansion time:

| Pattern | Kind | Resolved to |
|---------|------|-------------|
| `%%clipboard-paste%%` | Clipboard | Current clipboard plain text |
| `%%xadds%%` | Snippet ref | Plain text of the named snippet trigger |
| `%%nome%%`, `%%data%%`, `%%any_name%%` | Form field | User-supplied value from a dialog |

Priority at resolution: clipboard → snippet ref → form field.
Rich text snippets: only the `text` field is searched/substituted; spans are preserved as-is.

---

### New Module: `variable_support.py`

```
source/variable_support.py
```

#### Public API

```python
VARIABLE_RE = re.compile(r'%%([^%\s]+)%%')

def find_variable_names(text: str) -> list[str]:
    """Return unique variable names in order of first appearance."""

def classify_variable(name: str, snippets: dict) -> Literal["clipboard", "snippet_ref", "form_field"]:
    """Classify one variable name given the current snippets dict."""

def has_form_variables(text: str, snippets: dict) -> bool:
    """True if text contains at least one form-field variable."""

def resolve_inline(text: str, snippets: dict, get_clipboard: Callable[[], str | None]) -> str:
    """
    Resolve clipboard and snippet-ref variables only.
    Form-field variables are left unchanged (%%name%%).
    Safe to call on the keyboard hot path.
    """

def resolve_form_variables(text: str, form_data: dict[str, str]) -> str:
    """Substitute form-field variables with collected values."""
```

#### `classify_variable` logic

```python
def classify_variable(name, snippets):
    if name == "clipboard-paste":
        return "clipboard"
    if name in snippets and not callable(snippets[name]):
        return "snippet_ref"
    return "form_field"
```

Callable snippets (dynamic/slow) are **not** resolved as snippet refs — too complex.

#### Snippet ref resolution

- Extract `extract_plain_text(value)` from the referenced snippet (handles both plain str and
  rich text dict).
- Guard against circular references: pass a `_seen: set[str]` parameter, skip if the trigger
  is already in the set.
- Depth limit: 1 level. Variables inside the resolved snippet are **not** recursively resolved
  (prevents chains that are hard to debug).

#### Example

```python
snippets = {
    "xadds": "Rua Pais Leme, 215",
    "xaddc": "%%xadds%%, São Paulo - SP",
}

# resolve_inline("%%xadds%%, São Paulo - SP", snippets, ...)
# → "Rua Pais Leme, 215, São Paulo - SP"
```

---

### Changes to `txt_xpander.pyw`

#### A. Import

```python
from variable_support import has_form_variables, resolve_inline, resolve_form_variables
```

#### B. `on_press()` — dynamic slow-path detection

After finding a direct trigger and before the slow/fast branch, check if the static snippet
value has form variables and route it through the slow path:

```python
trigger = find_direct_trigger(self.typed_text, self.trigger_index)
if trigger:
    needs_slow = trigger in self.slow_snippets

    if not needs_slow:
        raw_value = self.snippets.get(trigger)
        if not callable(raw_value):
            plain = extract_plain_text(raw_value)
            if has_form_variables(plain, self.snippets):
                needs_slow = True

    if needs_slow:
        # existing backspace + task_runner.start block
        ...
    else:
        self.expand_snippet(trigger)
```

#### C. `expand_snippet()` — resolve inline variables

After retrieving the snippet value and before calling `text_inserter.insert_text()`:

```python
# Resolve clipboard + snippet-ref variables (no dialog needed)
if isinstance(snippet, str):
    snippet = resolve_inline(snippet, self.snippets, WindowsClipboard.get_text)
elif isinstance(snippet, dict) and snippet.get("__kind__") == "rich_text":
    resolved_text = resolve_inline(snippet["text"], self.snippets, WindowsClipboard.get_text)
    snippet = {**snippet, "text": resolved_text}
    # Note: spans remain valid as long as resolved text has same length;
    # if lengths differ, rebuild HTML/RTF from resolved text + original spans
    # (see section D below for the rebuild helper)
```

#### D. `run_slow_snippet()` — form dialog + full resolution

Extend to handle non-callable snippets with form variables:

```python
def run_slow_snippet(self, trigger: str):
    func = self.snippets.get(trigger)

    if callable(func):
        # existing flow unchanged
        result = func()
        ...
    else:
        # Static snippet with form variables
        raw = func
        plain = extract_plain_text(raw)

        # 1. Resolve inline vars first
        plain = resolve_inline(plain, self.snippets, WindowsClipboard.get_text)

        # 2. Collect remaining form fields
        form_names = [n for n in find_variable_names(plain)
                      if classify_variable(n, self.snippets) == "form_field"]

        form_data = {}
        if form_names:
            form_data = self._show_form_dialog(form_names)
            if form_data is None:
                return  # user cancelled — nothing is inserted

        result = resolve_form_variables(plain, form_data)

        if isinstance(raw, dict) and raw.get("__kind__") == "rich_text":
            result = rebuild_rich_text(raw, result)  # see section E

    self.text_inserter.insert_text(result)
```

#### E. `_show_form_dialog()` — Tkinter modal (new method)

```python
def _show_form_dialog(self, field_names: list[str]) -> dict[str, str] | None:
    """
    Show a modal Tk dialog asking the user to fill in each form field.
    Returns {field_name: value} or None if cancelled.
    Called from a background thread, so creates its own Tk root.
    """
```

Dialog design:
- Window title: "Preencher campos"
- For each field name, display a label and a single-line Entry widget
  - Label text: field name with underscores replaced by spaces, title-cased
    (`nome_text` → "Nome text", `data` → "Data")
- OK button (or Enter key) → collect values and return dict
- Cancel button (or Escape key) → return None
- Minimum width 350px; fields stacked vertically with padding
- Window is raised to front and given focus on open

#### F. Rich text rebuild helper (new function in `rich_text_support.py`)

When variables are resolved inside a rich text snippet, the plain `text` field changes length,
invalidating the stored `spans`, `html`, and `rtf`. Rebuild them:

```python
def rebuild_rich_text(original: dict, new_text: str) -> dict:
    """
    Return a new rich-text dict with updated text, preserving spans that still
    fit within the new length. Spans beyond new_text length are clipped/dropped.
    HTML and RTF are regenerated.
    """
```

Simple strategy: clip each span's `end` to `min(span["end"], len(new_text))`, drop spans
where `start >= len(new_text)`. Then regenerate `html` and `rtf` with `build_html_fragment`
and `build_rtf_document`.

---

### Changes to the Formatting Toolbar (`_create_formatting_toolbar`)

Add three new buttons after the existing six formatting buttons, separated by a visual divider.

#### New button group: "Variáveis"

```
[ B | I | U | S | <> | ⌫ ]  |  [ {S} | {📋} | {✏} ]
                              ↑ separator
```

| Button | Label | Action | Inserts |
|--------|-------|--------|---------|
| Snippet ref | `{S}` | Opens picker dialog | `%%trigger%%` |
| Clipboard | `{cb}` | Direct insert | `%%clipboard-paste%%` |
| Form field | `{?}` | Prompts for field name | `%%fieldname%%` |

#### Button implementations

**`{S}` — Snippet reference picker:**

```python
def insert_snippet_ref():
    # Collect all non-underscore, non-callable triggers
    choices = [k for k, v in self.snippets.items()
               if not k.startswith("_") and not callable(v)]
    # Show a simple Listbox dialog with a search Entry
    selected = _pick_from_list(win, "Inserir referência de snippet", choices)
    if selected:
        _insert_variable_text(text_widget, selected)
```

`_insert_variable_text(widget, name)` inserts `%%name%%` at the current cursor position
(or replaces the current selection).

**`{cb}` — Clipboard paste:**

```python
def insert_clipboard_var():
    _insert_variable_text(text_widget, "clipboard-paste")
```

**`{?}` — Form field:**

```python
def insert_form_field():
    name = simpledialog.askstring("Campo de formulário", "Nome do campo:",
                                  parent=win)
    if name and name.strip():
        _insert_variable_text(text_widget, name.strip().replace(" ", "_"))
```

#### `_insert_variable_text` helper (inline in toolbar builder)

```python
def _insert_variable_text(widget, name):
    token = f"%%{name}%%"
    try:
        sel_start = widget.index(tk.SEL_FIRST)
        sel_end = widget.index(tk.SEL_LAST)
        widget.delete(sel_start, sel_end)
        widget.insert(sel_start, token)
    except tk.TclError:
        widget.insert(tk.INSERT, token)
    widget.focus_set()
```

---

### Changes to `snippet_utils.py`

No structural changes needed. `extract_plain_text` already handles both str and rich text dict.
Import it in `variable_support.py`.

---

### Changes to `trigger_index.py`

No changes needed. Variable resolution happens at expansion time, after index lookup.

---

### New test file: `tests/test_variable_support.py`

Cover:
- `find_variable_names`: empty string, no vars, one var, duplicates, order preservation
- `classify_variable`: clipboard, snippet ref, callable snippet (→ form field), unknown
- `resolve_inline`: plain text substitution, snippet ref, clipboard, circular ref guard
- `has_form_variables`: true/false cases
- `resolve_form_variables`: single field, multiple fields, missing key (leave `%%name%%` unchanged)

---

## File Change Summary

| File | Change |
|------|--------|
| `txt_xpander.pyw` | `MenuItem default=True`; variable resolution in `on_press`, `expand_snippet`, `run_slow_snippet`; new `_show_form_dialog`; 3 toolbar buttons |
| `rich_text_support.py` | New `rebuild_rich_text(original, new_text)` helper |
| `source/variable_support.py` | **New file** — all variable parsing and resolution logic |
| `tests/test_variable_support.py` | **New file** — unit tests |

---

## Edge Cases & Decisions

- **Callable snippet refs** (`xcot`, `xwapp`, etc.) are treated as form fields, not snippet refs.
  Rationale: they require async operations and may show their own dialogs.
- **Rich text snippet refs**: the referenced snippet's plain text is used; formatting is not carried over into the referencing snippet.
- **Circular references**: `%%xaddc%%` inside `xaddc` — the `_seen` guard substitutes an empty string and logs a warning.
- **Cancelled form dialog**: nothing is inserted. The trigger text has already been deleted by backspace, so the user simply loses the typed trigger — same behaviour as a cancelled `xwapp`.
- **`%%clipboard-paste%%` when clipboard is empty**: substitutes an empty string.
- **Variable inside rich text**: only `text` field is processed; spans that now point past the end of the new text are clipped.
- **Variable names**: only alphanumeric + underscore + hyphen (enforced by `VARIABLE_RE`). Spaces → `%%field_name%%`.
