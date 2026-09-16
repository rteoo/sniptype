"""Pure group and application-policy helpers for the metadata-aware index.

The runtime keeps the JSON library and its optional ``__sniptype__`` metadata
separate.  This module turns the schema-v1 group/item fragments into small
immutable values so trigger compilation can do all policy work once, away
from the keyboard listener hot path.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import ntpath


VALID_TERMINATOR_POLICIES = frozenset({"inherit", "immediate", "terminator"})
VALID_APPLICATION_MODES = frozenset({"all", "allow", "deny"})


@dataclass(frozen=True)
class ApplicationPolicy:
    """Normalized executable policy attached to a group."""

    mode: str = "all"
    executables: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupPolicy:
    """Immutable, normalized schema-v1 group definition."""

    group_id: str | None = None
    label: str = "Ungrouped"
    notes: str = ""
    prefix: str = ""
    enabled: bool = True
    terminator: str = "inherit"
    applications: ApplicationPolicy = ApplicationPolicy()


UNGROUPED = GroupPolicy()


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def normalize_executable_name(value):
    """Return a case-folded executable basename, or ``None`` when invalid."""
    if not isinstance(value, str):
        return None
    basename = ntpath.basename(value.replace("/", "\\")).strip()
    return basename.casefold() or None


def normalize_application_policy(value):
    """Normalize an ``applications`` schema fragment without raising."""
    raw = _mapping(value)
    mode = raw.get("mode", "all")
    if mode not in VALID_APPLICATION_MODES:
        mode = "all"
    values = raw.get("executables", ())
    if isinstance(values, str) or not isinstance(values, (list, tuple, set, frozenset)):
        values = ()
    executables = []
    for candidate in values:
        normalized = normalize_executable_name(candidate)
        if normalized is not None and normalized not in executables:
            executables.append(normalized)
    return ApplicationPolicy(mode, tuple(executables))


def normalize_group(group_id, value):
    """Return a normalized immutable policy for one schema-v1 group."""
    raw = _mapping(value)
    normalized_id = None if group_id is None else str(group_id)
    label = raw.get("label", "Ungrouped" if normalized_id is None else normalized_id)
    notes = raw.get("notes", "")
    prefix = raw.get("prefix", "")
    if not isinstance(label, str):
        label = str(label)
    if not isinstance(notes, str):
        notes = str(notes)
    if not isinstance(prefix, str):
        prefix = ""
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        enabled = False
    terminator = raw.get("terminator", "inherit")
    if terminator not in VALID_TERMINATOR_POLICIES:
        terminator = "inherit"
    return GroupPolicy(
        group_id=normalized_id,
        label=label,
        notes=notes,
        prefix=prefix,
        enabled=enabled,
        terminator=terminator,
        applications=normalize_application_policy(raw.get("applications")),
    )


def normalize_groups(metadata):
    """Return all schema-v1 groups as ``group_id -> GroupPolicy``."""
    groups = _mapping(_mapping(metadata).get("groups"))
    return {str(group_id): normalize_group(group_id, value) for group_id, value in groups.items()}


def get_group(metadata, group_id):
    """Return a normalized group, falling back to implicit Ungrouped."""
    if group_id is None:
        return UNGROUPED
    return normalize_groups(metadata).get(str(group_id), UNGROUPED)


def get_static_item_metadata(metadata, stored_key):
    """Return a defensive static-item metadata mapping, or an empty mapping."""
    items = _mapping(_mapping(metadata).get("items"))
    static_items = _mapping(items.get("static"))
    value = static_items.get(stored_key)
    return dict(value) if isinstance(value, Mapping) else {}


def effective_trigger(stored_key, metadata=None, item_metadata=None):
    """Compose ``group.prefix + stored_key`` without changing its identity."""
    if not isinstance(stored_key, str):
        return stored_key
    item = item_metadata if item_metadata is not None else get_static_item_metadata(metadata, stored_key)
    group = get_group(metadata, _mapping(item).get("group_id"))
    return group.prefix + stored_key


def item_group_policy(metadata, stored_key, item_metadata=None):
    """Resolve the normalized group for a static item."""
    item = item_metadata if item_metadata is not None else get_static_item_metadata(metadata, stored_key)
    return get_group(metadata, _mapping(item).get("group_id"))


def resolve_terminator_policy(item_metadata, metadata=None, global_terminator_mode=False):
    """Return whether an item uses terminated expansion under the global mode."""
    group = item_group_policy(metadata, None, item_metadata)
    if group.terminator == "immediate":
        return False
    if group.terminator == "terminator":
        return True
    return bool(global_terminator_mode)


def application_policy_allows(policy, executable, *, windows=True):
    """Evaluate an application policy against a basename or unknown identity.

    Allowlisting on an unsupported platform fails closed.  Denylists permit an
    unknown identity, as the policy is an accidental-expansion control rather
    than an authentication boundary.
    """
    if not isinstance(policy, ApplicationPolicy):
        policy = normalize_application_policy(policy)
    if policy.mode == "all":
        return True
    if policy.mode == "allow":
        if not windows:
            return False
        executable = normalize_executable_name(executable)
        return executable is not None and executable in policy.executables
    executable = normalize_executable_name(executable)
    return executable is None or executable not in policy.executables


def static_item_enabled(metadata, stored_key):
    """Return whether a static item contributes to the runtime index."""
    return item_group_policy(metadata, stored_key).enabled


def validate_effective_triggers(snippets, metadata=None):
    """Report exact effective-trigger collisions and suffix reachability risks.

    The result is pure JSON-shaped data.  ``collisions`` contains
    ``(effective_trigger, stored_keys)`` pairs; ``reachability_warnings``
    contains ``(shorter, longer)`` pairs where longest-first matching makes the
    shorter trigger unreachable for the longer suffix.
    """
    keys = snippets.keys() if isinstance(snippets, Mapping) else snippets
    effective = {}
    for stored_key in keys or ():
        if not isinstance(stored_key, str) or not stored_key or stored_key.startswith("_"):
            continue
        if metadata is not None and not static_item_enabled(metadata, stored_key):
            continue
        trigger = effective_trigger(stored_key, metadata)
        effective.setdefault(trigger, []).append(stored_key)

    collisions = tuple(
        (trigger, tuple(stored_keys))
        for trigger, stored_keys in effective.items()
        if len(stored_keys) > 1
    )
    triggers = tuple(effective)
    reachability = tuple(
        (shorter, longer)
        for shorter in triggers
        for longer in triggers
        if shorter != longer and len(shorter) < len(longer) and longer.endswith(shorter)
    )
    return {
        "collisions": collisions,
        "reachability_warnings": reachability,
    }


# Names kept explicit for callers that describe the check as collision-only.
find_trigger_collisions = validate_effective_triggers
resolve_terminator = resolve_terminator_policy
allows_executable = application_policy_allows


__all__ = [
    "ApplicationPolicy",
    "GroupPolicy",
    "UNGROUPED",
    "allows_executable",
    "application_policy_allows",
    "effective_trigger",
    "find_trigger_collisions",
    "get_group",
    "get_static_item_metadata",
    "item_group_policy",
    "normalize_application_policy",
    "normalize_executable_name",
    "normalize_group",
    "normalize_groups",
    "resolve_terminator",
    "resolve_terminator_policy",
    "static_item_enabled",
    "validate_effective_triggers",
]
