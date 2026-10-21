"""What is wrong with the running app, as one ordered list.

``build_health`` is the pure projection behind the manager's InfoBar slot
(``DESIGN.md``, operations extensions). It reads facts the app already
records at their source (a failed capture, a quarantined library, a failed
mirror) and answers with the issues a person has to know about: most severe
first, each with one recovery action. A healthy app answers with an empty
list, and the window then says nothing.

Severity is the producer's call, made here and never escalated or softened by
the view: ``error`` is the shared ladder's critical (the core job fails or
data is at risk), ``warning`` is degraded or needs a decision, ``info`` is
worth knowing and the only kind a person may dismiss. Pure: callers pass
``now``, and every title and body is an interface string.
"""

from dataclasses import dataclass
from datetime import datetime

import time_format
from i18n import N_, _

ERROR = "error"
WARNING = "warning"
INFO = "info"
SEVERITY_ORDER = (ERROR, WARNING, INFO)

# Recovery actions. The view owns what each one does; the label is vocabulary.
RESUME = "resume"
OPEN_BACKUPS = "open_backups"
OPEN_FOLDER = "open_folder"
OPEN_LOG = "open_log"
RETRY_SYNC = "retry_sync"
OPEN_DYNAMIC = "open_dynamic"

ACTION_LABELS = {
    RESUME: N_("Retomar"),
    OPEN_BACKUPS: N_("Ver cópias de segurança"),
    OPEN_FOLDER: N_("Abrir pasta"),
    OPEN_LOG: N_("Abrir log"),
    RETRY_SYNC: N_("Tentar agora"),
    OPEN_DYNAMIC: N_("Ver ações dinâmicas"),
}

# The three states of expansion itself (the shared vocabulary's `ok`, `paused`
# and `down`). They never collapse into one another: a failed capture is not a
# pause, and resuming does not fix it.
EXPANSION_OK = "ok"
EXPANSION_PAUSED = "paused"
EXPANSION_DOWN = "down"
EXPANSION_LABELS = {
    EXPANSION_OK: N_("Expansão ativa"),
    EXPANSION_PAUSED: N_("Expansão pausada"),
    EXPANSION_DOWN: N_("Captura falhou"),
}

# How a library that was not read cleanly came back (Sniptype.library_recovery).
RECOVERED_FROM_BACKUP = "backup"
SAMPLE_DEFAULTS = "samples"

# Shadowed triggers listed by name before the rest are counted.
_SHADOWED_NAMES_SHOWN = 4


def expansion_state(enabled, capture_error):
    """Which of the three expansion states the app is in."""
    if capture_error is not None:
        return EXPANSION_DOWN
    return EXPANSION_OK if enabled else EXPANSION_PAUSED


def expansion_label(state):
    """The written name of an expansion state, in the interface language."""
    return _(EXPANSION_LABELS[state])


@dataclass(frozen=True)
class HealthFacts:
    """Everything ``build_health`` reads; a default is a healthy app.

    ``library_recovery`` is ``{"kind": "backup" | "samples", "at": ISO,
    "backup_at": ISO or None, "quarantined": file name or None}``;
    ``last_save_error`` is ``{"at": ISO, "error": text}``; ``last_mirror`` and
    ``last_sync`` are ``{"ok": bool, "at": ISO, "error": text or None, "path":
    text}``, or None before the first attempt of the session.
    """

    enabled: bool = True
    capture_error: object = None
    library_recovery: dict = None
    metadata_read_only: bool = False
    metadata_malformed: bool = False
    shadowed: tuple = ()
    last_save_error: dict = None
    last_mirror: dict = None
    last_sync: dict = None


@dataclass(frozen=True)
class Issue:
    """One thing the person has to know about, with the one way to fix it."""

    id: str
    severity: str
    title: str
    body: str
    action_id: str = None

    @property
    def action_label(self):
        return _(ACTION_LABELS[self.action_id]) if self.action_id else None

    @property
    def dismissible(self):
        return self.severity == INFO


def _moment(record, key="at"):
    """The datetime a fact recorded, or None when it holds none that parses."""
    value = record.get(key) if isinstance(record, dict) else None
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _stamp(record, now, key="at"):
    moment = _moment(record, key)
    return time_format.absolute_stamp(moment, now) if moment else ""


def _last_try(record, now):
    stamp = _stamp(record, now)
    return " " + _("Última tentativa: {when}.").format(when=stamp) if stamp else ""


def _capture_failed():
    return Issue(
        "capture-failed", ERROR,
        _("Captura falhou"),
        _("O SnipType não consegue ler o teclado, então nenhum snippet expande. "
          "Reinicie o SnipType; o log guarda o detalhe."),
        OPEN_LOG,
    )


def _sample_defaults(recovery):
    quarantined = recovery.get("quarantined")
    if quarantined:
        body = _("O snippets.json estava corrompido e não havia backup válido. "
                 "Ele foi isolado como {file}; seus snippets não estão nesta biblioteca.").format(
                     file=quarantined)
    else:
        body = _("O snippets.json estava corrompido e não havia backup válido. "
                 "Seus snippets não estão nesta biblioteca.")
    return Issue(
        "samples:" + str(recovery.get("at") or ""), ERROR,
        _("Usando a biblioteca de exemplo"), body, OPEN_FOLDER,
    )


def _restored_from_backup(recovery, now):
    taken = _stamp(recovery, now, "backup_at")
    title = (_("Biblioteca restaurada do backup · {when}").format(when=taken)
             if taken else _("Biblioteca restaurada de um backup"))
    quarantined = recovery.get("quarantined")
    if quarantined:
        body = _("O snippets.json estava corrompido e foi isolado como {file}. "
                 "O que foi alterado depois desse backup não está aqui.").format(file=quarantined)
    else:
        body = _("O snippets.json estava corrompido. "
                 "O que foi alterado depois desse backup não está aqui.")
    return Issue("restored:" + str(recovery.get("at") or ""), INFO, title, body, OPEN_BACKUPS)


def _save_failed(failure, now):
    return Issue(
        "save-failed", ERROR,
        _("Não foi possível salvar a biblioteca"),
        _("A última gravação do snippets.json falhou. Suas alterações continuam no editor; "
          "verifique o espaço em disco e as permissões da pasta de dados.")
        + _last_try(failure, now),
        OPEN_LOG,
    )


def _paused():
    return Issue(
        "paused", WARNING,
        _("Expansão pausada"),
        _("Nenhum trigger expande até você retomar."),
        RESUME,
    )


def _metadata_unavailable(malformed):
    if malformed:
        body = _("Os metadados da biblioteca estão malformados. Os snippets continuam "
                 "funcionando, mas grupos, formulários e favoritos não podem ser "
                 "alterados nesta versão.")
    else:
        body = _("Os metadados da biblioteca são de uma versão mais nova. Os snippets "
                 "continuam funcionando, mas grupos, formulários e favoritos não podem "
                 "ser alterados nesta versão.")
    return Issue(
        "metadata-read-only", WARNING,
        _("Metadados da biblioteca somente leitura"), body, OPEN_FOLDER,
    )


def _shadowed(names):
    shown = list(names[:_SHADOWED_NAMES_SHOWN])
    listed = ", ".join(shown)
    rest = len(names) - len(shown)
    if rest > 0:
        listed = _("{names} e mais {count}").format(names=listed, count=rest)
    return Issue(
        "shadowed", WARNING,
        _("Triggers em conflito com ações dinâmicas"),
        _("{names}. A ação dinâmica é que expande; o texto salvo continua no snippets.json.").format(
            names=listed),
        OPEN_DYNAMIC,
    )


def _mirror_failed(record, now):
    return Issue(
        "mirror-failed", WARNING,
        _("Cópia espelho não gravada"),
        _("A cópia da biblioteca para a pasta espelho falhou. A biblioteca local está salva; "
          "confira a pasta configurada.") + _last_try(record, now),
        RETRY_SYNC,
    )


def _sync_failed(record, now):
    return Issue(
        "sync-failed", WARNING,
        _("Pacote de sincronização não exportado"),
        _("A exportação do pacote de sincronização falhou. A biblioteca local está salva; "
          "confira a pasta configurada.") + _last_try(record, now),
        RETRY_SYNC,
    )


def _failed(record):
    return isinstance(record, dict) and record.get("ok") is False


# What the Dados card says about each destination: ``copy`` is the mirror,
# ``export`` the sync bundle.
_TRANSFER_OK = {
    "copy": N_("Última cópia {when} · OK"),
    "export": N_("Última exportação {when} · OK"),
}
_TRANSFER_FAILED = {
    "copy": N_("Última cópia falhou {when} · {error}"),
    "export": N_("Última exportação falhou {when} · {error}"),
}
_TRANSFER_NONE = {
    "copy": N_("Nenhuma cópia nesta sessão ainda."),
    "export": N_("Nenhuma exportação nesta sessão ainda."),
}


def describe_transfer(kind, record, now=None):
    """``(text, failed)``: the last mirror copy or sync export, in one line.

    ``kind`` is ``"copy"`` or ``"export"``; ``record`` is ``last_mirror`` or
    ``last_sync``. Nothing has happened until the first save of the session.
    """
    now = now or datetime.now()
    if not isinstance(record, dict):
        return _(_TRANSFER_NONE[kind]), False
    when = _stamp(record, now) or "—"
    if record.get("ok") is False:
        text = _(_TRANSFER_FAILED[kind]).format(
            when=when, error=record.get("error") or _("sem detalhe"))
        return text, True
    return _(_TRANSFER_OK[kind]).format(when=when), False


def build_health(facts, now=None):
    """The issues in ``facts``, most severe first; empty when nothing is wrong.

    Within a severity the order is fixed by how much of the app's job each
    one takes away. A failed capture is never also reported as a pause: the
    pause is its consequence, and resuming would not help.
    """
    now = now or datetime.now()
    issues = []
    if facts.capture_error is not None:
        issues.append(_capture_failed())
    elif not facts.enabled:
        issues.append(_paused())
    recovery = facts.library_recovery
    if recovery:
        if recovery.get("kind") == SAMPLE_DEFAULTS:
            issues.append(_sample_defaults(recovery))
        elif recovery.get("kind") == RECOVERED_FROM_BACKUP:
            issues.append(_restored_from_backup(recovery, now))
    if facts.last_save_error:
        issues.append(_save_failed(facts.last_save_error, now))
    if facts.metadata_read_only:
        issues.append(_metadata_unavailable(facts.metadata_malformed))
    if facts.shadowed:
        issues.append(_shadowed(tuple(facts.shadowed)))
    if _failed(facts.last_mirror):
        issues.append(_mirror_failed(facts.last_mirror, now))
    if _failed(facts.last_sync):
        issues.append(_sync_failed(facts.last_sync, now))
    # Stable: equal severities keep the order above.
    return sorted(issues, key=lambda issue: SEVERITY_ORDER.index(issue.severity))


__all__ = [
    "ACTION_LABELS",
    "ERROR",
    "EXPANSION_DOWN",
    "EXPANSION_LABELS",
    "EXPANSION_OK",
    "EXPANSION_PAUSED",
    "HealthFacts",
    "INFO",
    "Issue",
    "OPEN_BACKUPS",
    "OPEN_DYNAMIC",
    "OPEN_FOLDER",
    "OPEN_LOG",
    "RECOVERED_FROM_BACKUP",
    "RESUME",
    "RETRY_SYNC",
    "SAMPLE_DEFAULTS",
    "SEVERITY_ORDER",
    "WARNING",
    "build_health",
    "describe_transfer",
    "expansion_label",
    "expansion_state",
]
