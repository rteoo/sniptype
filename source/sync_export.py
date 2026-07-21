"""Compile the static library plus dynamic registry into the mobile sync bundle.

The bundle is a *compiled* view of the library, not a copy of ``snippets.json``:
mapping containers are expanded into the concrete triggers they generate, snippet
and mapping references are resolved, rich text is flattened to plain text plus
optional HTML, and the dynamic registry ships as metadata only. The phone's job
shrinks to "decode a list and insert a string".

See ``docs/sync-design.md`` for the schema and the reasoning behind every rule
here; the section markers in the comments below point back at it.

``build_bundle`` is a pure function of its arguments. It never invokes a dynamic
provider, never touches the network and never opens a dialog: every dynamic
trigger is mapped to a sentinel callable purely so ``classify_variable`` returns
``dynamic_ref`` for it.
"""

import hashlib
import json
import os
import sys
import time

from dynamic_registry import (
    BCB_METHODS,
    STOCK_METHODS,
    WHATSAPP_MODES,
    effective_trigger,
    is_enabled,
)
from rich_text_support import extract_plain_text, is_rich_text_payload
from snippet_utils import (
    check_dynamic_pattern,
    get_dynamic_prefixes,
    write_json_atomic,
)
from variable_support import classify_variable, find_variable_names

SCHEMA_VERSION = 1
BUNDLE_FILENAME = "txt_xpander_bundle.json"
STATE_FILENAME = "sync_export.state"
GENERATOR_NAME = "txt_xpander"

# The phone holds the whole decoded library in a keyboard extension running under
# a hard memory ceiling, so a very large bundle breaks there first (§5.3).
SIZE_WARN_BYTES = 5 * 1024 * 1024

# Cloud clients (OneDrive in particular) transiently lock files in a synced
# folder; one retry covers that without turning the save path into a spin loop.
PERMISSION_RETRY_DELAY = 0.5

LOCAL_PROVIDERS = ("datetime",)

EXTENSO_PATTERN = "EEEE, dd' de 'MMMM' de 'yyyy"
DEFAULT_DATE_FORMAT = "%d/%m/%Y"
RENDER_LOCALE = "pt-BR"

# C strftime -> Unicode TR35, converted desktop-side so the phone needs no parser.
STRFTIME_TO_TR35 = {
    "Y": "yyyy",
    "y": "yy",
    "m": "MM",
    "d": "dd",
    "H": "HH",
    "I": "hh",
    "M": "mm",
    "S": "ss",
    "j": "DDD",
    "A": "EEEE",
    "a": "EEE",
    "B": "MMMM",
    "b": "MMM",
    "p": "a",
}


def _sentinel():
    """Stand-in for a dynamic provider callable; never invoked."""
    raise AssertionError("sync_export must never invoke a dynamic snippet")


def _warn(logger, message):
    if logger:
        logger.warning(message)


def _is_exportable_value(value):
    """True for values the bundle can carry as text."""
    return isinstance(value, str) or is_rich_text_payload(value)


# =====================================================================
# EXPORT ACCEPT SET (§1.8)
# =====================================================================

def _provider_binds(entry):
    """Mirror ``build_dynamic_snippets``: would this entry bind a callable?

    Returns (ok, reason). ``reason`` is None when ok.
    """
    provider = entry.get("provider")
    if provider not in ("datetime", "bcb", "stock", "whatsapp"):
        return False, f"provider desconhecido '{provider}'"
    if provider == "bcb" and entry.get("method") not in BCB_METHODS:
        return False, f"método inválido '{entry.get('method')}' (provider bcb)"
    if provider == "stock" and entry.get("method") not in STOCK_METHODS:
        return False, f"método inválido '{entry.get('method')}' (provider stock)"
    if provider == "whatsapp" and entry.get("mode") not in WHATSAPP_MODES:
        return False, f"mode inválido '{entry.get('mode')}' (provider whatsapp)"
    return True, None


def build_accept_set(registry, logger=None):
    """Return [(key, trigger, entry), ...] for entries the desktop actually binds.

    This is the single predicate behind three decisions — which rows appear in
    ``dynamic[]``, which triggers win the precedence contest in §1.7, and which
    names get a sentinel callable in §1.6's classification map. Three separate
    filters would drift, so there is exactly one.

    The skip order mirrors ``build_dynamic_snippets`` exactly, including the fact
    that the duplicate-trigger check runs against *bound* entries only: an entry
    with an unknown provider does not reserve its trigger.
    """
    accepted = []
    seen = set()

    for key, entry in registry.items():
        if not isinstance(entry, dict) or not is_enabled(entry):
            continue
        trigger = effective_trigger(key, entry)
        if trigger in seen:
            _warn(logger, f"Bundle: trigger dinâmico duplicado '{trigger}' (entrada '{key}'); ignorado.")
            continue
        ok, reason = _provider_binds(entry)
        if not ok:
            _warn(logger, f"Bundle: {reason} em '{key}'; ignorado.")
            continue
        seen.add(trigger)
        accepted.append((key, trigger, entry))

    return accepted


# =====================================================================
# strftime -> TR35 (§1.8)
# =====================================================================

def strftime_to_unicode_pattern(fmt):
    """Convert a C strftime format to a Unicode TR35 pattern, or None on failure.

    Literal runs are quoted wholesale when they contain any ASCII letter, because
    TR35 reserves ``A-Z a-z`` as pattern letters — leave ``às`` bare and its ``s``
    renders as seconds. A literal ``'`` is always doubled, which is its TR35
    escape both inside and outside a quoted run.
    """
    if not isinstance(fmt, str):
        return None

    parts = []
    literal = []
    index = 0

    def flush_literal():
        if not literal:
            return
        run = "".join(literal).replace("'", "''")
        if any(char.isascii() and char.isalpha() for char in "".join(literal)):
            parts.append(f"'{run}'")
        else:
            parts.append(run)
        literal.clear()

    while index < len(fmt):
        char = fmt[index]
        if char != "%":
            literal.append(char)
            index += 1
            continue
        if index + 1 >= len(fmt):
            return None  # trailing lone '%'
        directive = fmt[index + 1]
        if directive == "%":
            literal.append("%")
        else:
            replacement = STRFTIME_TO_TR35.get(directive)
            if replacement is None:
                return None
            flush_literal()
            parts.append(replacement)
        index += 2

    flush_literal()
    return "".join(parts)


def _render_block(key, entry, logger):
    """Return the ``render`` dict for a locally-renderable entry, else None."""
    if entry.get("provider") not in LOCAL_PROVIDERS:
        return None

    if entry.get("method") == "extenso":
        # Wins over any 'format' key, matching _datetime_provider.
        pattern = EXTENSO_PATTERN
    else:
        fmt = entry.get("format", DEFAULT_DATE_FORMAT)
        pattern = strftime_to_unicode_pattern(fmt)
        if pattern is None:
            # Fail loudly: a silently wrong date is worse than a missing one.
            _warn(logger, f"Bundle: formato de data não conversível em '{key}': {fmt!r}; render omitido.")
            return None

    return {"kind": "date_format", "unicode_pattern": pattern, "locale": RENDER_LOCALE}


def build_dynamic_metadata(accept_set, logger=None):
    """Build ``dynamic[]`` from the export accept set, in registry order."""
    rows = []
    for key, trigger, entry in accept_set:
        render = _render_block(key, entry, logger)
        row = {
            "id": key,
            "trigger": trigger,
            "provider": entry.get("provider"),
            "category": entry.get("category", entry.get("provider", "other")),
            "description": entry.get("description", ""),
            # Only enabled entries reach this point; the field is written anyway so
            # the file is self-describing and a v2 needs no schema bump (§1.8).
            "enabled": True,
            "local": render is not None,
        }
        if render is not None:
            row["render"] = render
        rows.append(row)
    return rows


# =====================================================================
# EXPORT-TIME VARIABLE RESOLUTION (§1.6)
# =====================================================================

def _resolve_export_text(raw_text, classification_map, prefixes):
    """Resolve refs one level deep; return (text, input_block_or_None).

    Only ``snippet_ref`` and ``mapping_ref`` are substituted. ``clipboard``,
    ``dynamic_ref`` and ``form_field`` are preserved as tokens and reported in the
    ``input`` block, because baking them would leak the desktop's clipboard, ship
    a stale number that looks live, or need a user who is not here.
    """
    text = raw_text
    clipboard = False
    fields = []
    dynamic_refs = []

    for name in find_variable_names(raw_text):
        kind = classify_variable(name, classification_map, prefixes)
        if kind == "clipboard":
            clipboard = True
        elif kind == "form_field":
            fields.append(name)
        elif kind == "dynamic_ref":
            dynamic_refs.append(name)
        elif kind == "snippet_ref":
            target = classification_map[name]
            if _is_exportable_value(target):
                text = text.replace(f"%%{name}%%", extract_plain_text(target))
            # else: left as a token, and the re-scan below files it as residual.
        elif kind == "mapping_ref":
            value, _ = check_dynamic_pattern(classification_map, name, prefixes)
            if _is_exportable_value(value):
                text = text.replace(f"%%{name}%%", extract_plain_text(value))

    # Step 3: re-scan the resolved text. The runtime routes from the raw value but
    # builds the form dialog from the *resolved* one, so a form token injected by a
    # one-level ref is prompted for on the desktop and must appear in input.fields.
    accounted = set(fields) | set(dynamic_refs)
    if clipboard:
        accounted.add("clipboard-paste")
    residual = []

    for name in find_variable_names(text):
        if name in accounted:
            continue
        kind = classify_variable(name, classification_map, prefixes)
        accounted.add(name)
        if kind == "clipboard":
            clipboard = True
        elif kind == "form_field":
            fields.append(name)
        elif kind == "dynamic_ref":
            dynamic_refs.append(name)
        else:
            # A ref that survived resolution: injected by another ref (resolution is
            # one level deep) or pointing at an unexportable value. Defined by
            # survival, not provenance — anything still in the text that nothing
            # else accounts for forces an input block, so the phone refuses the
            # entry instead of inserting a literal %%token%%.
            residual.append(name)

    if not (clipboard or fields or dynamic_refs or residual):
        return text, None

    return text, {
        "clipboard": clipboard,
        "fields": fields,
        "dynamic_refs": dynamic_refs,
        "residual": residual,
    }


def _build_entry(trigger, value, source, classification_map, prefixes, logger):
    """Build one ``entries[]`` row, or None when the value is not exportable."""
    if is_rich_text_payload(value):
        raw_text = value["text"]
        kind = "rich_text"
        html = value.get("html")
    elif isinstance(value, str):
        raw_text = value
        kind = "text"
        html = None
    else:
        _warn(logger, f"Bundle: valor não exportável em '{trigger}' ({type(value).__name__}); ignorado.")
        return None

    text, input_block = _resolve_export_text(raw_text, classification_map, prefixes)

    entry = {"trigger": trigger, "text": text, "kind": kind, "source": source}
    # Resolving into `text` while copying `html` verbatim would ship a resolved
    # string next to unresolved markup; dropping the HTML costs formatting, not
    # content, and never lies.
    if kind == "rich_text" and html and not find_variable_names(raw_text):
        entry["html"] = html
    if input_block is not None:
        entry["input"] = input_block
    return entry


# =====================================================================
# TRIGGER SET (§1.7)
# =====================================================================

def build_entries(static_snippets, accepted_triggers, logger=None):
    """Compile ``entries[]``: static snippets first, then mapping expansions.

    Precedence is accepted dynamic > static > mapping-composed; the loser of any
    collision is dropped with a warning so the bundle never carries a duplicate
    trigger. Ordering is fully determined so identical data yields an identical
    file.
    """
    prefixes = get_dynamic_prefixes(static_snippets)
    classification_map = {
        **static_snippets,
        # Dynamic last, matching merge_snippets' {**static, **dynamic}. Build it the
        # other way round and a name present in both reclassifies from dynamic_ref
        # to snippet_ref and gets baked.
        **{trigger: _sentinel for trigger in accepted_triggers},
    }

    entries = []
    emitted = set(accepted_triggers)

    for key, value in static_snippets.items():
        if key.startswith("_"):
            continue  # containers and other underscore keys are never direct triggers
        if callable(value):
            continue  # runtime dynamic snippets never become entries
        if key in emitted:
            _warn(logger, f"Bundle: snippet estático '{key}' colide com um trigger dinâmico; ignorado.")
            continue
        entry = _build_entry(key, value, "static", classification_map, prefixes, logger)
        if entry is None:
            continue
        emitted.add(key)
        entries.append(entry)

    # Iterate the prefix map, not the snippet dict: it is keyed by prefix, so when
    # two containers derive the same prefix the last one wins and the earlier
    # container is genuinely unreachable at runtime.
    for prefix, container_key in prefixes.items():
        mapping = static_snippets.get(container_key)
        if not isinstance(mapping, dict):
            continue
        for item_name, value in mapping.items():
            if item_name == "__prefix__":
                continue
            if callable(value):
                continue
            trigger = prefix + item_name
            if trigger in emitted:
                _warn(logger, f"Bundle: trigger de mapeamento '{trigger}' colide com outro snippet; ignorado.")
                continue
            entry = _build_entry(trigger, value, "mapping", classification_map, prefixes, logger)
            if entry is None:
                continue
            entry["group"] = {"container": container_key, "prefix": prefix, "item": item_name}
            emitted.add(trigger)
            entries.append(entry)

    return entries


def build_bundle(static_snippets, registry, app_version=None, now=None, logger=None):
    """Build the versioned bundle. Pure: no I/O, no callables invoked.

    ``now`` and ``app_version`` are injectable so tests can assert exact output.
    """
    accept_set = build_accept_set(registry, logger)
    accepted_triggers = [trigger for _key, trigger, _entry in accept_set]

    timestamp = now if now is not None else time.gmtime()

    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", timestamp),
        "generator": {
            "name": GENERATOR_NAME,
            "version": app_version,
            "platform": sys.platform,
        },
        "entries": build_entries(static_snippets, accepted_triggers, logger),
        "dynamic": build_dynamic_metadata(accept_set, logger),
    }


# =====================================================================
# WRITE DISCIPLINE (§1.11)
# =====================================================================

def bundle_digest(bundle):
    """SHA-256 over the *content* of a bundle.

    ``exported_at`` and ``generator`` are both excluded so the timestamp stays
    honest: an app upgrade must not rewrite every user's bundle with a fresh
    "library last changed" time for a change that is not in the library.
    """
    payload = dict(bundle)
    payload.pop("exported_at", None)
    payload.pop("generator", None)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load_state(state_path):
    try:
        with open(state_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}  # missing or unreadable simply means "export unconditionally"
    return data if isinstance(data, dict) else {}


def _save_state(state_path, dest_path, digest, logger):
    try:
        write_json_atomic(state_path, {"path": dest_path, "sha256": digest})
    except Exception as e:
        # Losing the state file costs one unconditional export, nothing more.
        _warn(logger, f"Falha ao gravar o estado do bundle de sincronização: {e}")


def resolve_export_dir(export_dir, logger=None):
    """Validate ``sync_export_dir`` and return an absolute path, or None.

    Deliberately minimal: ``expanduser`` only, relative paths rejected, and the
    directory is **not created**. A typo'd path under ``makedirs`` semantics would
    silently write the user's full plaintext CPF/CNPJ library somewhere they never
    chose; the directory already existing is their confirmation that they meant it.
    """
    if not export_dir or not isinstance(export_dir, str):
        return None

    path = os.path.expanduser(export_dir)
    if not os.path.isabs(path):
        _warn(logger, f"sync_export_dir precisa ser um caminho absoluto; ignorado: {export_dir}")
        return None
    if not os.path.exists(path):
        _warn(logger, f"sync_export_dir não existe (não será criado); bundle ignorado: {path}")
        return None
    if not os.path.isdir(path):
        _warn(logger, f"sync_export_dir não é um diretório; bundle ignorado: {path}")
        return None
    return path


def _warn_on_shared_directory(export_path, mirror_dir, logger):
    """Advisory only: mirroring the raw file next to the compiled bundle doubles
    the plaintext exposure for no benefit. Never blocks the export."""
    if not mirror_dir or not isinstance(mirror_dir, str):
        return
    try:
        same = os.path.samefile(export_path, os.path.expanduser(mirror_dir))
    except OSError:
        return  # either path missing; §1.11 tolerates that for the export dir
    if same:
        _warn(
            logger,
            "mirror_dir e sync_export_dir apontam para o mesmo diretório: "
            "a biblioteca completa fica exposta duas vezes, em texto puro.",
        )


def _write_bundle(dest_path, bundle, logger):
    """Atomic write with a single PermissionError retry. Returns success."""
    try:
        write_json_atomic(dest_path, bundle)
        return True
    except PermissionError:
        time.sleep(PERMISSION_RETRY_DELAY)
    except Exception as e:
        _warn(logger, f"Falha ao gravar o bundle de sincronização em {dest_path}: {e}")
        return False

    try:
        write_json_atomic(dest_path, bundle)
        return True
    except Exception as e:
        _warn(logger, f"Falha ao gravar o bundle de sincronização em {dest_path}: {e}")
        return False


def export_bundle(
    static_snippets,
    registry,
    export_dir,
    state_path,
    mirror_dir=None,
    app_version=None,
    now=None,
    logger=None,
):
    """Compile and write the bundle. Best-effort: never raises, returns whether
    the file was written (False also means "skipped because unchanged")."""
    dest_dir = resolve_export_dir(export_dir, logger)
    if dest_dir is None:
        return False

    dest_path = os.path.join(dest_dir, BUNDLE_FILENAME)
    _warn_on_shared_directory(dest_dir, mirror_dir, logger)

    bundle = build_bundle(static_snippets, registry, app_version=app_version, now=now, logger=logger)
    digest = bundle_digest(bundle)

    state = _load_state(state_path)
    # All three conditions are load-bearing. Without the existence check a deleted
    # bundle is never rewritten; without the path check an A -> B -> A switch
    # leaves a stale bundle in A.
    if (
        state.get("sha256") == digest
        and state.get("path") == dest_path
        and os.path.exists(dest_path)
    ):
        return False

    size = len(json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8"))
    if size > SIZE_WARN_BYTES:
        _warn(logger, f"Bundle de sincronização grande ({size // 1024} KB); o app iOS pode não suportar.")

    if not _write_bundle(dest_path, bundle, logger):
        return False

    _save_state(state_path, dest_path, digest, logger)
    return True
