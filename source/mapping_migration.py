"""Read legacy mapping containers as ordinary text groups when lossless."""

from collections import Counter
from itertools import count
from uuid import NAMESPACE_URL, uuid5

from group_policy import effective_trigger, get_static_item_metadata, normalize_group
from library_metadata import create_group, normalize_metadata
from snippet_utils import check_dynamic_pattern, get_dynamic_prefixes, mapping_types
from trigger_index import compile_trigger_index, find_dynamic_trigger


def has_legacy_mappings(snippets):
    """Whether there is still a mapping container that needs the old editor."""
    return any(isinstance(snippets.get(key), dict) for key in mapping_types(snippets))


def _group_id(groups, container, prefix):
    # A backup and an export of the same legacy type should merge into one
    # group. Reserve a different ID if that ID has since been edited locally.
    for index in count():
        candidate = str(uuid5(NAMESPACE_URL, f"sniptype:mapping:{container}:{prefix}:{index}"))
        if candidate not in groups:
            return candidate


def _reusable_group(groups, container, prefix):
    """Find the migrated group with the same trigger behavior as the legacy type."""
    origin = {"container": container, "prefix": prefix}
    for group_id, group in groups.items():
        if group.get("legacy_mapping") != origin:
            continue
        policy = normalize_group(group_id, group)
        if policy.enabled and not policy.prefix and policy.terminator == "inherit" and policy.applications.mode == "all":
            return group_id
    return None


def _legacy_selector(trigger, snippets, prefixes):
    """Which prefix made the legacy resolver consider this whole trigger."""
    value, _ = check_dynamic_pattern(snippets, trigger, prefixes)
    for prefix, container in prefixes.items():
        if prefix:
            if value is not None and trigger.rfind(prefix) == 0:
                return container
        elif isinstance(mapping := snippets[container], dict):
            if trigger != "__prefix__" and mapping.get(trigger) is not None:
                return container
    return None


def _preserve_legacy_winners(snippets, prefixes, entries, candidates, winners):
    """Keep retained triggers reachable and ahead of newly converted suffixes."""
    owners = {trigger: key for key in candidates for trigger in entries[key]}
    lengths = {len(trigger) for trigger in owners}
    pending = set(entries) - candidates.keys()
    while pending:
        for trigger in entries[pending.pop()].keys() & winners:
            # A prefix can select a trigger whose value belongs to a different
            # container. Removing that selector could hide the retained value.
            needed = {_legacy_selector(trigger, snippets, prefixes)}
            needed.update(owners.get(trigger[-length:]) for length in lengths if length < len(trigger))
            for owner in needed:
                if owner in candidates:
                    del candidates[owner]
                    pending.add(owner)


def group_legacy_mappings(snippets, metadata, dynamic_triggers=(), *, merge_import=None):
    """Return the grouped library, or the original pair when nothing moved.

    Full trigger keys preserve inline references and allow the same identifier
    in several types. Convert an entire type together, or leave its original
    data and precedence in place for the compatibility editor. During a merge,
    an imported legacy type can update members of its own migrated group.
    """
    if getattr(metadata, "read_only", False) or not has_legacy_mappings(snippets):
        return snippets, metadata

    types = mapping_types(snippets)
    prefixes = get_dynamic_prefixes(snippets)
    prefix_counts = Counter(prefix for key, value in snippets.items() for prefix in get_dynamic_prefixes({key: value}))
    entries = {}
    for key, info in types.items():
        if isinstance(mapping := snippets.get(key), dict):
            entries[key] = {info["prefix"] + name: name for name in mapping if name != "__prefix__"}

    mapping_counts = Counter(trigger for triggers in entries.values() for trigger in triggers)
    mapping_index = compile_trigger_index({key: value for key, value in snippets.items() if key.startswith("_")}, ())
    # Legacy prefix order can prefer a shorter match, and repeated prefixes in
    # a trigger can prevent any match because the resolver uses rfind.
    winners = {
        trigger for trigger in mapping_counts
        if find_dynamic_trigger(snippets, trigger, mapping_index)[0] == trigger
    }
    direct = Counter(dynamic_triggers)
    direct.update(effective_trigger(key, metadata) for key in snippets if key and not key.startswith("_"))
    direct_lengths = {len(trigger) for trigger in direct if trigger}
    candidates = {}
    for key, triggers in entries.items():
        prefix = types[key]["prefix"]
        if prefixes.get(prefix) != key or prefix_counts[prefix] != 1:
            continue
        mapping = snippets[key]
        reuse = _reusable_group(metadata.get("groups", {}), key, prefix) if merge_import and key in merge_import else None
        previous = {
            trigger for trigger in triggers
            if reuse is not None and trigger not in merge_import and trigger in snippets
            and get_static_item_metadata(metadata, trigger).get("group_id") == reuse
        }
        if any(
            not name or not trigger or trigger.startswith("_") or any(c.isspace() for c in trigger)
            or mapping[name] is None or (trigger in snippets and trigger not in previous)
            or direct[trigger] > (trigger in previous)
            or mapping_counts[trigger] > 1 or trigger not in winners
            # A direct match used to win even against a longer legacy mapping.
            or any(trigger[-length:] in direct for length in direct_lengths if length < len(trigger))
            for trigger, name in triggers.items()
        ):
            continue
        candidates[key] = reuse

    _preserve_legacy_winners(snippets, prefixes, entries, candidates, winners)
    if not candidates:
        return snippets, metadata

    grouped = snippets.copy()
    # A reusable group can migrate an import without having to create a group.
    # Take a detached copy before moving its mapping item metadata.
    metadata = normalize_metadata(metadata, None)
    for key, reuse in candidates.items():
        mapping = snippets[key]
        label, prefix = types[key]["label"], types[key]["prefix"]
        group_id = reuse
        if group_id is None:
            group_id = _group_id(metadata.get("groups", {}), key, prefix)
            metadata = create_group(metadata, group_id, label=label or key,
                                    legacy_mapping={"container": key, "prefix": prefix})
        items = metadata["items"]
        old_items = items["mappings"].pop(key, {})
        for trigger, name in entries[key].items():
            grouped[trigger] = mapping[name]
            current = items["static"].get(trigger, {}) if trigger in snippets else {}
            items["static"][trigger] = {**current, **old_items.get(name, {}), "group_id": group_id}
        del grouped[key]
    return grouped, metadata
