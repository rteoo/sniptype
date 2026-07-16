import json
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backup_support as bs
import runtime_support
import txt_xpander as tx


def make_expander(base_dir, snippets_content=None):
    """Construct a TextExpander rooted at base_dir without touching real data."""
    if snippets_content is not None:
        with open(os.path.join(base_dir, "snippets.json"), "w", encoding="utf-8") as handle:
            handle.write(snippets_content)
    with mock.patch.object(tx, "get_runtime_base_dir", return_value=base_dir), \
            mock.patch.object(tx, "get_runtime_resource_dir", return_value=base_dir):
        return tx.TextExpander()


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
