"""Resolve the Txt Xpander user-data directory and its layout.

Data lives in a stable per-user directory instead of beside the executable
(which, in the packaged build, sits inside OneDrive and is hostile to atomic
writes). The same layout works verbatim on Windows, macOS and Linux:

    <data_dir>/
        snippets.json
        settings.json
        backups/
        logs/

``TXT_XPANDER_HOME`` overrides the location (used by tests and power users).
"""

import os
import shutil

ENV_HOME = "TXT_XPANDER_HOME"
DIR_NAME = ".txt_xpander"
SNIPPETS_NAME = "snippets.json"
SETTINGS_NAME = "settings.json"
BACKUPS_DIR_NAME = "backups"
LOGS_DIR_NAME = "logs"
MIGRATION_BREADCRUMB = "migrated-from.txt"


def get_data_dir():
    """Return the user-data directory (env override, else ~/.txt_xpander)."""
    override = os.environ.get(ENV_HOME)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(os.path.expanduser("~"), DIR_NAME)


def _resolve(data_dir):
    return data_dir if data_dir is not None else get_data_dir()


def get_snippets_path(data_dir=None):
    return os.path.join(_resolve(data_dir), SNIPPETS_NAME)


def get_settings_path(data_dir=None):
    return os.path.join(_resolve(data_dir), SETTINGS_NAME)


def get_backups_dir(data_dir=None):
    return os.path.join(_resolve(data_dir), BACKUPS_DIR_NAME)


def get_logs_dir(data_dir=None):
    return os.path.join(_resolve(data_dir), LOGS_DIR_NAME)


def ensure_data_dir(data_dir=None):
    """Create the data directory (and return it) if it does not exist."""
    resolved = _resolve(data_dir)
    os.makedirs(resolved, exist_ok=True)
    return resolved


def needs_migration(legacy_snippets_path, data_dir=None):
    """True when the data dir has no snippets yet but a legacy copy exists.

    The legacy file must be a different path than the destination, so a data
    directory that already coincides with the legacy location never migrates
    onto itself.
    """
    destination = get_snippets_path(data_dir)
    if os.path.abspath(legacy_snippets_path) == os.path.abspath(destination):
        return False
    return os.path.exists(legacy_snippets_path) and not os.path.exists(destination)


def migrate_snippets(legacy_snippets_path, data_dir=None):
    """Copy a legacy exe-side snippets file into the data dir (one time).

    Leaves the legacy file untouched as an extra safety copy and drops a
    breadcrumb recording where the data came from. Returns the destination path.
    """
    resolved = ensure_data_dir(data_dir)
    destination = get_snippets_path(resolved)
    shutil.copyfile(legacy_snippets_path, destination)
    breadcrumb = os.path.join(resolved, MIGRATION_BREADCRUMB)
    try:
        with open(breadcrumb, "w", encoding="utf-8") as handle:
            handle.write(os.path.abspath(legacy_snippets_path) + "\n")
    except OSError:
        pass
    return destination
