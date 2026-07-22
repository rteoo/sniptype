import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backup_support as bs


class BackupSupportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.snippets = os.path.join(self.tmp, "snippets.json")
        self.backups = os.path.join(self.tmp, "backups")
        self._write(self.snippets, '{"xhi": "hello"}')

    def _write(self, path, content):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def _read(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_create_backup_writes_copy(self):
        dest = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000000")
        self.assertIsNotNone(dest)
        self.assertTrue(os.path.exists(dest))
        self.assertEqual(self._read(dest), '{"xhi": "hello"}')

    def test_create_backup_skips_when_source_missing(self):
        os.remove(self.snippets)
        self.assertIsNone(bs.create_backup(self.snippets, self.backups))

    def test_create_backup_skips_identical_content(self):
        first = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000000")
        self.assertIsNotNone(first)
        second = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000001")
        self.assertIsNone(second)
        self.assertEqual(len(bs.list_backups(self.backups)), 1)

    def test_create_backup_after_change(self):
        bs.create_backup(self.snippets, self.backups, timestamp="20260101-000000")
        self._write(self.snippets, '{"xhi": "changed"}')
        second = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000001")
        self.assertIsNotNone(second)
        self.assertEqual(len(bs.list_backups(self.backups)), 2)

    def test_same_timestamp_does_not_overwrite(self):
        self._write(self.snippets, '{"a": 1}')
        first = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000000")
        self._write(self.snippets, '{"a": 2}')
        second = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000000")
        self.assertNotEqual(first, second)
        self.assertEqual(len(bs.list_backups(self.backups)), 2)

    def test_prune_keeps_newest_n(self):
        os.makedirs(self.backups, exist_ok=True)
        for i in range(5):
            path = os.path.join(self.backups, f"snippets-2026010{i}-000000.json")
            self._write(path, str(i))
            os.utime(path, (1000 + i, 1000 + i))
        removed = bs.prune_backups(self.backups, keep=2)
        self.assertEqual(len(removed), 3)
        remaining = bs.list_backups(self.backups)
        self.assertEqual(len(remaining), 2)
        # Newest two (highest mtime) survive.
        self.assertTrue(all("20260103" in p or "20260104" in p for p in remaining))

    def test_quarantine_preserves_bytes(self):
        garbage = '{"xhi": "hello"'  # truncated / invalid JSON
        self._write(self.snippets, garbage)
        dest = bs.quarantine_corrupt_file(self.snippets, timestamp="20260101-000000")
        self.assertFalse(os.path.exists(self.snippets))
        self.assertTrue(os.path.basename(dest).startswith(bs.QUARANTINE_PREFIX))
        self.assertEqual(self._read(dest), garbage)

    def test_find_latest_backup_by_mtime(self):
        os.makedirs(self.backups, exist_ok=True)
        older = os.path.join(self.backups, "snippets-20260101-000000.json")
        newer = os.path.join(self.backups, "snippets-20260102-000000.json")
        self._write(older, "old")
        self._write(newer, "new")
        os.utime(older, (1000, 1000))
        os.utime(newer, (2000, 2000))
        self.assertEqual(bs.find_latest_backup(self.backups), newer)

    def test_find_latest_backup_none_when_empty(self):
        self.assertIsNone(bs.find_latest_backup(self.backups))

    def test_should_backup_on_startup(self):
        self.assertTrue(bs.should_backup_on_startup(self.backups))  # no backups yet
        path = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000000")
        fresh_now = os.path.getmtime(path) + 60
        self.assertFalse(bs.should_backup_on_startup(self.backups, now=fresh_now))
        stale_now = os.path.getmtime(path) + bs.STARTUP_BACKUP_MAX_AGE_SECONDS + 60
        self.assertTrue(bs.should_backup_on_startup(self.backups, now=stale_now))

    def test_should_backup_on_startup_boundary_is_inclusive(self):
        # Age exactly equal to the window still triggers a backup (>=, not >).
        path = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000000")
        exactly_now = os.path.getmtime(path) + bs.STARTUP_BACKUP_MAX_AGE_SECONDS
        self.assertTrue(bs.should_backup_on_startup(self.backups, now=exactly_now))

    # --- rotation boundary --------------------------------------------------

    def _seed_backups(self, count):
        """Create ``count`` distinct backups with strictly increasing mtimes."""
        os.makedirs(self.backups, exist_ok=True)
        for i in range(count):
            path = os.path.join(self.backups, f"snippets-2026-{i:04d}.json")
            self._write(path, str(i))
            os.utime(path, (1000 + i, 1000 + i))

    def test_prune_returns_empty_below_keep(self):
        self._seed_backups(3)
        self.assertEqual(bs.prune_backups(self.backups), [])  # default keep=30
        self.assertEqual(len(bs.list_backups(self.backups)), 3)

    def test_prune_at_exactly_default_keep_removes_nothing(self):
        self._seed_backups(bs.DEFAULT_KEEP)  # exactly 30
        removed = bs.prune_backups(self.backups)
        self.assertEqual(removed, [])
        self.assertEqual(len(bs.list_backups(self.backups)), bs.DEFAULT_KEEP)

    def test_prune_one_above_default_keep_removes_oldest_only(self):
        self._seed_backups(bs.DEFAULT_KEEP + 1)  # 31
        removed = bs.prune_backups(self.backups)
        self.assertEqual(len(removed), 1)
        self.assertEqual(len(bs.list_backups(self.backups)), bs.DEFAULT_KEEP)
        # The one removed is the oldest (lowest mtime, index 0000).
        self.assertIn("snippets-2026-0000.json", removed[0])

    # --- force + dedupe -----------------------------------------------------

    def test_force_backup_writes_even_when_identical(self):
        first = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000000")
        self.assertIsNotNone(first)
        # Same content: the non-forced path would skip. force=True must not.
        forced = bs.create_backup(
            self.snippets, self.backups, timestamp="20260101-000001", force=True
        )
        self.assertIsNotNone(forced)
        self.assertEqual(len(bs.list_backups(self.backups)), 2)

    def test_create_backup_dedupes_multiple_same_second_collisions(self):
        # Three saves in the same clock second, each with changed content.
        for i in range(3):
            self._write(self.snippets, f'{{"a": {i}}}')
            created = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000000")
            self.assertIsNotNone(created)
        names = sorted(os.path.basename(p) for p in bs.list_backups(self.backups))
        self.assertEqual(
            names,
            [
                "snippets-20260101-000000-1.json",
                "snippets-20260101-000000-2.json",
                "snippets-20260101-000000.json",
            ],
        )

    def test_quarantine_dedupes_on_name_collision(self):
        # Two corrupt files quarantined in the same second must both survive.
        self._write(self.snippets, "corrupt-one")
        first = bs.quarantine_corrupt_file(self.snippets, timestamp="20260101-000000")
        self._write(self.snippets, "corrupt-two")
        second = bs.quarantine_corrupt_file(self.snippets, timestamp="20260101-000000")
        self.assertNotEqual(first, second)
        self.assertEqual(self._read(first), "corrupt-one")
        self.assertEqual(self._read(second), "corrupt-two")

    # --- listing hygiene ----------------------------------------------------

    def test_list_backups_excludes_non_backup_files(self):
        os.makedirs(self.backups, exist_ok=True)
        real = os.path.join(self.backups, "snippets-20260101-000000.json")
        self._write(real, "{}")
        # None of these file names match the "snippets-*.json" glob: a quarantine
        # file (prefix "snippets." not "snippets-"), a wrong extension, an
        # unrelated .json.
        self._write(os.path.join(self.backups, "snippets.corrupt-20260101-000000.json"), "q")
        self._write(os.path.join(self.backups, "snippets-20260101-000000.txt"), "t")
        self._write(os.path.join(self.backups, "notes.json"), "{}")
        listed = bs.list_backups(self.backups)
        self.assertEqual([os.path.basename(p) for p in listed], ["snippets-20260101-000000.json"])

    # --- age + timestamp helpers -------------------------------------------

    def test_newest_backup_age_seconds(self):
        self.assertIsNone(bs.newest_backup_age_seconds(self.backups))  # none yet
        path = bs.create_backup(self.snippets, self.backups, timestamp="20260101-000000")
        os.utime(path, (5000, 5000))
        self.assertEqual(bs.newest_backup_age_seconds(self.backups, now=5060), 60)

    def test_format_timestamp_shape_is_deterministic(self):
        # Shape must be YYYYMMDD-HHMMSS regardless of the local timezone.
        self.assertRegex(bs.format_timestamp(0), r"^\d{8}-\d{6}$")
        self.assertRegex(bs.format_timestamp(), r"^\d{8}-\d{6}$")


if __name__ == "__main__":
    unittest.main()
