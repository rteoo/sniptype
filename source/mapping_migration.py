"""Read legacy mapping containers as ordinary text groups when lossless."""

from collections import Counter
from itertools import count
from uuid import NAMESPACE_URL, uuid5

from group_policy import effective_trigger
from library_metadata import create_group
from snippet_utils import get_dynamic_prefixes, mapping_types
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


def group_legacy_mappings(snippets, metadata, dynamic_triggers=()):
    """Return the grouped library, or the original pair when nothing moved.

    Full trigger keys preserve inline references and allow the same identifier
    in several types. Convert an entire type together, or leave its original
    data and precedence in place for the compatibility editor.
    """
    if metadata.read_only or not has_legacy_mappings(snippets):
        return snippets, metadata

    grouped = snippets
    types = mapping_types(snippets)
    prefixes = get_dynamic_prefixes(snippets)
    prefix_counts = Counter(prefix for key, value in snippets.items() for prefix in get_dynamic_prefixes({key: value}))
    entries = {}
    for key, info in types.items():
        if isinstance(mapping := snippets.get(key), dict):
            entries[key] = {info["prefix"] + name: name for name in mapping if name != "__prefix__"}

    mapping_counts = Counter(trigger for triggers in entries.values() for trigger in triggers)
    mapping_index = compile_trigger_index({key: snippets[key] for key in prefixes.values()}, ())
    # Some old prefixes win even when a longer mapping matches the same text.
    shadowed = {
        trigger for trigger in mapping_counts
        if (matched := find_dynamic_trigger(snippets, trigger, mapping_index)[0]) is not None and matched != trigger
    }
    direct = set(dynamic_triggers)
    direct.update(effective_trigger(key, metadata) for key in snippets if key and not key.startswith("_"))
    direct_lengths = {len(trigger) for trigger in direct if trigger}
    for key, triggers in entries.items():
        label, prefix = types[key]["label"], types[key]["prefix"]
        if prefixes.get(prefix) != key or prefix_counts[prefix] != 1:
            continue
        mapping = snippets[key]
        if any(
            not name or not trigger or trigger.startswith("_") or any(c.isspace() for c in trigger)
            or mapping[name] is None or trigger in snippets or trigger in direct
            or mapping_counts[trigger] > 1 or trigger in shadowed
            # A direct match used to win even against a longer legacy mapping.
            or any(trigger[-length:] in direct for length in direct_lengths if length < len(trigger))
            for trigger, name in triggers.items()
        ):
            continue
        group_id = _group_id(metadata.get("groups", {}), key, prefix)
        metadata = create_group(metadata, group_id, label=label or key,
                                legacy_mapping={"container": key, "prefix": prefix})
        if grouped is snippets:
            grouped = snippets.copy()
        items = metadata["items"]
        old_items = items["mappings"].pop(key, {})
        for trigger, name in triggers.items():
            grouped[trigger] = mapping[name]
            items["static"][trigger] = {**old_items.get(name, {}), "group_id": group_id}
        del grouped[key]
    return grouped, metadata
