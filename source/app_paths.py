"""Resolve the Sniptype user-data directory and its layout.

Data lives in a stable per-user directory instead of beside the executable
(which, in the packaged build, sits inside OneDrive and is hostile to atomic
writes). The same layout works verbatim on Windows, macOS and Linux:

    <data_dir>/
        snippets.json
        settings.json
        backups/
        logs/

``SNIPTYPE_HOME`` overrides the location (used by tests and power users).
The old ``TXT_XPANDER_HOME`` override and ``~/.txt_xpander`` directory are
recognized only as migration fallbacks and are never removed or modified.
"""

import os
import shutil

ENV_HOME = "SNIPTYPE_HOME"
LEGACY_ENV_HOME = "TXT_XPANDER_HOME"
DIR_NAME = ".sniptype"
LEGACY_DIR_NAME = ".txt_xpander"
SNIPPETS_NAME = "snippets.json"
SETTINGS_NAME = "settings.json"
BACKUPS_DIR_NAME = "backups"
LOGS_DIR_NAME = "logs"
MIGRATION_BREADCRUMB = "migrated-from.txt"
LEGACY_MIGRATION_BREADCRUMB = "migrated-from-txt_xpander.txt"


def get_data_dir():
    """Return the canonical user-data directory.

    ``TXT_XPANDER_HOME`` remains a read/write override for existing scripted
    deployments. New installs use ``SNIPTYPE_HOME`` or ``~/.sniptype``.
    """
    override = os.environ.get(ENV_HOME)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    legacy_override = os.environ.get(LEGACY_ENV_HOME)
    if legacy_override:
        return os.path.abspath(os.path.expanduser(legacy_override))
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
    if data_dir is None and not os.environ.get(ENV_HOME) and not os.environ.get(LEGACY_ENV_HOME):
        _migrate_legacy_data_dir(resolved)
    return resolved


def _legacy_data_dir():
    return os.path.join(os.path.expanduser("~"), LEGACY_DIR_NAME)


def _migrate_legacy_data_dir(destination):
    """Copy legacy user data into the canonical directory once.

    The source remains untouched. Each item is copied only when absent at the
    destination, making interruption safe and avoiding overwriting newer data
    a user may have created in ``~/.sniptype``.
    """
    legacy = _legacy_data_dir()
    if os.path.abspath(legacy) == os.path.abspath(destination) or not os.path.isdir(legacy):
        return False
    marker = os.path.join(destination, LEGACY_MIGRATION_BREADCRUMB)
    copied = False
    try:
        for name in os.listdir(legacy):
            source = os.path.join(legacy, name)
            target = os.path.join(destination, name)
            if os.path.exists(target):
                continue
            if os.path.isdir(source) and not os.path.islink(source):
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            copied = True
        if copied and not os.path.exists(marker):
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write(os.path.abspath(legacy) + "\n")
    except OSError:
        # A partial copy is safe to retry on the next startup; the old source is
        # deliberately retained as the recovery copy.
        return copied
    return copied


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
