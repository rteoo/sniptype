"""Pure compilation and rendering for snippet fill-in forms.

The module deliberately has no Tk, clipboard, network, or application imports.
It turns a template and its persisted field definitions into an immutable
``CompiledForm``.  GUI code can use the field values to build controls, then
call ``render_form`` after submission.

``%%name%%`` remains the template syntax.  A missing field definition means a
metadata-free (legacy) form, for which unresolved names are inferred as text
fields.  Metadata-aware forms are strict: every form-field placeholder has
exactly one definition and every definition is used; inline references remain
for the existing resolver.  Rendering uses one regular
expression substitution pass, so a value containing another placeholder is
literal text rather than a second instruction.
"""

from dataclasses import dataclass
from datetime import date
import re

from snippet_utils import get_dynamic_prefixes


VARIABLE_RE = re.compile(r"%%([^%\s]+)%%")
FIELD_TYPES = ("text", "multiline", "choice", "date", "optional")
DEFAULT_DATE_FORMAT = "%d/%m/%Y"
_NAME_RE = re.compile(r"^[^%\s]+$")


class FormValidationError(ValueError):
    """Raised when a form definition or submitted value is invalid."""

    def __init__(self, message, *, errors=()):
        super().__init__(message)
        self.errors = tuple(errors)


@dataclass(frozen=True)
class FormField:
    """Normalized field definition consumed by the future form dialog."""

    name: str
    type: str = "text"
    default: object = ""
    options: tuple = ()
    content: str = ""
    output_format: str = DEFAULT_DATE_FORMAT
    label: str | None = None

@dataclass(frozen=True)
class CompiledForm:
    """Immutable, validated form ready for GUI collection and rendering."""

    template: str
    fields: tuple[FormField, ...]
    legacy: bool = False

    @property
    def field_names(self):
        return tuple(field.name for field in self.fields)


def _variable_names(template):
    seen = set()
    names = []
    for match in VARIABLE_RE.finditer(template):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return tuple(names)


def _variable_kind(name, snippets):
    if name == "clipboard-paste":
        return "clipboard"
    if name in snippets:
        return "reference"
    for prefix, mapping_key in get_dynamic_prefixes(snippets).items():
        if not name.startswith(prefix) or len(name) <= len(prefix):
            continue
        item = name[len(prefix):]
        mapping = snippets.get(mapping_key)
        if isinstance(mapping, dict) and item in mapping and item != "__prefix__":
            return "mapping"
    return "form_field"


def _normalize_field(definition, index):
    if isinstance(definition, FormField):
        normalized_default = definition.default
        if definition.type == "optional" and normalized_default == "":
            normalized_default = False
        definition = {
            "name": definition.name,
            "type": definition.type,
            "default": normalized_default,
            "options": definition.options,
            "content": definition.content,
            "output_format": definition.output_format,
            "label": definition.label,
        }
    if not isinstance(definition, dict):
        raise FormValidationError(
            f"Field {index + 1} must be an object.", errors=(f"fields[{index}]",)
        )

    name = definition.get("name")
    field_type = definition.get("type", "text")
    if not isinstance(name, str) or not name or not _NAME_RE.fullmatch(name):
        raise FormValidationError(
            f"Field {index + 1} has an invalid name.", errors=(f"fields[{index}].name",)
        )
    if field_type not in FIELD_TYPES:
        raise FormValidationError(
            f"Field {name!r} has an unsupported type.", errors=(f"fields[{index}].type",)
        )

    default = definition.get("default", "")
    options = definition.get("options", ())
    content = definition.get("content", "")
    output_format = definition.get("output_format", DEFAULT_DATE_FORMAT)
    label = definition.get("label")

    if field_type == "choice":
        if not isinstance(options, (list, tuple)) or not options:
            raise FormValidationError(f"Choice field {name!r} needs options.")
        if any(not isinstance(option, str) for option in options):
            raise FormValidationError(f"Choice field {name!r} has a non-text option.")
        if len(set(options)) != len(options):
            raise FormValidationError(f"Choice field {name!r} has duplicate options.")
        options = tuple(options)
        if default == "":
            default = options[0]
        if not isinstance(default, str) or default not in options:
            raise FormValidationError(f"Choice field {name!r} has an invalid default.")
    elif field_type in ("text", "multiline"):
        if not isinstance(default, str):
            raise FormValidationError(f"Text field {name!r} has a non-text default.")
    elif field_type == "optional":
        if "default" not in definition:
            default = False
        if not isinstance(content, str):
            raise FormValidationError(f"Optional field {name!r} needs literal content.")
        if not isinstance(default, bool):
            raise FormValidationError(f"Optional field {name!r} needs a boolean default.")
    elif field_type == "date":
        if not isinstance(output_format, str) or not output_format:
            raise FormValidationError(f"Date field {name!r} needs an output format.")
        if not isinstance(default, str):
            raise FormValidationError(f"Date field {name!r} has a non-text default.")
        if default != "today":
            _parse_date(default, name)

    if label is not None and not isinstance(label, str):
        raise FormValidationError(f"Field {name!r} has a non-text label.")
    return FormField(name, field_type, default, tuple(options), content, output_format, label)


def validate_form_fields(fields, snippets=None):
    """Normalize and validate field definitions, returning immutable fields.

    ``snippets`` is the merged runtime lookup map.  Names that already resolve
    as clipboard, static/dynamic references, or dynamic mappings are rejected
    because a form field could never win the existing variable precedence.
    """
    if isinstance(fields, dict):
        fields = fields.get("fields")
    if not isinstance(fields, (list, tuple)):
        raise FormValidationError("Form fields must be a list.")

    normalized = []
    seen = set()
    for index, definition in enumerate(fields):
        field = _normalize_field(definition, index)
        if field.name in seen:
            raise FormValidationError(f"Duplicate form field {field.name!r}.")
        seen.add(field.name)
        if snippets is not None and _variable_kind(field.name, snippets) != "form_field":
            raise FormValidationError(
                f"Form field {field.name!r} collides with an existing variable."
            )
        normalized.append(field)
    return tuple(normalized)


def infer_legacy_fields(template, snippets=None):
    """Infer unresolved placeholders as text fields for metadata-free forms."""
    if not isinstance(template, str):
        raise FormValidationError("Form template must be text.")
    snippets = snippets or {}
    return tuple(
        FormField(name)
        for name in _variable_names(template)
        if _variable_kind(name, snippets) == "form_field"
    )


def compile_form(template, fields=None, snippets=None):
    """Compile a snippet template and validate its metadata definitions."""
    if not isinstance(template, str):
        raise FormValidationError("Form template must be text.")
    names = _variable_names(template)
    if fields is None:
        normalized = infer_legacy_fields(template, snippets)
        return CompiledForm(template, normalized, legacy=True)

    normalized = validate_form_fields(fields, snippets)
    defined = tuple(field.name for field in normalized)
    form_names = tuple(
        name for name in names
        if _variable_kind(name, snippets or {}) == "form_field"
    )
    missing = tuple(name for name in form_names if name not in defined)
    extra = tuple(name for name in defined if name not in form_names)
    if missing or extra:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unused: " + ", ".join(extra))
        raise FormValidationError("Form definitions do not match template (" + "; ".join(details) + ").")
    return CompiledForm(template, normalized, legacy=False)


def _parse_date(value, name):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise FormValidationError(f"Date field {name!r} needs an ISO date (YYYY-MM-DD).") from exc


def _render_value(field, value):
    if value is None:
        value = field.default
    if field.type in ("text", "multiline"):
        if not isinstance(value, str):
            raise FormValidationError(f"Field {field.name!r} needs text input.")
        return value
    if field.type == "choice":
        if not isinstance(value, str) or value not in field.options:
            raise FormValidationError(f"Field {field.name!r} needs one of its configured choices.")
        return value
    if field.type == "optional":
        if not isinstance(value, bool):
            raise FormValidationError(f"Optional field {field.name!r} needs a boolean value.")
        return field.content if value else ""
    if value == "today":
        parsed = date.today()
    else:
        parsed = _parse_date(value, field.name)
    return parsed.strftime(field.output_format)


def render_form(compiled, values):
    """Render a compiled form in one pass using submitted values/defaults."""
    if not isinstance(compiled, CompiledForm):
        raise TypeError("render_form expects a CompiledForm")
    if not isinstance(values, dict):
        raise FormValidationError("Form values must be an object.")
    allowed = set(compiled.field_names)
    extra = set(values) - allowed
    if extra:
        raise FormValidationError("Unknown form values: " + ", ".join(sorted(extra)) + ".")
    rendered = {
        field.name: _render_value(field, values.get(field.name))
        for field in compiled.fields
    }
    return VARIABLE_RE.sub(
        lambda match: rendered.get(match.group(1), match.group(0)),
        compiled.template,
    )


__all__ = [
    "CompiledForm",
    "DEFAULT_DATE_FORMAT",
    "FIELD_TYPES",
    "FormField",
    "FormValidationError",
    "compile_form",
    "infer_legacy_fields",
    "render_form",
    "validate_form_fields",
]
