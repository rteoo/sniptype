from rich_text_support import extract_plain_text
from snippet_utils import check_dynamic_pattern, get_dynamic_prefixes
from variable_support import has_form_variables


def _compute_form_triggers(snippets):
    """Return the set of direct triggers whose value needs a form-fill dialog.

    Computed once at compile time so the keyboard hot path never runs the
    form-variable regex per keystroke.
    """
    form_triggers = set()
    for trigger, value in snippets.items():
        if trigger.startswith("_") or callable(value):
            continue
        if has_form_variables(extract_plain_text(value), snippets):
            form_triggers.add(trigger)
    return form_triggers


def compile_trigger_index(snippets, slow_snippets):
    """Precompute trigger lookup structures for the keyboard hot path.

    Within each last-character bucket, triggers are ordered longest-first so a
    trigger that is a suffix of another can never shadow the longer one
    (deterministic match; fixes the insertion-order hazard). Ties keep source
    order for stability.
    """
    direct_triggers = []
    direct_by_last_char = {}

    for trigger in snippets.keys():
        if trigger.startswith("_"):
            continue

        direct_triggers.append(trigger)
        last_char = trigger[-1]
        direct_by_last_char.setdefault(last_char, []).append(trigger)

    for last_char, bucket in direct_by_last_char.items():
        bucket.sort(key=len, reverse=True)  # stable: equal lengths keep source order

    dynamic_prefixes = get_dynamic_prefixes(snippets)

    return {
        "direct_triggers": tuple(direct_triggers),
        "direct_by_last_char": {key: tuple(value) for key, value in direct_by_last_char.items()},
        "dynamic_prefixes": dynamic_prefixes,
        "ordered_prefixes": tuple(dynamic_prefixes.keys()),
        "slow_triggers": frozenset(slow_snippets),
        "form_triggers": frozenset(_compute_form_triggers(snippets)),
    }


def find_direct_trigger(typed_text, trigger_index):
    """Return the longest direct trigger that matches the current suffix."""
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
