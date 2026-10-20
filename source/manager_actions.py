"""Pure, copy-on-write transactions for snippet-manager operations.

The manager edits the persisted static library and its separate metadata block.
This module deliberately has no disk, Tk, or runtime concerns: callers can
apply an :class:`ActionResult` only after their own save transaction succeeds.
"""

from collections.abc import Mapping
import copy
from dataclasses import dataclass

from dynamic_registry import composed_mapping_triggers
from group_policy import effective_trigger, static_item_enabled
from rich_text_support import extract_plain_text
from library_metadata import (
    LibraryMetadata,
    MetadataReadOnlyError,
    assign_static_item as metadata_assign_static_item,
    create_group as metadata_create_group,
    delete_group as metadata_delete_group,
    duplicate_static_item_metadata,
    rename_static_item_metadata,
    normalize_metadata,
    restore_mapping_item_metadata,
    restore_static_item_metadata,
    remove_form_metadata as metadata_remove_form_metadata,
    set_form_metadata as metadata_set_form_metadata,
    set_mapping_form_metadata as metadata_set_mapping_form_metadata,
    toggle_favorite as metadata_toggle_favorite,
    toggle_mapping_favorite as metadata_toggle_mapping_favorite,
    unassign_static_item as metadata_unassign_static_item,
    update_group as metadata_update_group,
)


class ManagerActionError(ValueError):
    """Base error for a manager transaction that cannot be applied."""


class TriggerCollisionError(ManagerActionError):
    """Raised when an operation would create an exact effective-trigger clash."""

    def __init__(self, trigger, conflicts=()):
        self.trigger = trigger
        self.conflicts = tuple(conflicts)
        detail = ", ".join(str(value) for value in self.conflicts)
        suffix = f" ({detail})" if detail else ""
        super().__init__(f"effective trigger already exists: {trigger}{suffix}")


@dataclass(frozen=True)
class ActionResult:
    """The complete new in-memory state returned by one manager operation."""

    snippets: dict
    metadata: LibraryMetadata
    reachability_warnings: tuple = ()

    @property
    def content(self):
        """Alias for callers that name the snippet map ``content``."""
        return self.snippets

    @property
    def warnings(self):
        """Short alias for UI code presenting reachability confirmations."""
        return self.reachability_warnings

    def __iter__(self):
        yield self.snippets
        yield self.metadata


def _begin(snippets, metadata):
    """Validate compatibility before taking independent working copies.

    Runtime dynamic snippets are kept by reference. They are bound provider
    methods whose owners hold locks and caches: a deep copy either raises
    (``RLock`` cannot be pickled) or re-binds the providers to copies of their
    owners. No transaction edits a callable, and saves never persist one.
    """
    state = normalize_metadata(metadata, None)
    if state.read_only:
        raise MetadataReadOnlyError(
            "library metadata is read-only for compatibility"
        )
    if not isinstance(snippets, Mapping):
        raise TypeError("snippets must be a mapping")
    content = {
        key: value if callable(value) else copy.deepcopy(value)
        for key, value in snippets.items()
        if key != "__sniptype__"
    }
    return content, state


def _dynamic_triggers(snippets, dynamic_triggers):
    if isinstance(dynamic_triggers, str):
        result = {dynamic_triggers}
    elif isinstance(dynamic_triggers, Mapping):
        result = set(dynamic_triggers)
    else:
        result = set(dynamic_triggers or ())
    result.update(
        key for key, value in snippets.items() if isinstance(key, str) and callable(value)
    )
    result.update(composed_mapping_triggers(snippets))
    return {trigger for trigger in result if isinstance(trigger, str)}


def _effective_static_triggers(snippets, metadata):
    result = {}
    for stored_key, value in snippets.items():
        if not isinstance(stored_key, str) or not stored_key or stored_key.startswith("_"):
            continue
        if callable(value) or not static_item_enabled(metadata, stored_key):
            continue
        trigger = effective_trigger(stored_key, metadata)
        result.setdefault(trigger, []).append(stored_key)
    return result


def _check_collisions(snippets, metadata, changed_keys, dynamic_triggers):
    static_triggers = _effective_static_triggers(snippets, metadata)
    dynamic = _dynamic_triggers(snippets, dynamic_triggers)
    for stored_key in changed_keys:
        if stored_key not in snippets or not isinstance(stored_key, str):
            continue
        if stored_key.startswith("_") or callable(snippets[stored_key]):
            continue
        if not static_item_enabled(metadata, stored_key):
            continue
        trigger = effective_trigger(stored_key, metadata)
        conflicts = [
            other
            for other in static_triggers.get(trigger, ())
            if other != stored_key
        ]
        if trigger in dynamic:
            conflicts.extend(sorted(dynamic & {trigger}))
        if conflicts:
            raise TriggerCollisionError(trigger, conflicts)


def _warnings(snippets, metadata, dynamic_triggers):
    triggers = set(_effective_static_triggers(snippets, metadata))
    triggers.update(_dynamic_triggers(snippets, dynamic_triggers))
    ordered = sorted(triggers)
    return tuple(
        (shorter, longer)
        for shorter in ordered
        for longer in ordered
        if shorter != longer
        and len(shorter) < len(longer)
        and longer.endswith(shorter)
    )


def _finish(snippets, metadata, dynamic_triggers=()):
    return ActionResult(
        snippets=snippets,
        metadata=metadata,
        reachability_warnings=_warnings(snippets, metadata, dynamic_triggers),
    )


def duplicate_static(
    snippets,
    metadata,
    source_key,
    destination_key,
    *,
    dynamic_triggers=(),
):
    """Duplicate one static value and its metadata under a new stored key."""
    content, state = _begin(snippets, metadata)
    if source_key not in content:
        raise KeyError(f"unknown static item: {source_key}")
    if destination_key in content:
        raise ValueError(f"static item already exists: {destination_key}")
    if not isinstance(destination_key, str) or not destination_key or destination_key.startswith("_"):
        raise ValueError("destination_key must be a non-empty non-reserved string")
    if callable(content[source_key]):
        raise ValueError(f"cannot duplicate dynamic item: {source_key}")
    content[destination_key] = copy.deepcopy(content[source_key])
    state = duplicate_static_item_metadata(state, source_key, destination_key)
    if destination_key not in state["items"]["static"]:
        state["items"]["static"][destination_key] = {"favorite": False}
    _check_collisions(content, state, (destination_key,), dynamic_triggers)
    return _finish(content, state, dynamic_triggers)


def rename_static(
    snippets,
    metadata,
    source_key,
    destination_key,
    *,
    dynamic_triggers=(),
):
    """Rename a static stored key while preserving all of its metadata."""
    content, state = _begin(snippets, metadata)
    if source_key not in content or callable(content[source_key]):
        raise KeyError(f"unknown static item: {source_key}")
    if destination_key in content:
        raise ValueError(f"static item already exists: {destination_key}")
    if (
        not isinstance(destination_key, str)
        or not destination_key
        or destination_key.startswith("_")
    ):
        raise ValueError("destination_key must be a non-empty non-reserved string")
    content[destination_key] = content.pop(source_key)
    state = rename_static_item_metadata(state, source_key, destination_key)
    _check_collisions(content, state, (destination_key,), dynamic_triggers)
    return _finish(content, state, dynamic_triggers)


def _restorable_item(state, item_metadata):
    """A copy of saved item metadata whose group still exists; an item whose
    group was deleted since comes back ungrouped."""
    item = copy.deepcopy(dict(item_metadata))
    if item.get("group_id") not in dict(state).get("groups", {}):
        item.pop("group_id", None)
    return item


def restore_static(
    snippets,
    metadata,
    key,
    value,
    item_metadata=None,
    *,
    dynamic_triggers=(),
):
    """Undo a static delete: put ``value`` back under ``key`` with the item's
    metadata as :func:`library_metadata.static_item_metadata` saved it.

    Refused when anything has taken the name since, or when the item's
    effective trigger now collides with another.
    """
    content, state = _begin(snippets, metadata)
    if not isinstance(key, str) or not key or key.startswith("_"):
        raise ValueError("key must be a non-empty non-reserved string")
    if key in content:
        raise ValueError(f"static item already exists: {key}")
    content[key] = copy.deepcopy(value)
    if item_metadata:
        state = restore_static_item_metadata(state, key, _restorable_item(state, item_metadata))
    _check_collisions(content, state, (key,), dynamic_triggers)
    return _finish(content, state, dynamic_triggers)


def restore_mapping_item(
    snippets,
    metadata,
    container_key,
    item_key,
    value,
    item_metadata=None,
    *,
    dynamic_triggers=(),
):
    """Undo a mapping-item delete, as :func:`restore_static` does for statics.

    Refused when the mapping type is gone or the identifier is taken again.
    """
    content, state = _begin(snippets, metadata)
    entries = content.get(container_key)
    if not isinstance(entries, Mapping):
        raise KeyError(f"unknown mapping type: {container_key}")
    if not isinstance(item_key, str) or not item_key or item_key == "__prefix__":
        raise ValueError("item_key must be a non-empty identifier other than __prefix__")
    if item_key in entries:
        raise ValueError(f"mapping item already exists: {item_key}")
    entries[item_key] = copy.deepcopy(value)
    if item_metadata:
        state = restore_mapping_item_metadata(
            state, container_key, item_key, _restorable_item(state, item_metadata))
    return _finish(content, state, dynamic_triggers)


def create_group(
    snippets,
    metadata,
    group_id=None,
    definition=None,
    *,
    dynamic_triggers=(),
    **fields,
):
    """Create a group, optionally with a deterministic injected identifier."""
    content, state = _begin(snippets, metadata)
    state = metadata_create_group(state, group_id, definition, **fields)
    return _finish(content, state, dynamic_triggers)


def update_group(
    snippets,
    metadata,
    group_id,
    updates=None,
    *,
    dynamic_triggers=(),
    **changes,
):
    """Update a group and reject newly conflicting effective static triggers."""
    content, state = _begin(snippets, metadata)
    state = metadata_update_group(state, group_id, updates, **changes)
    trigger_changed = any(
        key in (updates or {}) or key in changes for key in ("prefix", "enabled")
    )
    changed = ()
    if trigger_changed:
        assigned = [
            key
            for key, item in state["items"].get("static", {}).items()
            if isinstance(item, Mapping) and item.get("group_id") == str(group_id)
        ]
        changed = tuple(assigned)
    _check_collisions(content, state, changed, dynamic_triggers)
    return _finish(content, state, dynamic_triggers)


def delete_group(snippets, metadata, group_id, *, dynamic_triggers=()):
    """Delete a group and move its static assignments to implicit Ungrouped."""
    content, state = _begin(snippets, metadata)
    assigned = tuple(
        key
        for key, item in state.get("items", {}).get("static", {}).items()
        if isinstance(item, Mapping) and item.get("group_id") == str(group_id)
    )
    state = metadata_delete_group(state, group_id)
    _check_collisions(content, state, assigned, dynamic_triggers)
    return _finish(content, state, dynamic_triggers)


def group_members(metadata, group_id):
    """``(static keys, (container, key) mapping items)`` assigned to a group."""
    items = dict(metadata or {}).get("items", {})
    group_id = str(group_id)
    static = tuple(
        key for key, item in items.get("static", {}).items()
        if isinstance(item, Mapping) and item.get("group_id") == group_id
    )
    mappings = tuple(
        (container, key)
        for container, entries in items.get("mappings", {}).items()
        if isinstance(entries, Mapping)
        for key, item in entries.items()
        if isinstance(item, Mapping) and item.get("group_id") == group_id
    )
    return static, mappings


def restore_group(
    snippets,
    metadata,
    group_id,
    definition,
    *,
    static_items=(),
    mapping_items=(),
    dynamic_triggers=(),
):
    """Undo :func:`delete_group`: recreate the group under its id and give it
    back the members (from :func:`group_members`) that still exist and that
    nothing has regrouped since."""
    content, state = _begin(snippets, metadata)
    state = metadata_create_group(state, group_id, definition)
    group_id = str(group_id)
    statics = state["items"]["static"]
    regrouped = []
    for key in static_items:
        if key in content and not callable(content[key]) and "group_id" not in statics.get(key, {}):
            statics.setdefault(key, {})["group_id"] = group_id
            regrouped.append(key)
    mappings = state["items"]["mappings"]
    for container, key in mapping_items:
        entries = content.get(container)
        if not isinstance(entries, Mapping) or key not in entries:
            continue
        item = mappings.setdefault(container, {}).setdefault(key, {})
        item.setdefault("group_id", group_id)
    _check_collisions(content, state, regrouped, dynamic_triggers)
    return _finish(content, state, dynamic_triggers)


def assign_item(snippets, metadata, item_key, group_id, *, dynamic_triggers=()):
    """Assign an existing static item to a group."""
    content, state = _begin(snippets, metadata)
    if item_key not in content or callable(content[item_key]):
        raise KeyError(f"unknown static item: {item_key}")
    state = metadata_assign_static_item(state, item_key, group_id)
    _check_collisions(content, state, (item_key,), dynamic_triggers)
    return _finish(content, state, dynamic_triggers)


def unassign_item(snippets, metadata, item_key, *, dynamic_triggers=()):
    """Move a static item to implicit Ungrouped."""
    content, state = _begin(snippets, metadata)
    if item_key not in content or callable(content[item_key]):
        raise KeyError(f"unknown static item: {item_key}")
    state = metadata_unassign_static_item(state, item_key)
    _check_collisions(content, state, (item_key,), dynamic_triggers)
    return _finish(content, state, dynamic_triggers)


def set_form(snippets, metadata, item_key, form, *, dynamic_triggers=()):
    """Set validated structured form metadata for an existing static item."""
    content, state = _begin(snippets, metadata)
    if item_key not in content or callable(content[item_key]):
        raise KeyError(f"unknown static item: {item_key}")
    # Keep the persisted JSON shape while reusing the pure field validator.
    # Passing content also rejects names that would lose to runtime variables.
    from form_support import compile_form

    compile_form(extract_plain_text(content[item_key]), form, content)
    state = metadata_set_form_metadata(state, item_key, form)
    return _finish(content, state, dynamic_triggers)


def set_mapping_form(
    snippets,
    metadata,
    container_key,
    item_key,
    form,
    *,
    dynamic_triggers=(),
):
    """Set validated structured form metadata for one mapping item."""
    content, state = _begin(snippets, metadata)
    container = content.get(container_key)
    if (
        not isinstance(container, Mapping)
        or item_key == "__prefix__"
        or item_key not in container
        or callable(container[item_key])
    ):
        raise KeyError(f"unknown mapping item: {container_key}:{item_key}")
    from form_support import compile_form

    compile_form(extract_plain_text(container[item_key]), form, content)
    state = metadata_set_mapping_form_metadata(
        state,
        container_key,
        item_key,
        form,
    )
    return _finish(content, state, dynamic_triggers)


def remove_form(snippets, metadata, item_key, *, dynamic_triggers=()):
    """Remove structured form metadata from an existing static item."""
    content, state = _begin(snippets, metadata)
    if item_key not in content or callable(content[item_key]):
        raise KeyError(f"unknown static item: {item_key}")
    state = metadata_remove_form_metadata(state, item_key)
    return _finish(content, state, dynamic_triggers)


def toggle_favorite(snippets, metadata, item_key, favorite=None, *, dynamic_triggers=()):
    """Toggle or explicitly set favorite metadata for an existing static item."""
    content, state = _begin(snippets, metadata)
    if item_key not in content or callable(content[item_key]):
        raise KeyError(f"unknown static item: {item_key}")
    state = metadata_toggle_favorite(state, item_key, favorite)
    return _finish(content, state, dynamic_triggers)


def toggle_mapping_favorite(
    snippets,
    metadata,
    container_key,
    item_key,
    favorite=None,
    *,
    dynamic_triggers=(),
):
    """Toggle or explicitly set favorite metadata for a mapping item."""
    content, state = _begin(snippets, metadata)
    container = content.get(container_key)
    if (
        not isinstance(container, Mapping)
        or item_key == "__prefix__"
        or item_key not in container
    ):
        raise KeyError(f"unknown mapping item: {container_key}:{item_key}")
    state = metadata_toggle_mapping_favorite(
        state,
        container_key,
        item_key,
        favorite,
    )
    return _finish(content, state, dynamic_triggers)


# Descriptive aliases make the boundary convenient to callers that mirror the
# lower-level library_metadata names.
duplicate_static_item = duplicate_static
assign_static_item = assign_item
unassign_static_item = unassign_item
set_form_metadata = set_form
remove_form_metadata = remove_form


__all__ = [
    "ActionResult",
    "ManagerActionError",
    "MetadataReadOnlyError",
    "TriggerCollisionError",
    "assign_item",
    "assign_static_item",
    "create_group",
    "delete_group",
    "duplicate_static",
    "duplicate_static_item",
    "group_members",
    "rename_static",
    "remove_form",
    "remove_form_metadata",
    "restore_group",
    "restore_mapping_item",
    "restore_static",
    "set_form",
    "set_form_metadata",
    "set_mapping_form",
    "toggle_favorite",
    "toggle_mapping_favorite",
    "unassign_item",
    "unassign_static_item",
    "update_group",
]
