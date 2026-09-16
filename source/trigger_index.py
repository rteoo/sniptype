from dataclasses import dataclass

from rich_text_support import extract_plain_text
from group_policy import (
    ApplicationPolicy,
    application_policy_allows,
    effective_trigger,
    get_static_item_metadata,
    item_group_policy,
    resolve_terminator_policy,
)
from snippet_utils import check_dynamic_pattern, get_dynamic_prefixes
from variable_support import find_variable_names, has_form_variables


@dataclass(frozen=True)
class ExpansionTarget:
    """Immutable direct-expansion identity captured during index compilation."""

    effective_trigger: str
    source_kind: str
    stable_identity: str

    @property
    def trigger(self):
        """Compatibility spelling used by callers that call it just a trigger."""
        return self.effective_trigger

    @property
    def source_identity(self):
        """Compatibility spelling for the stable source identity."""
        return self.stable_identity


def _is_indexable_trigger(trigger):
    """Whether a snippets-dict key is a real, indexable trigger.

    An empty key would suffix-match every keystroke (``endswith("")`` is always
    true) and has no last character to bucket by; an ``_``-prefixed key names a
    mapping container, not a trigger. Both are excluded from every index set so
    the direct index and the metadata helpers never disagree about what "" is.
    Callable handling is intentionally left to each caller: the direct-index
    loop indexes keys regardless of value, while the metadata helpers skip
    callables.
    """
    return bool(trigger) and not trigger.startswith("_")


def _compute_form_triggers(snippets, prefixes=None):
    """Return triggers whose value needs a form-fill dialog.

    Computed once at compile time so the keyboard hot path never runs the
    form-variable regex per keystroke. Includes both direct triggers and
    triggers composed from a dynamic-mapping prefix plus item name.
    """
    if prefixes is None:
        prefixes = get_dynamic_prefixes(snippets)

    form_triggers = set()
    for trigger, value in snippets.items():
        if not _is_indexable_trigger(trigger) or callable(value):
            continue
        if has_form_variables(extract_plain_text(value), snippets, prefixes):
            form_triggers.add(trigger)

    for prefix, mapping_key in prefixes.items():
        mapping = snippets.get(mapping_key)
        if not isinstance(mapping, dict):
            continue
        for item_name, value in mapping.items():
            if item_name == "__prefix__" or callable(value):
                continue
            if has_form_variables(extract_plain_text(value), snippets, prefixes):
                form_triggers.add(prefix + item_name)

    return form_triggers


def _compute_slow_ref_triggers(snippets, slow_snippets):
    """Return direct triggers whose body references a slow dynamic trigger.

    Such a snippet must run on the async path: resolving the reference fetches
    over the network or opens a dialog, which would otherwise block the listener.
    """
    slow_ref_triggers = set()
    for trigger, value in snippets.items():
        if not _is_indexable_trigger(trigger) or callable(value):
            continue
        if any(name in slow_snippets for name in find_variable_names(extract_plain_text(value))):
            slow_ref_triggers.add(trigger)
    return slow_ref_triggers


def _sort_buckets(buckets):
    for bucket in buckets.values():
        bucket.sort(key=lambda target: len(target.effective_trigger), reverse=True)
    return {key: tuple(value) for key, value in buckets.items()}


def compile_trigger_index(
    snippets,
    slow_snippets,
    metadata=None,
    terminator_mode=False,
    global_terminator_mode=None,
):
    """Precompute trigger lookup structures for the keyboard hot path.

    Within each last-character bucket, triggers are ordered longest-first so a
    trigger that is a suffix of another can never shadow the longer one
    (deterministic match; fixes the insertion-order hazard). Ties keep source
    order for stability.
    """
    if global_terminator_mode is not None:
        terminator_mode = global_terminator_mode

    direct_triggers = []
    direct_by_last_char = {}
    direct_targets = []
    direct_targets_by_last_char = {}
    immediate_targets_by_last_char = {}
    terminated_targets_by_last_char = {}
    application_policies = {}

    for trigger, value in snippets.items():
        # An empty key has no last char (crash below) and would suffix-match
        # every keystroke; an ``_``-prefixed key is a mapping container.
        if not _is_indexable_trigger(trigger):
            continue

        if callable(value):
            # Registry-backed dynamics keep their existing global policy and
            # stable key; metadata never scopes a dynamic callable.
            target = ExpansionTarget(trigger, "dynamic", trigger)
            terminated = bool(terminator_mode)
            application_policy = ApplicationPolicy()
        else:
            group = item_group_policy(metadata, trigger)
            if not group.enabled:
                continue
            item_metadata = get_static_item_metadata(metadata, trigger)
            target = ExpansionTarget(
                effective_trigger(trigger, metadata, item_metadata),
                "static",
                trigger,
            )
            terminated = resolve_terminator_policy(
                item_metadata,
                metadata,
                terminator_mode,
            )
            application_policy = group.applications

        direct_targets.append(target)
        direct_triggers.append(target.effective_trigger)
        last_char = target.effective_trigger[-1]
        direct_by_last_char.setdefault(last_char, []).append(target.effective_trigger)
        direct_targets_by_last_char.setdefault(last_char, []).append(target)
        target_buckets = (
            terminated_targets_by_last_char
            if terminated
            else immediate_targets_by_last_char
        )
        target_buckets.setdefault(last_char, []).append(target)
        application_policies[target.stable_identity] = application_policy

    direct_by_last_char = {
        key: tuple(sorted(value, key=len, reverse=True))
        for key, value in direct_by_last_char.items()
    }
    direct_targets_by_last_char = _sort_buckets(direct_targets_by_last_char)
    immediate_targets_by_last_char = _sort_buckets(immediate_targets_by_last_char)
    terminated_targets_by_last_char = _sort_buckets(terminated_targets_by_last_char)

    dynamic_prefixes = get_dynamic_prefixes(snippets)
    bare_mapping_by_last_char = {}
    bare_mapping_key = dynamic_prefixes.get("")
    bare_mapping = snippets.get(bare_mapping_key)
    if isinstance(bare_mapping, dict):
        for item_name in bare_mapping:
            if item_name == "__prefix__" or not isinstance(item_name, str) or not item_name:
                continue
            bare_mapping_by_last_char.setdefault(item_name[-1], []).append(item_name)
        for bucket in bare_mapping_by_last_char.values():
            bucket.sort(key=len, reverse=True)

    slow_triggers = set(slow_snippets) | _compute_slow_ref_triggers(snippets, slow_snippets)
    form_triggers = _compute_form_triggers(snippets, dynamic_prefixes)
    raw_slow_triggers = set(slow_triggers)
    raw_form_triggers = set(form_triggers)
    static_ids = {
        trigger
        for trigger, value in snippets.items()
        if _is_indexable_trigger(trigger) and not callable(value)
    }
    slow_triggers.difference_update(static_ids)
    form_triggers.difference_update(static_ids)
    for target in direct_targets:
        if target.source_kind != "static":
            continue
        if target.stable_identity in raw_slow_triggers:
            slow_triggers.add(target.effective_trigger)
        if target.stable_identity in raw_form_triggers:
            form_triggers.add(target.effective_trigger)

    return {
        "direct_triggers": tuple(direct_triggers),
        "direct_by_last_char": direct_by_last_char,
        "direct_targets": tuple(direct_targets),
        "direct_targets_by_last_char": direct_targets_by_last_char,
        "direct_immediate_by_last_char": immediate_targets_by_last_char,
        "direct_terminated_by_last_char": terminated_targets_by_last_char,
        "direct_immediate_targets_by_last_char": immediate_targets_by_last_char,
        "direct_terminated_targets_by_last_char": terminated_targets_by_last_char,
        "immediate_by_last_char": immediate_targets_by_last_char,
        "terminated_by_last_char": terminated_targets_by_last_char,
        "application_policies": application_policies,
        "global_terminator_mode": bool(terminator_mode),
        "dynamic_prefixes": dynamic_prefixes,
        "ordered_prefixes": tuple(dynamic_prefixes.keys()),
        "bare_mapping_by_last_char": {
            key: tuple(value) for key, value in bare_mapping_by_last_char.items()
        },
        "slow_triggers": frozenset(slow_triggers),
        "form_triggers": frozenset(form_triggers),
    }


def target_application_policy(target, trigger_index):
    """Return a target's compiled application policy without metadata access."""
    return trigger_index.get("application_policies", {}).get(
        target.stable_identity,
        ApplicationPolicy(),
    )


def target_is_allowed(target, trigger_index, executable=None, *, windows=True):
    """Evaluate a compiled target without scanning metadata at match time."""
    policy = target_application_policy(target, trigger_index)
    return application_policy_allows(policy, executable, windows=windows)


def find_direct_candidate(typed_text, trigger_index, terminated=False):
    """Return the longest suffix candidate before application-policy I/O."""
    if not typed_text:
        return None

    bucket_name = (
        "direct_terminated_by_last_char"
        if terminated
        else "direct_immediate_by_last_char"
    )
    candidates = trigger_index.get(bucket_name, {}).get(typed_text[-1], ())
    for target in candidates:
        if typed_text.endswith(target.effective_trigger):
            return target

    return None


def find_direct_target(
    typed_text,
    trigger_index,
    terminated=False,
    executable=None,
    *,
    windows=True,
):
    """Return the longest allowed target, never falling back after denial."""
    target = find_direct_candidate(typed_text, trigger_index, terminated)
    if target is None:
        return None
    if not target_is_allowed(target, trigger_index, executable, windows=windows):
        return None
    return target


def find_direct_trigger(typed_text, trigger_index, terminated=False):
    """Return the longest direct trigger that matches the current suffix."""
    target = find_direct_target(typed_text, trigger_index, terminated)
    return target.effective_trigger if target is not None else None


def find_dynamic_trigger(snippets, typed_text, trigger_index):
    """Return the full typed trigger and mapped value for dynamic mappings."""
    if not typed_text:
        return None, None

    dynamic_prefixes = trigger_index["dynamic_prefixes"]
    for prefix in trigger_index["ordered_prefixes"]:
        if prefix == "":
            mapping = snippets.get(dynamic_prefixes[prefix])
            candidates = trigger_index["bare_mapping_by_last_char"].get(
                typed_text[-1], ()
            )
            for item_name in candidates:
                if typed_text.endswith(item_name):
                    value = mapping.get(item_name)
                    if value is not None:
                        return item_name, value
            continue
        if prefix in typed_text:
            prefix_start = typed_text.rfind(prefix)
            potential_trigger = typed_text[prefix_start:]
            value, _ = check_dynamic_pattern(snippets, potential_trigger, dynamic_prefixes)
            if value is not None:
                return potential_trigger, value

    return None, None
