"""Rotating backups and corrupt-file quarantine for the snippets library.

Pure filesystem helpers with no app dependencies so they stay unit-testable.
Timestamps are injected as strings/epoch seconds by callers to keep tests
deterministic; production callers pass the real time.
"""

import glob
import os
import shutil
import time


BACKUP_PREFIX = "snippets-"
BACKUP_SUFFIX = ".json"
BACKUP_GLOB = f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"
QUARANTINE_PREFIX = "snippets.corrupt-"
DEFAULT_KEEP = 30
STARTUP_BACKUP_MAX_AGE_SECONDS = 24 * 60 * 60


def format_timestamp(now=None):
    """Return a filesystem-safe local timestamp (YYYYMMDD-HHMMSS)."""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now))


def _dedupe_path(path):
    """Return a path that does not exist yet, appending -1, -2 ... if needed."""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    counter = 1
    while True:
        candidate = f"{root}-{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def _same_content(path_a, path_b):
    try:
        with open(path_a, "rb") as handle_a, open(path_b, "rb") as handle_b:
            return handle_a.read() == handle_b.read()
    except OSError:
        return False


def list_backups(backups_dir):
    """Return backup file paths newest-first (by mtime, then name)."""
    paths = glob.glob(os.path.join(backups_dir, BACKUP_GLOB))
    return sorted(paths, key=lambda p: (os.path.getmtime(p), p), reverse=True)


def find_latest_backup(backups_dir):
    """Return the newest backup path, or None when there are none."""
    backups = list_backups(backups_dir)
    return backups[0] if backups else None


def create_backup(snippets_path, backups_dir, timestamp=None, force=False):
    """Copy the current snippets file into backups_dir.

    Skips (returns None) when the source is missing or byte-identical to the
    newest existing backup. Pass ``force=True`` for an explicit "backup now"
    action that should always produce a file. Returns the backup path written.
    """
    if not os.path.exists(snippets_path):
        return None

    os.makedirs(backups_dir, exist_ok=True)

    if not force:
        latest = find_latest_backup(backups_dir)
        if latest is not None and _same_content(snippets_path, latest):
            return None

    timestamp = timestamp or format_timestamp()
    dest = _dedupe_path(os.path.join(backups_dir, f"{BACKUP_PREFIX}{timestamp}{BACKUP_SUFFIX}"))
    shutil.copy2(snippets_path, dest)
    return dest


def prune_backups(backups_dir, keep=DEFAULT_KEEP):
    """Delete all but the newest ``keep`` backups. Return removed paths."""
    removed = []
    for path in list_backups(backups_dir)[keep:]:
        try:
            os.remove(path)
            removed.append(path)
        except OSError:
            pass
    return removed


def quarantine_corrupt_file(path, timestamp=None):
    """Rename a corrupt snippets file aside so it is never overwritten.

    Uses ``os.replace`` (atomic rename, bytes preserved). Returns the new path.
    """
    timestamp = timestamp or format_timestamp()
    dest = _dedupe_path(
        os.path.join(os.path.dirname(path) or ".", f"{QUARANTINE_PREFIX}{timestamp}{BACKUP_SUFFIX}")
    )
    os.replace(path, dest)
    return dest


def newest_backup_age_seconds(backups_dir, now=None):
    """Return seconds since the newest backup, or None when none exist."""
    latest = find_latest_backup(backups_dir)
    if latest is None:
        return None
    now = now if now is not None else time.time()
    return now - os.path.getmtime(latest)


def should_backup_on_startup(backups_dir, now=None, max_age_seconds=STARTUP_BACKUP_MAX_AGE_SECONDS):
    """True when there is no backup, or the newest one is older than the window."""
    age = newest_backup_age_seconds(backups_dir, now=now)
    return age is None or age >= max_age_seconds
