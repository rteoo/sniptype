import json
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backup_support as bs
import runtime_support
from app_module import txt_xpander as tx  # .pyw is not importable off Windows


def make_expander(base_dir, snippets_content=None):
    """Construct a TextExpander rooted at base_dir without touching real data.

    Pins the data dir to base_dir via TXT_XPANDER_HOME so nothing is written to
    the real ~/.txt_xpander during tests.
    """
    if snippets_content is not None:
        with open(os.path.join(base_dir, "snippets.json"), "w", encoding="utf-8") as handle:
            handle.write(snippets_content)
    previous_home = os.environ.get("TXT_XPANDER_HOME")
    os.environ["TXT_XPANDER_HOME"] = base_dir
    try:
        with mock.patch.object(tx, "get_runtime_base_dir", return_value=base_dir), \
                mock.patch.object(tx, "get_runtime_resource_dir", return_value=base_dir):
            return tx.TextExpander()
    finally:
        if previous_home is None:
            os.environ.pop("TXT_XPANDER_HOME", None)
        else:
            os.environ["TXT_XPANDER_HOME"] = previous_home


class SaveSnippetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_expander(self.tmp, '{"xhi": "hello"}')

    def test_save_returns_true_and_backs_up_previous(self):
        # Change content so a new backup is warranted, then save.
        self.app.snippets = {"xhi": "changed"}
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"xhi": "changed"})
        # A backup of the pre-write "hello" content exists.
        contents = []
        for path in bs.list_backups(self.app.backups_dir):
            with open(path, encoding="utf-8") as handle:
                contents.append(json.load(handle))
        self.assertIn({"xhi": "hello"}, contents)

    def test_save_failure_returns_false(self):
        with mock.patch.object(tx, "write_json_atomic", side_effect=OSError("disk full")):
            self.assertFalse(self.app.save_snippets({"xhi": "x"}))

    def test_save_strips_callables(self):
        self.app.snippets = {"xhi": "hello", "xnow": lambda: "dynamic"}
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertNotIn("xnow", data)


class BackupRestoreImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_expander(self.tmp, '{"xhi": "hello"}')

    def _static(self):
        return {k: v for k, v in self.app.snippets.items() if not callable(v)}

    def test_backup_now_forces_backup_even_when_unchanged(self):
        before = len(bs.list_backups(self.app.backups_dir))
        created = self.app.backup_now()
        self.assertIsNotNone(created)
        self.assertEqual(len(bs.list_backups(self.app.backups_dir)), before + 1)

    def test_restore_backup_replaces_and_reloads(self):
        # Make a backup of the original, then change the live library.
        original_backup = self.app.backup_now()
        self.app.snippets["xhi"] = "changed"
        self.app.save_snippets(self.app.snippets)
        self.assertEqual(self.app.snippets["xhi"], "changed")

        ok, error = self.app.restore_backup(original_backup)
        self.assertTrue(ok, error)
        self.assertEqual(self.app.snippets["xhi"], "hello")

    def test_restore_rejects_invalid_backup(self):
        bad = os.path.join(self.app.backups_dir, "snippets-20990101-000000.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        ok, error = self.app.restore_backup(bad)
        self.assertFalse(ok)
        self.assertIn("inválido", error.lower())

    def test_export_library_writes_copy(self):
        dest = os.path.join(self.tmp, "exported.json")
        ok, error = self.app.export_library(dest)
        self.assertTrue(ok, error)
        with open(dest, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"xhi": "hello"})

    def test_import_replace(self):
        src = os.path.join(self.tmp, "incoming.json")
        with open(src, "w", encoding="utf-8") as handle:
            json.dump({"xbye": "goodbye"}, handle)
        ok, error = self.app.import_library(src, mode="replace")
        self.assertTrue(ok, error)
        self.assertIn("xbye", self.app.snippets)
        self.assertNotIn("xhi", self._static())

    def test_import_merge(self):
        src = os.path.join(self.tmp, "incoming.json")
        with open(src, "w", encoding="utf-8") as handle:
            json.dump({"xbye": "goodbye"}, handle)
        ok, error = self.app.import_library(src, mode="merge")
        self.assertTrue(ok, error)
        self.assertIn("xbye", self.app.snippets)
        self.assertIn("xhi", self._static())

    def test_import_rejects_non_object_json(self):
        src = os.path.join(self.tmp, "bad.json")
        with open(src, "w", encoding="utf-8") as handle:
            handle.write("[1, 2, 3]")
        ok, error = self.app.import_library(src)
        self.assertFalse(ok)

    def test_mirror_copies_on_save(self):
        mirror = os.path.join(self.tmp, "mirror")
        self.app.settings = {"mirror_dir": mirror}
        self.app.snippets["xhi"] = "mirrored"
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        mirrored = os.path.join(mirror, "snippets.json")
        self.assertTrue(os.path.exists(mirrored))
        with open(mirrored, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["xhi"], "mirrored")


class RecoverSnippetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_expander(self.tmp, '{"xhi": "hello"}')

    def test_corrupt_load_quarantines_and_restores_from_backup(self):
        # A good backup exists from startup/construction. Corrupt the live file.
        good = {"xhi": "hello"}
        garbage = '{"xhi": "hello"'  # truncated JSON
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write(garbage)

        recovered = self.app.recover_snippets_file("test corruption")

        # Restored data matches the backup, corrupt bytes preserved under quarantine.
        self.assertEqual(recovered, good)
        quarantined = [
            name for name in os.listdir(self.tmp)
            if name.startswith(bs.QUARANTINE_PREFIX)
        ]
        self.assertEqual(len(quarantined), 1)
        with open(os.path.join(self.tmp, quarantined[0]), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), garbage)
        # Live file was rewritten with the recovered good data (never with garbage).
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), good)

    def test_recovery_skips_corrupt_newest_backup_for_older_valid_one(self):
        # Simulate a corrupt backup ranked newest by mtime, with an older valid one.
        good = {"xhi": "hello"}
        for path in bs.list_backups(self.app.backups_dir):
            os.remove(path)
        old_valid = os.path.join(self.app.backups_dir, "snippets-20260101-000000.json")
        new_corrupt = os.path.join(self.app.backups_dir, "snippets-20260102-000000.json")
        with open(old_valid, "w", encoding="utf-8") as handle:
            json.dump(good, handle)
        with open(new_corrupt, "w", encoding="utf-8") as handle:
            handle.write("{ truncated")
        os.utime(old_valid, (1000, 1000))
        os.utime(new_corrupt, (2000, 2000))  # newest by mtime, but invalid
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write("{ also corrupt")

        recovered = self.app.recover_snippets_file("test corruption")
        self.assertEqual(recovered, good)

    def test_startup_backup_skipped_for_invalid_file(self):
        # A corrupt live file must not be copied into a fresh (newest) backup.
        for path in bs.list_backups(self.app.backups_dir):
            os.remove(path)
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write("{ corrupt")
        self.app.backup_on_startup()
        self.assertEqual(bs.list_backups(self.app.backups_dir), [])

    def test_corrupt_load_without_backup_falls_back_to_defaults(self):
        # Remove all backups so recovery must use defaults.
        for path in bs.list_backups(self.app.backups_dir):
            os.remove(path)
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write("not json at all")

        recovered = self.app.recover_snippets_file("test corruption")

        self.assertEqual(recovered, self.app.get_default_snippets())
        quarantined = [
            name for name in os.listdir(self.tmp)
            if name.startswith(bs.QUARANTINE_PREFIX)
        ]
        self.assertEqual(len(quarantined), 1)

    def test_load_snippets_recovers_on_corrupt_file(self):
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write("{ broken")
        merged = self.app.load_snippets()
        # Static "xhi" survived via backup restore; dynamic snippets merged on top.
        self.assertEqual(merged.get("xhi"), "hello")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.base_dir = os.path.join(self.tmp, "app")   # legacy exe-side location
        self.data_dir = os.path.join(self.tmp, "home")  # ~/.txt_xpander stand-in
        os.makedirs(self.base_dir)
        with open(os.path.join(self.base_dir, "snippets.json"), "w", encoding="utf-8") as handle:
            handle.write('{"xhi": "legacy value"}')
        self._saved_home = os.environ.get("TXT_XPANDER_HOME")
        os.environ["TXT_XPANDER_HOME"] = self.data_dir

    def tearDown(self):
        if self._saved_home is None:
            os.environ.pop("TXT_XPANDER_HOME", None)
        else:
            os.environ["TXT_XPANDER_HOME"] = self._saved_home

    def _construct(self):
        with mock.patch.object(tx, "get_runtime_base_dir", return_value=self.base_dir), \
                mock.patch.object(tx, "get_runtime_resource_dir", return_value=self.base_dir):
            return tx.TextExpander()

    def test_first_launch_migrates_legacy_into_data_dir(self):
        app = self._construct()
        self.assertEqual(app.data_dir, os.path.abspath(self.data_dir))
        with open(app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"xhi": "legacy value"})
        # Legacy file left untouched as an extra safety copy.
        legacy = os.path.join(self.base_dir, "snippets.json")
        with open(legacy, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"xhi": "legacy value"})
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "migrated-from.txt")))

    def test_migration_is_idempotent(self):
        self._construct()
        # Change the migrated copy; a second launch must not re-copy the legacy.
        migrated_path = os.path.join(self.data_dir, "snippets.json")
        with open(migrated_path, "w", encoding="utf-8") as handle:
            handle.write('{"xhi": "edited after migration"}')
        self._construct()
        with open(migrated_path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"xhi": "edited after migration"})


class NotificationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "notifications.json")

    def test_load_missing_returns_empty(self):
        self.assertEqual(runtime_support.load_notification_history(self.path), [])

    def test_roundtrip_and_limit(self):
        history = [{"time": "00:00:00", "title": "t", "message": str(i), "kind": "status"} for i in range(200)]
        runtime_support.save_notification_history(self.path, history, limit=120)
        loaded = runtime_support.load_notification_history(self.path, limit=120)
        self.assertEqual(len(loaded), 120)
        self.assertEqual(loaded[-1]["message"], "199")

    def test_invalid_file_returns_empty(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{ not a list")
        self.assertEqual(runtime_support.load_notification_history(self.path), [])

    def test_history_persists_across_construction(self):
        base = os.path.join(self.tmp, "app")
        os.makedirs(base)
        app = make_expander(base, '{"xhi": "hello"}')
        app.notification_history_file = os.path.join(base, "notifications.json")
        runtime_support.save_notification_history(
            app.notification_history_file,
            [{"time": "00:00:00", "title": "t", "message": "persisted", "kind": "status"}],
        )
        reloaded = runtime_support.load_notification_history(app.notification_history_file)
        self.assertEqual(reloaded[0]["message"], "persisted")


class LoggingConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.logger = logging.getLogger(runtime_support.LOGGER_NAME)
        self._saved_handlers = list(self.logger.handlers)
        self.logger.handlers = []

    def tearDown(self):
        for handler in list(self.logger.handlers):
            handler.close()
        self.logger.handlers = self._saved_handlers

    def test_configure_logging_writes_file(self):
        runtime_support.configure_logging(self.tmp)
        runtime_support.AppLogger().error("boom happened")
        for handler in self.logger.handlers:
            handler.flush()
        log_path = os.path.join(self.tmp, runtime_support.LOG_FILE_NAME)
        self.assertTrue(os.path.exists(log_path))
        with open(log_path, encoding="utf-8") as handle:
            self.assertIn("boom happened", handle.read())

    def test_configure_logging_is_idempotent(self):
        runtime_support.configure_logging(self.tmp)
        count = len(self.logger.handlers)
        runtime_support.configure_logging(self.tmp)
        self.assertEqual(len(self.logger.handlers), count)


if __name__ == "__main__":
    unittest.main()
