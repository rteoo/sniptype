"""Pure rows, filters, and navigation descriptors for the snippet manager.

The manager UI owns widgets and selection state.  This module owns only the
local projection of runtime data: stable references, effective triggers, and
the small amount of metadata needed to filter or navigate without touching
Tk, disk, providers, or the clipboard.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from dynamic_registry import effective_trigger as registry_effective_trigger
from dynamic_registry import is_enabled as registry_entry_enabled
from group_policy import effective_trigger as static_effective_trigger
from group_policy import get_group, get_static_item_metadata, static_item_enabled
from snippet_utils import get_dynamic_prefixes
from workflow_support import SnippetRef


FILTER_ALL = "all"
FILTER_FAVORITES = "favorites"
FILTER_RECENT = "recent"
UNGROUPED_FILTER = "ungrouped"


@dataclass(frozen=True)
class ManagerRow:
    """Immutable manager projection for one static, mapping, or dynamic item."""

    ref: SnippetRef
    stored_trigger: str
    effective_trigger: str
    group_id: str | None = None
    group_label: str = "Ungrouped"
    favorite: bool = False
    enabled: bool = True

    @property
    def kind(self):
        return self.ref.kind

    @property
    def source_kind(self):
        return self.ref.kind

    @property
    def stored_key(self):
        return self.stored_trigger

    @property
    def key(self):
        return self.ref.key

    @property
    def container(self):
        return self.ref.container


@dataclass(frozen=True)
class NavigationTarget:
    """GUI-free descriptor for selecting one manager tab and row."""

    ref: SnippetRef
    tab: str
    row_id: str
    stored_trigger: str
    effective_trigger: str

    @property
    def kind(self):
        return self.ref.kind

    @property
    def key(self):
        return self.ref.key

    @property
    def container(self):
        return self.ref.container


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _favorite(value):
    return isinstance(value, Mapping) and value.get("favorite") is True


def _mapping_item_metadata(metadata, container, item):
    items = _as_mapping(_as_mapping(metadata).get("items"))
    mappings = _as_mapping(items.get("mappings"))
    entries = _as_mapping(mappings.get(container))
    value = entries.get(item)
    return dict(value) if isinstance(value, Mapping) else {}


def _append_static_rows(rows, snippets, metadata):
    for stored_key, value in snippets.items():
        # Underscore-prefixed entries are mapping containers.  The reserved
        # metadata entry is excluded explicitly because callers may pass a raw
        # library document instead of the already-split runtime map.
        if (
            not isinstance(stored_key, str)
            or not stored_key
            or stored_key.startswith("_")
            or stored_key == "__sniptype__"
            or callable(value)
        ):
            continue
        item = get_static_item_metadata(metadata, stored_key)
        group = get_group(metadata, item.get("group_id"))
        rows.append(
            ManagerRow(
                SnippetRef("static", stored_key),
                stored_key,
                static_effective_trigger(stored_key, metadata, item),
                group.group_id,
                group.label,
                _favorite(item),
                static_item_enabled(metadata, stored_key),
            )
        )


def _append_mapping_rows(rows, snippets, metadata):
    for prefix, container in get_dynamic_prefixes(snippets).items():
        mapping = snippets.get(container)
        if not isinstance(mapping, Mapping):
            continue
        for item in mapping:
            if not isinstance(item, str) or not item or item == "__prefix__":
                continue
            item_metadata = _mapping_item_metadata(metadata, container, item)
            rows.append(
                ManagerRow(
                    SnippetRef("mapping", item, container),
                    item,
                    prefix + item,
                    None,
                    "Ungrouped",
                    _favorite(item_metadata),
                    True,
                )
            )


def _append_dynamic_rows(rows, snippets, dynamic_registry):
    registry = _as_mapping(dynamic_registry)
    registry_effective = set()
    registry_keys = set()
    for stable_key, entry in registry.items():
        if not isinstance(stable_key, str) or not stable_key or not isinstance(entry, Mapping):
            continue
        trigger = registry_effective_trigger(stable_key, entry)
        if not isinstance(trigger, str) or not trigger:
            continue
        registry_keys.add(stable_key)
        registry_effective.add(trigger)
        rows.append(
            ManagerRow(
                SnippetRef("dynamic", stable_key),
                stable_key,
                trigger,
                None,
                "Ungrouped",
                False,
                registry_entry_enabled(entry),
            )
        )

    # A runtime callable not represented in the registry is still navigable;
    # this keeps custom/test-provided dynamic snippets visible without making
    # the registry a required dependency of the pure projection.
    for trigger, value in snippets.items():
        if not isinstance(trigger, str) or not trigger or not callable(value):
            continue
        if trigger in registry_effective or trigger in registry_keys:
            continue
        rows.append(
            ManagerRow(
                SnippetRef("dynamic", trigger),
                trigger,
                trigger,
                None,
                "Ungrouped",
                False,
                True,
            )
        )


def build_manager_rows(snippets, metadata=None, dynamic_registry=None):
    """Build ordered immutable rows from local runtime/library projections.

    Ordering is static snippets, mapping items, then registry dynamics.  Static
    group policy applies only to direct static rows.  Mapping favorite flags
    are read from their nested metadata, while registry dynamics are never
    favorites in schema version 1.
    """
    runtime = _as_mapping(snippets)
    rows = []
    _append_static_rows(rows, runtime, metadata)
    _append_mapping_rows(rows, runtime, metadata)
    _append_dynamic_rows(rows, runtime, dynamic_registry)
    return tuple(rows)


def filter_manager_rows(rows, filter_name=FILTER_ALL, *, workflow_state=None, group_id=None):
    """Apply a virtual manager filter while preserving row or history order."""
    rows = tuple(rows or ())
    if group_id is not None and filter_name in (None, FILTER_ALL):
        filter_name = "group"
    if filter_name in (None, FILTER_ALL):
        return rows
    if filter_name in (FILTER_FAVORITES, "favorite"):
        return tuple(row for row in rows if row.favorite)
    if filter_name == FILTER_RECENT:
        if workflow_state is None:
            return ()
        by_ref = {row.ref: row for row in rows}
        return tuple(
            by_ref[item]
            for item in workflow_state.recent_items()
            if item in by_ref
        )

    if filter_name == UNGROUPED_FILTER:
        selected_group = None
    elif filter_name == "group":
        selected_group = group_id
    elif isinstance(filter_name, tuple) and len(filter_name) == 2 and filter_name[0] == "group":
        selected_group = filter_name[1]
    elif isinstance(filter_name, str) and filter_name.startswith("group:"):
        selected_group = filter_name[6:]
    elif group_id is not None:
        selected_group = group_id
    else:
        # A group id is a useful direct selector for callers that already have
        # a group sidebar value and do not need a separate filter token.
        selected_group = filter_name
    return tuple(row for row in rows if row.group_id == selected_group)


def navigation_target(row):
    """Return a stable tab/row descriptor for a manager row."""
    if not isinstance(row, ManagerRow):
        raise TypeError("navigation_target expects a ManagerRow")
    tab = row.kind
    row_id = row.stored_trigger
    if row.kind == "mapping":
        row_id = f"{row.container}:{row.stored_trigger}"
    return NavigationTarget(
        row.ref,
        tab,
        row_id,
        row.stored_trigger,
        row.effective_trigger,
    )


def find_manager_target(rows, target):
    """Find a navigation descriptor by reference, row, or unique trigger."""
    rows = tuple(rows or ())
    if isinstance(target, ManagerRow):
        return navigation_target(target)
    if isinstance(target, NavigationTarget):
        target = target.ref
    if isinstance(target, SnippetRef):
        for row in rows:
            if row.ref == target:
                return navigation_target(row)
        return None
    if isinstance(target, str):
        matches = [row for row in rows if row.effective_trigger == target]
        if not matches:
            matches = [row for row in rows if row.stored_trigger == target]
        if len(matches) == 1:
            return navigation_target(matches[0])
    return None


# Descriptive aliases keep call sites readable without duplicating behavior.
manager_rows_for_filter = filter_manager_rows
build_navigation_target = navigation_target
lookup_manager_target = find_manager_target


__all__ = [
    "FILTER_ALL",
    "FILTER_FAVORITES",
    "FILTER_RECENT",
    "ManagerRow",
    "NavigationTarget",
    "UNGROUPED_FILTER",
    "build_manager_rows",
    "build_navigation_target",
    "filter_manager_rows",
    "find_manager_target",
    "lookup_manager_target",
    "manager_rows_for_filter",
    "navigation_target",
]
