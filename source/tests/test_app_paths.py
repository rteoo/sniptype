import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app_paths


class DataDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = os.environ.get(app_paths.ENV_HOME)
        self._saved_legacy = os.environ.get(app_paths.LEGACY_ENV_HOME)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(app_paths.ENV_HOME, None)
        else:
            os.environ[app_paths.ENV_HOME] = self._saved
        if self._saved_legacy is None:
            os.environ.pop(app_paths.LEGACY_ENV_HOME, None)
        else:
            os.environ[app_paths.LEGACY_ENV_HOME] = self._saved_legacy

    def test_env_override_wins(self):
        os.environ[app_paths.ENV_HOME] = self.tmp
        self.assertEqual(app_paths.get_data_dir(), os.path.abspath(self.tmp))

    def test_legacy_env_override_is_a_compatibility_fallback(self):
        os.environ.pop(app_paths.ENV_HOME, None)
        os.environ[app_paths.LEGACY_ENV_HOME] = self.tmp
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

    def test_needs_migration_false_when_legacy_missing(self):
        # No legacy file to migrate from: nothing to do, even if dest is absent.
        missing_legacy = os.path.join(self.tmp, "does-not-exist", "snippets.json")
        self.assertFalse(app_paths.needs_migration(missing_legacy, self.data_dir))

    def test_migrate_breadcrumb_records_legacy_absolute_path(self):
        app_paths.migrate_snippets(self.legacy, self.data_dir)
        breadcrumb = os.path.join(self.data_dir, app_paths.MIGRATION_BREADCRUMB)
        with open(breadcrumb, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), os.path.abspath(self.legacy) + "\n")

    def test_migrate_creates_data_dir_when_absent(self):
        # data_dir does not exist yet; migrate_snippets must create it.
        self.assertFalse(os.path.isdir(self.data_dir))
        dest = app_paths.migrate_snippets(self.legacy, self.data_dir)
        self.assertTrue(os.path.isdir(self.data_dir))
        self.assertEqual(dest, app_paths.get_snippets_path(self.data_dir))

    def test_default_legacy_directory_is_copied_without_being_modified(self):
        # The first Sniptype launch migrates the old per-user directory into
        # the canonical one, leaving the old tree as a recovery copy.
        home = os.path.join(self.tmp, "home")
        legacy_dir = os.path.join(home, app_paths.LEGACY_DIR_NAME)
        os.makedirs(legacy_dir)
        legacy_file = os.path.join(legacy_dir, "snippets.json")
        with open(legacy_file, "w", encoding="utf-8") as handle:
            handle.write('{"legacy": "value"}')

        with mock.patch.object(app_paths.os.path, "expanduser", return_value=home):
            with mock.patch.dict(os.environ, {}, clear=True):
                destination = app_paths.ensure_data_dir()

        self.assertEqual(destination, os.path.join(home, app_paths.DIR_NAME))
        with open(os.path.join(destination, "snippets.json"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), '{"legacy": "value"}')
        with open(legacy_file, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), '{"legacy": "value"}')
        self.assertTrue(os.path.exists(os.path.join(destination, app_paths.LEGACY_MIGRATION_BREADCRUMB)))


class EnvOverrideAdversarialTests(unittest.TestCase):
    """SNIPTYPE_HOME edge cases: empty, relative, tilde, unicode, a file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = os.environ.get(app_paths.ENV_HOME)
        self._saved_legacy = os.environ.get(app_paths.LEGACY_ENV_HOME)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(app_paths.ENV_HOME, None)
        else:
            os.environ[app_paths.ENV_HOME] = self._saved
        if self._saved_legacy is None:
            os.environ.pop(app_paths.LEGACY_ENV_HOME, None)
        else:
            os.environ[app_paths.LEGACY_ENV_HOME] = self._saved_legacy

    def test_empty_env_falls_back_to_default(self):
        # An empty string is falsy: the override must not win over the default.
        os.environ[app_paths.ENV_HOME] = ""
        expected = os.path.join(os.path.expanduser("~"), app_paths.DIR_NAME)
        self.assertEqual(app_paths.get_data_dir(), expected)

    def test_relative_env_is_made_absolute(self):
        os.environ[app_paths.ENV_HOME] = os.path.join("relative", "data")
        result = app_paths.get_data_dir()
        self.assertTrue(os.path.isabs(result))
        self.assertTrue(result.endswith(os.path.join("relative", "data")))

    def test_tilde_env_is_expanded(self):
        os.environ[app_paths.ENV_HOME] = os.path.join("~", "xp_home_test")
        result = app_paths.get_data_dir()
        self.assertNotIn("~", result)
        self.assertEqual(
            result, os.path.abspath(os.path.join(os.path.expanduser("~"), "xp_home_test"))
        )

    def test_unicode_and_spaces_env_is_usable(self):
        fancy = os.path.join(self.tmp, "Área de Trabalho ☂")
        os.environ[app_paths.ENV_HOME] = fancy
        created = app_paths.ensure_data_dir()
        self.assertTrue(os.path.isdir(created))
        # The resolved layout paths must be writable under the fancy directory.
        snippets = app_paths.get_snippets_path()
        with open(snippets, "w", encoding="utf-8") as handle:
            handle.write("{}")
        self.assertTrue(os.path.exists(snippets))

    def test_deep_nonexistent_env_is_created(self):
        deep = os.path.join(self.tmp, "a", "b", "c", "d")
        os.environ[app_paths.ENV_HOME] = deep
        app_paths.ensure_data_dir()
        self.assertTrue(os.path.isdir(deep))

    def test_ensure_data_dir_raises_when_target_is_a_file(self):
        # Pointed at a regular file, ensure_data_dir must fail loudly, not silently
        # treat the file as a directory.
        as_file = os.path.join(self.tmp, "iam-a-file")
        with open(as_file, "w", encoding="utf-8") as handle:
            handle.write("x")
        os.environ[app_paths.ENV_HOME] = as_file
        with self.assertRaises(OSError):
            app_paths.ensure_data_dir()


if __name__ == "__main__":
    unittest.main()
