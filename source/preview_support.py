"""Side-effect-free preview resolution for Sniptype snippet values."""

from dataclasses import dataclass

from form_support import compile_form, render_form_values
from rich_text_support import extract_plain_text, is_rich_text_payload, rebuild_rich_text
from snippet_utils import check_dynamic_pattern, get_dynamic_prefixes
from variable_support import VARIABLE_RE, classify_variable


CLIPBOARD_PLACEHOLDER = "‹clipboard›"
DYNAMIC_PLACEHOLDER_TEMPLATE = "‹dynamic:{name}›"


@dataclass(frozen=True)
class PreviewResult:
    """Resolved preview payload plus intentionally unavailable variable names."""

    payload: object
    unavailable: tuple[str, ...] = ()


def resolve_preview(value, snippets, form_fields=None, form_values=None):
    """Resolve a preview without clipboard reads, providers, insertion, or I/O.

    Static and mapping references use the local in-memory library. Clipboard
    and callable dynamic references become explicit placeholders. Form values
    are rendered from supplied values or their configured defaults. Every
    replacement is selected from the original template in one regex pass, so
    replacement text containing ``%%tokens%%`` remains literal.
    """
    text = extract_plain_text(value)
    compiled = compile_form(text, form_fields, snippets)
    rendered_fields = render_form_values(compiled, form_values or {})
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
        if kind == "dynamic_ref":
            unavailable.append(name)
            return DYNAMIC_PLACEHOLDER_TEMPLATE.format(name=name)
        if kind == "snippet_ref":
            return extract_plain_text(snippets[name])
        mapped, _mapping_key = check_dynamic_pattern(snippets, name, prefixes)
        return extract_plain_text(mapped)

    resolved_text = VARIABLE_RE.sub(replace, text)
    payload = rebuild_rich_text(value, resolved_text) if is_rich_text_payload(value) else resolved_text
    return PreviewResult(payload, tuple(dict.fromkeys(unavailable)))


__all__ = [
    "CLIPBOARD_PLACEHOLDER",
    "DYNAMIC_PLACEHOLDER_TEMPLATE",
    "PreviewResult",
    "resolve_preview",
]
