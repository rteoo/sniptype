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


def make_expander(base_dir, snippets_content=None, resource_dir=None):
    """Construct a TextExpander rooted at base_dir without touching real data.

    Pins the data dir to base_dir via TXT_XPANDER_HOME so nothing is written to
    the real ~/.txt_xpander during tests. ``resource_dir`` separates the bundled
    resources from the data dir, which matters when a test writes a user override
    of a bundled file.
    """
    if snippets_content is not None:
        with open(os.path.join(base_dir, "snippets.json"), "w", encoding="utf-8") as handle:
            handle.write(snippets_content)
    previous_home = os.environ.get("TXT_XPANDER_HOME")
    os.environ["TXT_XPANDER_HOME"] = base_dir
    try:
        with mock.patch.object(tx, "get_runtime_base_dir", return_value=base_dir), \
                mock.patch.object(tx, "get_runtime_resource_dir", return_value=resource_dir or base_dir):
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


def write_bundled_registry(registry):
    """Write a bundled dynamic_snippets.json into a fresh dir and return it."""
    resource_dir = tempfile.mkdtemp()
    with open(os.path.join(resource_dir, "dynamic_snippets.json"), "w", encoding="utf-8") as handle:
        json.dump(registry, handle)
    return resource_dir


class ShadowedStaticSnippetTests(unittest.TestCase):
    """A static snippet named like a dynamic trigger must survive every save.

    The merged map holds the dynamic callable at that key, and callables are
    dropped on the way to disk — so before the fix the static value was silently
    deleted from snippets.json by the next save.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        resources = write_bundled_registry(
            {"xhi": {"provider": "datetime", "category": "datetime", "format": "%Y-%m-%d"}}
        )
        self.app = make_expander(
            self.tmp, '{"xhi": "meu texto importante", "xname": "Example User"}', resource_dir=resources
        )

    def _on_disk(self):
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            return json.load(handle)

    def test_collision_is_detected_at_load(self):
        self.assertTrue(callable(self.app.snippets["xhi"]))
        self.assertEqual({"xhi": "meu texto importante"}, self.app.shadowed_static_snippets)

    def test_save_of_the_merged_map_keeps_the_shadowed_static(self):
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        self.assertEqual(
            {"xhi": "meu texto importante", "xname": "Example User"}, self._on_disk()
        )

    def test_reload_then_save_keeps_the_shadowed_static(self):
        # The original loss needed a reload to re-merge the callable on top.
        self.app.reload_snippets_from_disk()
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        self.assertEqual("meu texto importante", self._on_disk()["xhi"])

    def test_merge_import_keeps_the_shadowed_static(self):
        src = os.path.join(self.tmp, "incoming.json")
        with open(src, "w", encoding="utf-8") as handle:
            json.dump({"xbye": "goodbye"}, handle)
        ok, error = self.app.import_library(src, mode="merge")
        self.assertTrue(ok, error)
        self.assertEqual("meu texto importante", self._on_disk()["xhi"])


class StaticEditorGuardTests(unittest.TestCase):
    """The static editor's free-text trigger box lets a user type a name a
    dynamic trigger owns. Two paths there must not lose the shadowed static.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        resources = write_bundled_registry(
            {"xhi": {"provider": "datetime", "category": "datetime", "format": "%Y-%m-%d"}}
        )
        self.app = make_expander(
            self.tmp, '{"xhi": "meu texto importante", "xname": "Example User"}', resource_dir=resources
        )

    def _on_disk(self):
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            return json.load(handle)

    # BUG 2: saving over a live dynamic trigger.
    def test_save_over_dynamic_records_shadow_but_keeps_the_callable(self):
        self.assertTrue(callable(self.app.snippets["xhi"]))
        self.app._store_static_snippet("xhi", "novo valor")
        # The callable stays in the merged map so the runtime index keeps
        # routing the trigger to the dynamic snippet (a restart would too).
        self.assertTrue(callable(self.app.snippets["xhi"]))
        self.assertEqual("novo valor", self.app.shadowed_static_snippets["xhi"])
        # The new static value still reaches disk...
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        self.assertEqual("novo valor", self._on_disk()["xhi"])
        # ...and the rebuilt index still routes the trigger to the callable.
        self.app.refresh_runtime_indexes()
        self.assertTrue(callable(self.app.snippets["xhi"]))

    def test_save_of_a_plain_static_goes_into_the_merged_map(self):
        self.app._store_static_snippet("xnew", "valor")
        self.assertEqual("valor", self.app.snippets["xnew"])
        self.assertNotIn("xnew", self.app.shadowed_static_snippets)

    # BUG 1: deleting a shadowed trigger from the static editor.
    def test_delete_of_a_dynamic_trigger_is_refused_and_saves_nothing(self):
        confirm = mock.Mock(return_value=True)
        with mock.patch.object(self.app, "save_snippets") as save:
            result = self.app._delete_static_snippet("xhi", confirm)
        self.assertEqual("dynamic", result)
        confirm.assert_not_called()
        save.assert_not_called()
        # The preserved static and the dynamic callable both survive intact.
        self.assertEqual("meu texto importante", self.app.shadowed_static_snippets["xhi"])
        self.assertTrue(callable(self.app.snippets["xhi"]))

    def test_delete_of_a_plain_static_still_works(self):
        confirm = mock.Mock(return_value=True)
        result = self.app._delete_static_snippet("xname", confirm)
        self.assertEqual("ok", result)
        confirm.assert_called_once()
        self.assertNotIn("xname", self.app.snippets)
        self.assertNotIn("xname", self._on_disk())

    def test_delete_asks_only_when_eligible(self):
        confirm = mock.Mock(return_value=False)
        self.assertEqual("cancelled", self.app._delete_static_snippet("xname", confirm))
        confirm.assert_called_once()
        self.assertIn("xname", self.app.snippets)


class DynamicToggleCollisionTests(unittest.TestCase):
    """Enabling a dynamic trigger over a static name needs the same guard as a rename."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        resources = write_bundled_registry(
            {
                "xhi": {
                    "provider": "datetime",
                    "category": "datetime",
                    "format": "%Y-%m-%d",
                    "enabled": False,
                },
                "xfree": {"provider": "datetime", "category": "datetime", "format": "%Y"},
            }
        )
        self.app = make_expander(self.tmp, '{"xhi": "meu texto importante"}', resource_dir=resources)

    def _override(self):
        if not os.path.exists(self.app.dynamic_registry_file):
            return {}
        with open(self.app.dynamic_registry_file, encoding="utf-8") as handle:
            return json.load(handle)

    def test_enabling_over_a_static_asks_and_a_refusal_changes_nothing(self):
        with mock.patch.object(tx.messagebox, "askyesno", return_value=False) as ask:
            self.assertFalse(self.app._toggle_registry_entry("xhi", True))
        ask.assert_called_once()
        self.assertEqual({}, self._override())
        self.assertEqual("meu texto importante", self.app.snippets["xhi"])

    def test_enabling_over_a_static_proceeds_when_confirmed(self):
        with mock.patch.object(tx.messagebox, "askyesno", return_value=True):
            self.assertTrue(self.app._toggle_registry_entry("xhi", True))
        self.assertTrue(self._override()["xhi"]["enabled"])
        self.assertTrue(callable(self.app.snippets["xhi"]))
        # The static value it now shadows is still preserved across a save.
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual("meu texto importante", json.load(handle)["xhi"])

    def test_enabling_without_a_collision_does_not_prompt(self):
        self.app._toggle_registry_entry("xfree", False)
        with mock.patch.object(tx.messagebox, "askyesno") as ask:
            self.assertTrue(self.app._toggle_registry_entry("xfree", True))
        ask.assert_not_called()

    def test_disabling_never_prompts(self):
        with mock.patch.object(tx.messagebox, "askyesno") as ask:
            self.assertTrue(self.app._toggle_registry_entry("xfree", False))
        ask.assert_not_called()

    def test_checkbox_snaps_back_when_the_toggle_is_refused(self):
        var = mock.Mock()
        var.get.return_value = True
        with mock.patch.object(self.app, "_toggle_registry_entry", return_value=False):
            self.app._on_registry_checkbox("xhi", var)
        var.set.assert_called_once_with(False)


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

    def test_mirror_failure_does_not_fail_save(self):
        # mirror_dir whose parent is a regular file: makedirs cannot create it.
        # Mirroring is best-effort redundancy and must never fail a persisted save.
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")
        self.app.settings = {"mirror_dir": os.path.join(blocker, "mirror")}
        self.app.snippets["xhi"] = "kept"
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        # The real library was written despite the mirror failure.
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["xhi"], "kept")

    def test_restore_rejects_wrong_root_type_backup(self):
        # Valid JSON, but a list where an object is required: must be refused, not
        # loaded as the live library.
        bad = os.path.join(self.app.backups_dir, "snippets-20990101-000000.json")
        os.makedirs(self.app.backups_dir, exist_ok=True)
        with open(bad, "w", encoding="utf-8") as handle:
            json.dump([1, 2, 3], handle)
        ok, error = self.app.restore_backup(bad)
        self.assertFalse(ok)
        self.assertIn("formato", error.lower())
        # Live library untouched.
        self.assertEqual(self.app.snippets["xhi"], "hello")


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

    def test_wrong_root_type_file_recovers_from_backup(self):
        # Valid JSON but the wrong shape (a list) is as unusable as broken JSON:
        # it must be quarantined and the good backup restored.
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write("[1, 2, 3]")
        merged = self.app.load_snippets()
        self.assertEqual(merged.get("xhi"), "hello")
        quarantined = [n for n in os.listdir(self.tmp) if n.startswith(bs.QUARANTINE_PREFIX)]
        self.assertEqual(len(quarantined), 1)

    def test_empty_file_recovers_from_backup(self):
        # A 0-byte snippets.json (an interrupted write) is not valid JSON; recovery
        # must quarantine it and restore the newest good backup.
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write("")
        recovered = self.app.recover_snippets_file("empty file")
        self.assertEqual(recovered, {"xhi": "hello"})
        quarantined = [n for n in os.listdir(self.tmp) if n.startswith(bs.QUARANTINE_PREFIX)]
        self.assertEqual(len(quarantined), 1)
        with open(os.path.join(self.tmp, quarantined[0]), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "")  # corrupt (empty) bytes preserved

    def test_save_does_not_back_up_a_corrupt_on_disk_file(self):
        # A corrupt live file must never enter the backup rotation, or it could
        # rank newest by mtime and defeat a later recovery.
        for path in bs.list_backups(self.app.backups_dir):
            os.remove(path)
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write("{ corrupt on disk")
        self.assertTrue(self.app.save_snippets({"xhi": "recovered"}))
        # No backup was created from the corrupt content...
        self.assertEqual(bs.list_backups(self.app.backups_dir), [])
        # ...and the new good data was written.
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"xhi": "recovered"})


class AtomicSaveTests(unittest.TestCase):
    """A failed save must never damage the prior on-disk library."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_expander(self.tmp, '{"xhi": "hello"}')

    def _leftover_temps(self):
        return [
            n for n in os.listdir(self.tmp)
            if n.startswith("snippets.json.") and n.endswith(".tmp")
        ]

    def test_failed_write_leaves_prior_file_intact(self):
        with mock.patch.object(tx, "write_json_atomic", side_effect=OSError("disk full")):
            self.assertFalse(self.app.save_snippets({"xhi": "changed"}))
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"xhi": "hello"})

    def test_non_serializable_value_fails_cleanly(self):
        # Exercises the real atomic write: json.dump raises mid-write on a set().
        # The original file must survive and no temp file may be left behind.
        self.assertFalse(self.app.save_snippets({"xhi": {1, 2, 3}}))
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"xhi": "hello"})
        self.assertEqual(self._leftover_temps(), [])


class SyncExportDirTests(unittest.TestCase):
    """The mobile-bundle export directory is never auto-created (unlike mirror).

    A typo'd sync_export_dir must not silently publish the full plaintext library
    somewhere the user never chose, so a missing directory is skipped -- while
    mirror_dir is created on demand. AGENTS.md 'Snippets File Safety' documents
    this asymmetry.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_expander(self.tmp, '{"xhi": "hello"}')

    def test_missing_sync_export_dir_is_not_created_but_mirror_is(self):
        sync_dir = os.path.join(self.tmp, "not_created_export")
        mirror_dir = os.path.join(self.tmp, "mirror")
        self.app.settings = {"sync_export_dir": sync_dir, "mirror_dir": mirror_dir}
        self.app.snippets["xhi"] = "published"
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        # sync_export_dir absent -> never created; bundle silently skipped.
        self.assertFalse(os.path.exists(sync_dir))
        # mirror_dir, by contrast, is created on demand.
        self.assertTrue(os.path.exists(os.path.join(mirror_dir, "snippets.json")))


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
