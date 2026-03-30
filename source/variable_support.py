"""Variable substitution support for snippet values.

Syntax: %%variable_name%%

Three kinds, resolved in this priority order:
  - %%clipboard-paste%%  → current clipboard plain text
  - %%trigger%%          → plain text of an existing static snippet (1 level deep)
  - %%field_name%%       → form-fill: collected via a dialog before insertion
"""

import re

from rich_text_support import extract_plain_text

VARIABLE_RE = re.compile(r'%%([^%\s]+)%%')


def find_variable_names(text):
    """Return unique variable names in order of first appearance."""
    seen = set()
    result = []
    for m in VARIABLE_RE.finditer(text):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def classify_variable(name, snippets):
    """Return 'clipboard', 'snippet_ref', or 'form_field'."""
    if name == "clipboard-paste":
        return "clipboard"
    if name in snippets and not callable(snippets[name]):
        return "snippet_ref"
    return "form_field"


def has_form_variables(text, snippets):
    """True if text contains at least one form-field variable."""
    return any(
        classify_variable(name, snippets) == "form_field"
        for name in find_variable_names(text)
    )


def resolve_inline(text, snippets, get_clipboard, _seen=None):
    """
    Resolve %%clipboard-paste%% and %%snippet_ref%% variables in text.
    Form-field variables (%%name%%) are left unchanged.
    Safe to call on the keyboard hot path — never opens a dialog.

    _seen: set of trigger names already in the resolution chain (prevents circular refs).
    """
    names = find_variable_names(text)
    if not names:
        return text

    if _seen is None:
        _seen = set()

    for name in names:
        kind = classify_variable(name, snippets)
        if kind == "clipboard":
            value = get_clipboard() or ""
            text = text.replace(f"%%{name}%%", value)
        elif kind == "snippet_ref" and name not in _seen:
            raw = snippets[name]
            resolved = extract_plain_text(raw)
            # One level deep only: do not recursively resolve variables inside the ref.
            text = text.replace(f"%%{name}%%", resolved)
        # form_field and circular refs: leave unchanged

    return text


def resolve_form_variables(text, form_data):
    """Substitute form-field variables with values collected from the dialog."""
    for name, value in form_data.items():
        text = text.replace(f"%%{name}%%", value)
    return text
