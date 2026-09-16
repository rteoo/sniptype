"""Pure helpers for the embedded Sniptype library metadata boundary.

The JSON library remains a mapping of stored snippet keys to values.  The one
reserved key, ``__sniptype__``, carries the optional schema-v1 metadata.  This
module deliberately has no knowledge of Tk, providers, or the runtime merge;
it only separates, normalizes, joins, and combines JSON-shaped values.
"""

from collections.abc import Mapping
import copy
import uuid


METADATA_KEY = "__sniptype__"
METADATA_KIND = "sniptype_metadata"
SCHEMA_VERSION = 1


class MetadataReadOnlyError(ValueError):
    """Raised when a metadata mutation would rewrite an unsupported block."""


class LibraryMetadata(dict):
    """A dict-compatible metadata value with compatibility-state annotations.

    ``raw_block`` is populated for malformed and future-schema blocks.  Such
    blocks are read-only to the current implementation and are emitted without
    interpretation by :func:`build_library_document`.
    """

    def __init__(self, value=None, *, raw_block=None, read_only=False, malformed=False, present=False):
        super().__init__(copy.deepcopy(value or {}))
        self.raw_block = copy.deepcopy(raw_block)
        self.read_only = bool(read_only)
        self.malformed = bool(malformed)
        self.present = bool(present)

    def copy(self):
        return LibraryMetadata(
            self,
            raw_block=self.raw_block,
            read_only=self.read_only,
            malformed=self.malformed,
            present=self.present,
        )


def _state(value, *, present=False):
    """Convert an arbitrary metadata value into a compatibility-aware value."""
    if isinstance(value, LibraryMetadata):
        return value.copy()
    if value is None:
        if present:
            return LibraryMetadata({}, raw_block=None, read_only=True, malformed=True, present=True)
        return LibraryMetadata({}, present=False)
    if value == {}:
        if present:
            return LibraryMetadata({}, raw_block={}, read_only=True, malformed=True, present=True)
        return LibraryMetadata({}, present=False)
    if not isinstance(value, Mapping):
        return LibraryMetadata({}, raw_block=value, read_only=True, malformed=True, present=present)

    block = copy.deepcopy(dict(value))
    # A caller may construct only the metadata payload it wants to edit.  The
    # schema markers are defaults in that case; explicit, wrong markers remain
    # malformed and are preserved below.
    if "kind" not in block and "schema_version" not in block:
        block["kind"] = METADATA_KIND
        block["schema_version"] = SCHEMA_VERSION
    version = block.get("schema_version")
    if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION:
        return LibraryMetadata(block, raw_block=block, read_only=True, present=present)
    if not _valid_schema_one(block):
        return LibraryMetadata({}, raw_block=block, read_only=True, malformed=True, present=present)
    return LibraryMetadata(block, present=present)


def _valid_schema_one(block):
    """Check the structural contract while allowing additive unknown fields."""
    if not isinstance(block, Mapping):
        return False
    if block.get("kind") != METADATA_KIND:
        return False
    version = block.get("schema_version")
    if version != SCHEMA_VERSION or isinstance(version, bool):
        return False
    groups = block.get("groups", {})
    items = block.get("items", {})
    if not isinstance(groups, Mapping) or not isinstance(items, Mapping):
        return False
    if any(not isinstance(group, Mapping) for group in groups.values()):
        return False
    static_entries = items.get("static", {})
    if not isinstance(static_entries, Mapping):
        return False
    if any(not isinstance(item, Mapping) for item in static_entries.values()):
        return False
    mapping_entries = items.get("mappings", {})
    if not isinstance(mapping_entries, Mapping):
        return False
    for container in mapping_entries.values():
        if not isinstance(container, Mapping):
            return False
        if any(not isinstance(item, Mapping) for item in container.values()):
            return False
    return True


def split_library_document(document):
    """Return ``(snippet_content, metadata)`` from a library JSON object.

    A missing reserved entry produces empty metadata.  Malformed and
    future-schema entries remain available through ``metadata.raw_block`` and
    are marked ``read_only``; content is still returned so it can run.
    """
    if not isinstance(document, Mapping):
        raise TypeError("library document must be a JSON object")
    snippets = {key: copy.deepcopy(value) for key, value in document.items() if key != METADATA_KEY}
    if METADATA_KEY not in document:
        return snippets, LibraryMetadata({}, present=False)
    return snippets, _state(document[METADATA_KEY], present=True)


def _available_sets(available_items):
    if available_items is None:
        return {"static": None, "mappings": None}
    if isinstance(available_items, Mapping) and ({"static", "mappings"} & set(available_items)):
        result = {}
        for category in ("static", "mappings"):
            values = available_items.get(category)
            if values is None:
                result[category] = None
            elif category == "mappings" and isinstance(values, Mapping):
                result[category] = {container: set(items) for container, items in values.items()}
            else:
                result[category] = set(values)
        return result
    if isinstance(available_items, Mapping):
        return {"static": set(available_items), "mappings": set()}
    return {"static": set(available_items), "mappings": set()}


def normalize_metadata(metadata, available_items):
    """Return an independent, schema-v1 metadata copy limited to live items.

    Unknown fields are retained.  References to missing groups become
    ungrouped by removing ``group_id``; the implicit Ungrouped group is never
    serialized.  Compatibility-state values are preserved unchanged.
    """
    state = _state(metadata, present=isinstance(metadata, LibraryMetadata) and metadata.present)
    if state.read_only:
        return state
    if not state:
        return LibraryMetadata({}, present=state.present)

    normalized = copy.deepcopy(dict(state))
    normalized.setdefault("kind", METADATA_KIND)
    normalized.setdefault("schema_version", SCHEMA_VERSION)
    groups = normalized.setdefault("groups", {})
    items = normalized.setdefault("items", {})
    normalized["groups"] = {str(group_id): copy.deepcopy(group) for group_id, group in groups.items()}
    available = _available_sets(available_items)

    static_source = items.get("static", {})
    if not isinstance(static_source, Mapping):
        static_source = {}
    static_allowed = available["static"]
    filtered_static = {}
    for item_key, item_metadata in static_source.items():
        if static_allowed is not None and item_key not in static_allowed:
            continue
        item = copy.deepcopy(item_metadata)
        group_id = item.get("group_id")
        if group_id is not None and group_id not in normalized["groups"]:
            item.pop("group_id", None)
        filtered_static[item_key] = item
    items["static"] = filtered_static

    mapping_source = items.get("mappings", {})
    if not isinstance(mapping_source, Mapping):
        mapping_source = {}
    mapping_allowed = available["mappings"]
    filtered_mappings = {}
    for container_key, source in mapping_source.items():
        if not isinstance(source, Mapping):
            continue
        if isinstance(mapping_allowed, Mapping):
            if container_key not in mapping_allowed:
                continue
            item_allowed = mapping_allowed[container_key]
        else:
            item_allowed = mapping_allowed
        filtered = {}
        for item_key, item_metadata in source.items():
            if item_allowed is not None and item_key not in item_allowed:
                continue
            item = copy.deepcopy(item_metadata)
            group_id = item.get("group_id")
            if group_id is not None and group_id not in normalized["groups"]:
                item.pop("group_id", None)
            filtered[item_key] = item
        filtered_mappings[container_key] = filtered
    items["mappings"] = filtered_mappings
    return LibraryMetadata(normalized, present=True)


def build_library_document(snippets, metadata):
    """Join snippet content and metadata into a fresh JSON-ready mapping."""
    if not isinstance(snippets, Mapping):
        raise TypeError("snippets must be a mapping")
    document = {
        key: copy.deepcopy(value)
        for key, value in snippets.items()
        if key != METADATA_KEY
    }
    state = _state(metadata)
    if state.read_only:
        document[METADATA_KEY] = copy.deepcopy(state.raw_block)
    elif state or state.present:
        document[METADATA_KEY] = copy.deepcopy(dict(state))
    return document


def _import_mode(import_result):
    if isinstance(import_result, str):
        return import_result
    if isinstance(import_result, Mapping):
        return import_result.get("mode", "merge")
    return getattr(import_result, "mode", "merge")


def _winner_items(import_result, imported_items):
    """Read optional content-winner hints while accepting small caller shapes."""
    if not isinstance(import_result, Mapping):
        return None
    explicit = import_result.get("imported_items")
    if explicit is None:
        explicit = {
            category: import_result[key]
            for category, key in (("static", "imported_static"), ("mappings", "imported_mappings"))
            if key in import_result
        }
    if not explicit:
        return None
    result = {}
    for category, values in explicit.items():
        if category == "mappings" and isinstance(values, Mapping):
            result[category] = {container: set(keys) for container, keys in values.items()}
        else:
            result[category] = set(values)
    return result


def _new_group_id(groups):
    while True:
        candidate = str(uuid.uuid4())
        if candidate not in groups:
            return candidate


def merge_metadata(existing, imported, import_result):
    """Apply replace/merge metadata rules without mutating either input.

    ``import_result`` may be ``"replace"``/``"merge"`` or a mapping with a
    ``mode`` key and optional ``imported_items`` category-to-key sets.  In a
    merge, imported item metadata wins wherever imported content wins; absent
    winner hints default to every imported metadata item.
    """
    mode = _import_mode(import_result)
    if mode not in ("replace", "merge"):
        raise ValueError("import mode must be 'replace' or 'merge'")
    incoming = _state(imported)
    if mode == "replace":
        return incoming
    if incoming.read_only:
        raise ValueError("cannot merge read-only or future-schema imported metadata")
    current = _state(existing)
    if current.read_only:
        return current
    if not incoming:
        return current
    if not current:
        return incoming

    merged = copy.deepcopy(dict(current))
    merged.update({key: copy.deepcopy(value) for key, value in incoming.items() if key not in ("groups", "items")})
    existing_groups = copy.deepcopy(merged.setdefault("groups", {}))
    imported_groups = incoming.get("groups", {})
    remap = {}
    for group_id, definition in imported_groups.items():
        if group_id not in existing_groups:
            existing_groups[group_id] = copy.deepcopy(definition)
        elif existing_groups[group_id] != definition:
            replacement = _new_group_id(existing_groups)
            existing_groups[replacement] = copy.deepcopy(definition)
            remap[group_id] = replacement
    merged["groups"] = existing_groups

    existing_items = copy.deepcopy(merged.setdefault("items", {}))
    imported_items = incoming.get("items", {})
    winners = _winner_items(import_result, imported_items)
    local = existing_items.setdefault("static", {})
    incoming_category = imported_items.get("static", {})
    allowed = None if winners is None else winners.get("static", set())
    for item_key, item_metadata in incoming_category.items():
        if allowed is not None and item_key not in allowed:
            continue
        item = copy.deepcopy(item_metadata)
        if item.get("group_id") in remap:
            item["group_id"] = remap[item["group_id"]]
        local[item_key] = item
    local_mappings = existing_items.setdefault("mappings", {})
    incoming_mappings = imported_items.get("mappings", {})
    if not isinstance(incoming_mappings, Mapping):
        incoming_mappings = {}
    mapping_winners = None if winners is None else winners.get("mappings", {})
    for container_key, incoming_container in incoming_mappings.items():
        if not isinstance(incoming_container, Mapping):
            continue
        local_container = local_mappings.setdefault(container_key, {})
        allowed = None if mapping_winners is None else mapping_winners.get(container_key, set())
        for item_key, item_metadata in incoming_container.items():
            if allowed is not None and item_key not in allowed:
                continue
            item = copy.deepcopy(item_metadata)
            if item.get("group_id") in remap:
                item["group_id"] = remap[item["group_id"]]
            local_container[item_key] = item
    for category, values in imported_items.items():
        if category not in ("static", "mappings"):
            existing_items[category] = copy.deepcopy(values)
    merged["items"] = existing_items
    return LibraryMetadata(merged, present=True)


def _mutable_metadata(metadata):
    state = _state(metadata)
    if state.read_only:
        raise MetadataReadOnlyError("library metadata is read-only for compatibility")
    if not state:
        return LibraryMetadata(
            {
                "kind": METADATA_KIND,
                "schema_version": SCHEMA_VERSION,
                "groups": {},
                "items": {"static": {}, "mappings": {}},
            },
            present=True,
        )
    value = copy.deepcopy(dict(state))
    value.setdefault("kind", METADATA_KIND)
    value.setdefault("schema_version", SCHEMA_VERSION)
    value.setdefault("groups", {})
    value.setdefault("items", {})
    value["items"].setdefault("static", {})
    value["items"].setdefault("mappings", {})
    return LibraryMetadata(value, present=True)


def _item_container(state, category="static"):
    return state["items"].setdefault(category, {})


def _prune_item(container, item_key):
    if not container.get(item_key):
        container.pop(item_key, None)


def create_group(metadata, group_id=None, definition=None, **fields):
    """Create a group and return a new metadata value.

    ``group_id`` is injectable for deterministic callers; otherwise a UUID4 is
    generated.  Definition fields, including unknown extensions, are retained.
    """
    state = _mutable_metadata(metadata)
    if definition is None:
        definition = {}
    if not isinstance(definition, Mapping):
        raise TypeError("group definition must be a mapping")
    group_id = str(uuid.uuid4()) if group_id is None else str(group_id)
    if not group_id:
        raise ValueError("group_id must not be empty")
    if group_id in state["groups"]:
        raise ValueError(f"group already exists: {group_id}")
    group = {
        "label": "",
        "notes": "",
        "prefix": "",
        "enabled": True,
        "terminator": "inherit",
        "applications": {"mode": "all", "executables": []},
    }
    group.update(copy.deepcopy(dict(definition)))
    group.update(copy.deepcopy(fields))
    state["groups"][group_id] = group
    return state


def update_group(metadata, group_id, updates=None, **changes):
    """Update one group while retaining its unknown fields."""
    state = _mutable_metadata(metadata)
    group_id = str(group_id)
    if group_id not in state["groups"]:
        raise KeyError(f"unknown group: {group_id}")
    if updates is None:
        updates = {}
    if not isinstance(updates, Mapping):
        raise TypeError("group updates must be a mapping")
    state["groups"][group_id].update(copy.deepcopy(dict(updates)))
    state["groups"][group_id].update(copy.deepcopy(changes))
    return state


def delete_group(metadata, group_id):
    """Delete a group and move all of its assignments to implicit Ungrouped."""
    state = _mutable_metadata(metadata)
    group_id = str(group_id)
    if group_id not in state["groups"]:
        raise KeyError(f"unknown group: {group_id}")
    del state["groups"][group_id]
    for item in _item_container(state, "static").values():
        if item.get("group_id") == group_id:
            item.pop("group_id", None)
    for container in _item_container(state, "mappings").values():
        for item in container.values():
            if item.get("group_id") == group_id:
                item.pop("group_id", None)
    for item_key in list(_item_container(state, "static")):
        _prune_item(_item_container(state, "static"), item_key)
    for container in _item_container(state, "mappings").values():
        for item_key in list(container):
            _prune_item(container, item_key)
    return state


def assign_static_item(metadata, item_key, group_id):
    """Assign a static item to an existing group."""
    state = _mutable_metadata(metadata)
    group_id = str(group_id)
    if group_id not in state["groups"]:
        raise KeyError(f"unknown group: {group_id}")
    items = _item_container(state)
    item = items.setdefault(item_key, {})
    item["group_id"] = group_id
    return state


def unassign_static_item(metadata, item_key):
    """Move a static item to implicit Ungrouped."""
    state = _mutable_metadata(metadata)
    items = _item_container(state)
    if item_key in items:
        items[item_key].pop("group_id", None)
        _prune_item(items, item_key)
    return state


def set_form_metadata(metadata, item_key, form):
    """Set structured form metadata for a static item."""
    if not isinstance(form, Mapping):
        raise TypeError("form metadata must be a mapping")
    state = _mutable_metadata(metadata)
    _item_container(state).setdefault(item_key, {})["form"] = copy.deepcopy(dict(form))
    return state


def remove_form_metadata(metadata, item_key):
    """Remove structured form metadata from a static item."""
    state = _mutable_metadata(metadata)
    items = _item_container(state)
    if item_key in items:
        items[item_key].pop("form", None)
        _prune_item(items, item_key)
    return state


def toggle_favorite(metadata, item_key, favorite=None):
    """Toggle or explicitly set a static item's favorite flag."""
    if favorite is not None and not isinstance(favorite, bool):
        raise TypeError("favorite must be a boolean")
    state = _mutable_metadata(metadata)
    item = _item_container(state).setdefault(item_key, {})
    item["favorite"] = (not item.get("favorite", False)) if favorite is None else favorite
    return state


def duplicate_static_item_metadata(metadata, source_key, destination_key):
    """Copy static item metadata under a new key as a non-favorite item."""
    state = _mutable_metadata(metadata)
    items = _item_container(state)
    if destination_key in items:
        raise ValueError(f"static item already exists: {destination_key}")
    if source_key not in items:
        return state
    duplicated = copy.deepcopy(items[source_key])
    duplicated["favorite"] = False
    items[destination_key] = duplicated
    return state


__all__ = [
    "LibraryMetadata",
    "MetadataReadOnlyError",
    "METADATA_KEY",
    "METADATA_KIND",
    "SCHEMA_VERSION",
    "build_library_document",
    "assign_static_item",
    "create_group",
    "delete_group",
    "duplicate_static_item_metadata",
    "merge_metadata",
    "normalize_metadata",
    "remove_form_metadata",
    "set_form_metadata",
    "split_library_document",
    "toggle_favorite",
    "unassign_static_item",
    "update_group",
]
