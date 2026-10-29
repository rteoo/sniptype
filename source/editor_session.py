"""Draft state of one manager editor, kept apart from Tk.

The Textos and Mapeamentos editors are explicit-save surfaces: what the
person types is a draft until Salvar writes it. An :class:`EditorSession`
remembers which saved item the editor shows (its ``ref``) and what the
editor showed when that item was loaded (the baseline). That is enough to
tell a draft from saved work, to ask before an exit would drop it, and to
decide what a library refresh means for the editor.

Values are compared as the editor serializes them, not as they are stored:
loading a value into the Text widget and serializing it back normalizes rich
text, so the caller takes the baseline from the editor right after a load.
The stored value (``source``) is kept separately, for :meth:`reconcile`.
"""

from i18n import N_, _


class _Missing:
    def __repr__(self):
        return "MISSING"


# The library holds nothing under the editor's ref (deleted, renamed away,
# or its mapping type is gone).
MISSING = _Missing()

# What the editor shows (EditorSession.mode).
EMPTY = "empty"  # nothing: no saved item and no draft started with Novo
NEW = "new"      # a draft that is not saved anywhere yet
ITEM = "item"    # a saved item, under ``ref``

# What a library refresh means for the editor (EditorSession.reconcile).
UNCHANGED = "unchanged"
CHANGED = "changed"
GONE = "gone"

EDITOR_KINDS = ("static", "mapping")


class EditorSession:
    """Which saved item one editor shows, and whether the editor holds a draft."""

    def __init__(self, kind, container=None):
        if kind not in EDITOR_KINDS:
            raise ValueError(f"unsupported editor kind: {kind!r}")
        self.kind = kind
        self.reset(container=container)

    def reset(self, *, new=False, container=None):
        """Show nothing, or with ``new`` a fresh draft, in ``container``."""
        self.ref = None
        self.container = container
        self.mode = NEW if new else EMPTY
        self._baseline = ("", "")
        self._source = MISSING

    def load(self, ref, trigger, value, source, container=None):
        """The editor now shows saved item ``ref``.

        ``trigger`` and ``value`` are what the editor shows for it, as the
        editor serializes them; ``source`` is the value stored in the
        library. ``container`` is the mapping type of a mapping item.
        """
        if not isinstance(ref, str) or not ref:
            raise ValueError("an editor ref must be non-empty text")
        if self.kind == "mapping" and not container:
            raise ValueError("a mapping editor needs the item's mapping type")
        self.ref = ref
        self.container = container
        self.mode = ITEM
        self._baseline = (trigger.strip(), value)
        self._source = source

    def mark_saved(self, ref, trigger, value, source, container=None):
        """Salvar wrote the draft as ``ref``: it is the new baseline."""
        self.load(ref, trigger, value, source, container)

    def is_dirty(self, trigger, value):
        """Whether the editor's ``trigger`` and ``value`` differ from what is saved.

        A draft kept over a library change (:meth:`keep_draft`) stays dirty
        until it is saved or discarded, whatever it holds.
        """
        if self._baseline is None:
            return True
        return (trigger.strip(), value) != self._baseline

    def reconcile(self, stored):
        """What the library now holding ``stored`` under the ref means for the editor.

        :data:`UNCHANGED` when the editor shows no saved item or the item
        is as it was loaded, :data:`CHANGED` when it was saved differently
        since, :data:`GONE` when ``stored`` is :data:`MISSING`.
        """
        if self.ref is None:
            return UNCHANGED
        if stored is MISSING:
            return GONE
        return UNCHANGED if stored == self._source else CHANGED

    def keep_draft(self, stored):
        """Keep the draft over the library's ``stored`` value.

        The draft stays unsaved until Salvar or Descartar, so leaving it still
        asks. When the item is gone the draft becomes a new one: Salvar
        creates the item again.
        """
        self._source = stored
        self._baseline = None
        if stored is MISSING:
            self.ref = None
            self.mode = NEW

    def retarget(self, ref, trigger):
        """The saved item was renamed to ``ref``; an open draft follows it."""
        if self.ref is None:
            raise ValueError("only a saved item can be renamed")
        self.ref = ref
        if self._baseline is not None:
            self._baseline = (trigger.strip(), self._baseline[1])


def static_draft_problem(trigger, plain_text):
    """Why a Textos draft cannot be saved yet, as a message id, or None."""
    trigger = trigger.strip()
    if not trigger:
        return N_("Informe um trigger.")
    if trigger.startswith("_"):
        return N_("Triggers com '_' são reservados.")
    if not plain_text.strip():
        return N_("Informe um valor para o snippet.")
    return None


def static_trigger_problem(snippets, trigger, current=None):
    """Why ``trigger`` cannot be the stored trigger of a copy or a rename, or None.

    ``current`` is the trigger being renamed, which may keep its own name.
    """
    if not trigger:
        return _("Informe um trigger.")
    if trigger.startswith("_"):
        return _("Triggers com '_' são reservados.")
    if trigger != current and trigger in snippets:
        return _("O trigger '{new_trigger}' já existe.").format(new_trigger=trigger)
    return None


def mapping_draft_problem(name, plain_text):
    """Why a Mapeamentos draft cannot be saved yet, as a message id, or None."""
    name = name.strip()
    if not name:
        return N_("Informe um identificador.")
    if name == "__prefix__":
        return N_("'__prefix__' é reservado para o prefixo do tipo de mapeamento.")
    if not plain_text.strip():
        return N_("Informe um valor.")
    return None


def mapping_type_problem(types, snippets, type_name, prefix):
    """Why a Novo tipo draft cannot be created, as ``(field, message)``, or None.

    ``type_name`` and ``prefix`` arrive stripped and lowercased; ``types`` is
    :func:`snippet_utils.mapping_types`. ``field`` (``"name"`` or ``"prefix"``)
    names the entry the message is about.
    """
    if not type_name or not prefix:
        return ("prefix" if type_name else "name"), _("Preencha todos os campos.")
    for field, value in (("name", type_name), ("prefix", prefix)):
        if not value.replace("_", "").isalnum():
            return field, _("Use apenas letras, números e underscores.")
    if any(info.get("prefix") == prefix for info in types.values()):
        return "prefix", _("O prefixo '{prefix}' já está em uso por outro tipo de mapeamento.").format(prefix=prefix)
    if mapping_type_key(type_name) in snippets:
        return "name", _("Tipo '{type_name}' já existe.").format(type_name=type_name)
    return None


def mapping_type_key(type_name):
    """The library key a new custom mapping type is stored under."""
    return f"_{type_name}_codes"


__all__ = [
    "CHANGED", "EDITOR_KINDS", "EMPTY", "EditorSession", "GONE", "ITEM", "MISSING",
    "NEW", "UNCHANGED", "mapping_draft_problem", "mapping_type_key", "mapping_type_problem",
    "static_draft_problem", "static_trigger_problem",
]
