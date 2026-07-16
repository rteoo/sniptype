import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import platform_support as ps


class OsDetectionTests(unittest.TestCase):
    def test_current_os_is_known(self):
        self.assertIn(ps.current_os(), {"windows", "darwin", "linux"})

    def test_flags_are_consistent(self):
        flags = [ps.IS_WINDOWS, ps.IS_MAC, ps.IS_LINUX]
        self.assertEqual(sum(1 for f in flags if f), 1)

    def test_paste_modifier_matches_platform(self):
        self.assertEqual(ps.paste_modifier_is_cmd(), ps.IS_MAC)


class LockfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "app.lock")

    def test_acquire_then_same_process_reacquires(self):
        self.assertTrue(ps.acquire_lockfile(self.path))
        # Same PID may re-acquire (idempotent for one process).
        self.assertTrue(ps.acquire_lockfile(self.path))

    def test_stale_lock_is_reclaimed(self):
        # A PID that is very unlikely to be running.
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("2147483000")
        self.assertTrue(ps.acquire_lockfile(self.path))
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(int(handle.read().strip()), os.getpid())

    def test_release_removes_own_lock(self):
        ps.acquire_lockfile(self.path)
        ps.release_lockfile(self.path)
        self.assertFalse(os.path.exists(self.path))


class AutostartTests(unittest.TestCase):
    def test_target_path_has_expected_suffix(self):
        path = ps.autostart_target_path("Txt Xpander")
        self.assertTrue(path.endswith(".lnk") or path.endswith(".plist") or path.endswith(".desktop"))

    def test_macos_plist_is_wellformed(self):
        plist = ps.macos_launch_agent("Txt Xpander", "/usr/bin/txt")
        self.assertIn("com.txt-xpander", plist)
        self.assertIn("<key>RunAtLoad</key><true/>", plist)
        self.assertIn("/usr/bin/txt", plist)

    def test_linux_desktop_entry_is_wellformed(self):
        entry = ps.linux_desktop_entry("Txt Xpander", "python txt_xpander.pyw")
        self.assertIn("[Desktop Entry]", entry)
        self.assertIn("Exec=python txt_xpander.pyw", entry)
        self.assertIn("Name=Txt Xpander", entry)


if __name__ == "__main__":
    unittest.main()
