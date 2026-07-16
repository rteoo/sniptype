from snippet_utils import check_dynamic_pattern, get_dynamic_prefixes


def compile_trigger_index(snippets, slow_snippets):
    """Precompute trigger lookup structures while preserving current trigger order."""
    direct_triggers = []
    direct_by_last_char = {}

    for trigger in snippets.keys():
        if trigger.startswith("_"):
            continue

        direct_triggers.append(trigger)
        last_char = trigger[-1]
        direct_by_last_char.setdefault(last_char, []).append(trigger)

    dynamic_prefixes = get_dynamic_prefixes(snippets)

    return {
        "direct_triggers": tuple(direct_triggers),
        "direct_by_last_char": {key: tuple(value) for key, value in direct_by_last_char.items()},
        "dynamic_prefixes": dynamic_prefixes,
        "ordered_prefixes": tuple(dynamic_prefixes.keys()),
        "slow_triggers": frozenset(slow_snippets),
    }


def find_direct_trigger(typed_text, trigger_index):
    """Return the first direct trigger that matches current suffix, preserving source order."""
    # ceiling: first-match-in-source-order; a trigger that is a suffix of another can shadow it.
    # Switch to longest-match-first when validating trigger conflicts (improvement plan phase 3).
    if not typed_text:
        return None

    candidates = trigger_index["direct_by_last_char"].get(typed_text[-1], ())
    for trigger in candidates:
        if typed_text.endswith(trigger):
            return trigger

    return None


def find_dynamic_trigger(snippets, typed_text, trigger_index):
    """Return the full typed trigger and mapped value for dynamic mappings."""
    if not typed_text:
        return None, None

    dynamic_prefixes = trigger_index["dynamic_prefixes"]
    for prefix in trigger_index["ordered_prefixes"]:
        if prefix in typed_text:
            prefix_start = typed_text.rfind(prefix)
            potential_trigger = typed_text[prefix_start:]
            value, _ = check_dynamic_pattern(snippets, potential_trigger, dynamic_prefixes)
            if value is not None:
                return potential_trigger, value

    return None, None
