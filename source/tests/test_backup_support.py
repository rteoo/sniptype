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


if __name__ == "__main__":
    unittest.main()
