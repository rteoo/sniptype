import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app_paths


class DataDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = os.environ.get(app_paths.ENV_HOME)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(app_paths.ENV_HOME, None)
        else:
            os.environ[app_paths.ENV_HOME] = self._saved

    def test_env_override_wins(self):
        os.environ[app_paths.ENV_HOME] = self.tmp
        self.assertEqual(app_paths.get_data_dir(), os.path.abspath(self.tmp))

    def test_default_is_home_dotdir(self):
        os.environ.pop(app_paths.ENV_HOME, None)
        expected = os.path.join(os.path.expanduser("~"), app_paths.DIR_NAME)
        self.assertEqual(app_paths.get_data_dir(), expected)

    def test_layout_paths(self):
        self.assertEqual(app_paths.get_snippets_path(self.tmp), os.path.join(self.tmp, "snippets.json"))
        self.assertEqual(app_paths.get_settings_path(self.tmp), os.path.join(self.tmp, "settings.json"))
        self.assertEqual(app_paths.get_backups_dir(self.tmp), os.path.join(self.tmp, "backups"))
        self.assertEqual(app_paths.get_logs_dir(self.tmp), os.path.join(self.tmp, "logs"))

    def test_ensure_data_dir_creates(self):
        target = os.path.join(self.tmp, "nested", "data")
        app_paths.ensure_data_dir(target)
        self.assertTrue(os.path.isdir(target))


class MigrationHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.legacy_dir = os.path.join(self.tmp, "legacy")
        self.data_dir = os.path.join(self.tmp, "data")
        os.makedirs(self.legacy_dir)
        self.legacy = os.path.join(self.legacy_dir, "snippets.json")
        with open(self.legacy, "w", encoding="utf-8") as handle:
            handle.write('{"xhi": "hello"}')

    def test_needs_migration_true_when_dest_missing(self):
        self.assertTrue(app_paths.needs_migration(self.legacy, self.data_dir))

    def test_needs_migration_false_when_dest_exists(self):
        os.makedirs(self.data_dir)
        with open(app_paths.get_snippets_path(self.data_dir), "w", encoding="utf-8") as handle:
            handle.write("{}")
        self.assertFalse(app_paths.needs_migration(self.legacy, self.data_dir))

    def test_needs_migration_false_when_same_path(self):
        # data dir coincides with legacy location: never migrate onto itself.
        self.assertFalse(app_paths.needs_migration(self.legacy, self.legacy_dir))

    def test_migrate_copies_and_leaves_legacy(self):
        dest = app_paths.migrate_snippets(self.legacy, self.data_dir)
        self.assertTrue(os.path.exists(dest))
        with open(dest, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), '{"xhi": "hello"}')
        self.assertTrue(os.path.exists(self.legacy))  # legacy preserved
        breadcrumb = os.path.join(self.data_dir, app_paths.MIGRATION_BREADCRUMB)
        self.assertTrue(os.path.exists(breadcrumb))


if __name__ == "__main__":
    unittest.main()
