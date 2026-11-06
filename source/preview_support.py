"""Side-effect-free preview resolution for Sniptype snippet values."""

from dataclasses import dataclass
from datetime import datetime

from builtin_tokens import KEYS, render_date, resolve_conditions
from form_support import compile_form, fields_used_in, render_form_values
from rich_text_support import extract_plain_text, is_rich_text_payload, rebuild_rich_text
from snippet_utils import check_dynamic_pattern, get_dynamic_prefixes
from variable_support import VARIABLE_RE, classify_variable


CLIPBOARD_PLACEHOLDER = "‹clipboard›"
CURSOR_PLACEHOLDER = "‹cursor›"
KEY_PLACEHOLDERS = {"enter": "‹Enter›", "tab": "‹Tab›"}
DYNAMIC_PLACEHOLDER_TEMPLATE = "‹dynamic:{name}›"


@dataclass(frozen=True)
class PreviewResult:
    """Resolved preview payload plus intentionally unavailable variable names."""

    payload: object
    unavailable: tuple[str, ...] = ()


def resolve_preview(value, snippets, form_fields=None, form_values=None):
    """Resolve a preview without clipboard reads, providers, insertion, or I/O.

    Static and mapping references use the local in-memory library and
    ``%%_date…%%`` renders the current date. Clipboard and callable dynamic
    references become explicit placeholders, ``%%_cursor%%`` shows where the
    caret will end and ``%%_enter%%``/``%%_tab%%`` show the key they press. Form values are rendered from supplied values or their
    configured defaults. Every
    replacement is selected from the original template in one regex pass, so
    replacement text containing ``%%tokens%%`` remains literal.
    """
    now = datetime.now()
    # The branch that holds now, as an expansion would pick it.
    text = resolve_conditions(extract_plain_text(value), now)
    if form_fields is not None:
        form_fields = fields_used_in(form_fields, text)
    compiled = compile_form(text, form_fields, snippets)
    rendered_fields = render_form_values(compiled, {
        name: typed for name, typed in (form_values or {}).items() if name in compiled.field_names
    })
    prefixes = get_dynamic_prefixes(snippets)
    unavailable = []

    def replace(match):
        name = match.group(1)
        kind = classify_variable(name, snippets, prefixes)
        if kind == "form_field":
            return rendered_fields.get(name, match.group(0))
        if kind == "clipboard":
            unavailable.append(name)
            return CLIPBOARD_PLACEHOLDER
        if kind == "date":
            return render_date(name, now)
        if kind == "cursor":
            return CURSOR_PLACEHOLDER
        if kind == "key":
            return KEY_PLACEHOLDERS[KEYS[name]]
        if kind == "dynamic_ref":
            unavailable.append(name)
            return DYNAMIC_PLACEHOLDER_TEMPLATE.format(name=name)
        if kind == "snippet_ref":
            return resolve_conditions(extract_plain_text(snippets[name]), now)
        mapped, _mapping_key = check_dynamic_pattern(snippets, name, prefixes)
        return resolve_conditions(extract_plain_text(mapped), now)

    resolved_text = VARIABLE_RE.sub(replace, text)
    payload = rebuild_rich_text(value, resolved_text) if is_rich_text_payload(value) else resolved_text
    return PreviewResult(payload, tuple(dict.fromkeys(unavailable)))


__all__ = [
    "CLIPBOARD_PLACEHOLDER",
    "CURSOR_PLACEHOLDER",
    "DYNAMIC_PLACEHOLDER_TEMPLATE",
    "KEY_PLACEHOLDERS",
    "PreviewResult",
    "resolve_preview",
]
