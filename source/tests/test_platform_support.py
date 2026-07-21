import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

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


class AutostartRoundTripTests(unittest.TestCase):
    """install/remove round-trip on each mocked OS, writing into a temp dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _redirect(self, system, filename):
        path = os.path.join(self.tmp, "autostart", filename)
        patches = [
            mock.patch.object(ps, "current_os", return_value=system),
            mock.patch.object(ps, "autostart_target_path", return_value=path),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return path

    def test_linux_round_trip(self):
        path = self._redirect("linux", "txt-xpander.desktop")
        created = ps.install_autostart("Txt Xpander", ["/usr/bin/python3", "/opt/txt_xpander.pyw"])
        self.assertEqual(created, path)
        self.assertTrue(ps.is_autostart_enabled("Txt Xpander"))
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("[Desktop Entry]", content)
        self.assertIn("Exec=/usr/bin/python3 /opt/txt_xpander.pyw", content)

        self.assertTrue(ps.remove_autostart("Txt Xpander"))
        self.assertFalse(ps.is_autostart_enabled("Txt Xpander"))
        self.assertFalse(ps.remove_autostart("Txt Xpander"))

    def test_macos_round_trip(self):
        path = self._redirect("darwin", "com.txt-xpander.plist")
        ps.install_autostart("Txt Xpander", ["/usr/bin/python3", "/opt/txt_xpander.pyw"])
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("<string>/usr/bin/python3</string>", content)
        self.assertIn("<string>/opt/txt_xpander.pyw</string>", content)
        self.assertIn("<key>RunAtLoad</key><true/>", content)

        self.assertTrue(ps.remove_autostart("Txt Xpander"))
        self.assertFalse(os.path.exists(path))

    def test_windows_round_trip_with_mocked_shortcut(self):
        path = self._redirect("windows", "Txt Xpander.lnk")

        def fake_run(argv, **kwargs):
            # Stand in for WScript.Shell: the real call writes the .lnk.
            with open(path, "wb") as handle:
                handle.write(b"L\x00\x00\x00")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(ps.subprocess, "run", side_effect=fake_run) as run:
            created = ps.install_autostart("Txt Xpander", [r"C:\App\Txt Xpander.exe"])

        self.assertEqual(created, path)
        script = run.call_args[0][0][-1]
        self.assertIn("WScript.Shell", script)
        self.assertIn(r"'C:\App\Txt Xpander.exe'", script)
        self.assertIn(r"$sc.WorkingDirectory = 'C:\App'", script)
        self.assertIn("$sc.Arguments = ''", script)
        self.assertTrue(ps.is_autostart_enabled("Txt Xpander"))
        self.assertTrue(ps.remove_autostart("Txt Xpander"))

    def test_windows_shortcut_from_source_works_in_the_app_dir(self):
        path = self._redirect("windows", "Txt Xpander.lnk")
        source_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        launcher = os.path.join(source_dir, "txt_xpander.pyw")

        def fake_run(argv, **kwargs):
            open(path, "wb").close()
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(ps.subprocess, "run", side_effect=fake_run) as run:
            ps.install_autostart("Txt Xpander", [r"C:\Py\pythonw.exe", launcher])

        script = run.call_args[0][0][-1]
        self.assertIn(f"$sc.WorkingDirectory = {ps._ps_quote(source_dir)}", script)
        self.assertIn(f"$sc.Arguments = {ps._ps_quote(launcher)}", script)

    def test_windows_failure_raises_instead_of_claiming_success(self):
        self._redirect("windows", "Txt Xpander.lnk")
        failure = mock.Mock(returncode=1, stdout="", stderr="access denied")
        with mock.patch.object(ps.subprocess, "run", return_value=failure):
            with self.assertRaises(OSError) as ctx:
                ps.install_autostart("Txt Xpander", [r"C:\App\Txt Xpander.exe"])
        self.assertIn("access denied", str(ctx.exception))
        self.assertFalse(ps.is_autostart_enabled("Txt Xpander"))

    def test_missing_entry_after_write_raises(self):
        self._redirect("windows", "Txt Xpander.lnk")
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(ps.subprocess, "run", return_value=ok):
            with self.assertRaises(OSError):
                ps.install_autostart("Txt Xpander", [r"C:\App\Txt Xpander.exe"])


class AutostartCommandTests(unittest.TestCase):
    def test_frozen_build_points_at_the_executable(self):
        with mock.patch.object(ps.sys, "frozen", True, create=True), \
                mock.patch.object(ps.sys, "executable", r"C:\App\Txt Xpander.exe"):
            self.assertEqual(ps.default_autostart_command(), [r"C:\App\Txt Xpander.exe"])

    def test_source_checkout_points_at_the_launcher(self):
        with mock.patch.object(ps.sys, "frozen", False, create=True):
            argv = ps.default_autostart_command()
        self.assertEqual(len(argv), 2)
        self.assertTrue(argv[1].endswith("txt_xpander.pyw"))
        self.assertTrue(os.path.exists(argv[1]))


if __name__ == "__main__":
    unittest.main()
