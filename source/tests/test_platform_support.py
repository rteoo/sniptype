import os
import shutil
import subprocess
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
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("[Desktop Entry]", content)
        self.assertIn("Exec=/usr/bin/python3 /opt/txt_xpander.pyw", content)

        self.assertTrue(ps.remove_autostart("Txt Xpander"))
        self.assertFalse(os.path.exists(path))
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
        self.assertTrue(os.path.exists(path))
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

        # Literal expectations: building these with _ps_quote would let a broken
        # quoter satisfy its own test.
        script = run.call_args[0][0][-1]
        self.assertIn(f"$sc.WorkingDirectory = '{source_dir}'", script)
        self.assertIn(f"$sc.Arguments = '{launcher}'", script)
        self.assertIn(r"$sc.TargetPath = 'C:\Py\pythonw.exe'", script)

    def test_windows_single_quote_in_path_is_escaped(self):
        """A quote in the path must not break out of the PowerShell string literal."""
        path = self._redirect("windows", "Txt Xpander.lnk")
        target = r"C:\Users\O'Brien\Txt Xpander.exe"

        def fake_run(argv, **kwargs):
            open(path, "wb").close()
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(ps.subprocess, "run", side_effect=fake_run) as run:
            ps.install_autostart("Txt Xpander", [target])

        script = run.call_args[0][0][-1]
        self.assertIn(r"$sc.TargetPath = 'C:\Users\O''Brien\Txt Xpander.exe'", script)
        # Doubling is the only escape: no lone quote may survive to end the literal.
        self.assertNotIn(r"'C:\Users\O'Brien", script)

    def test_windows_failure_raises_instead_of_claiming_success(self):
        path = self._redirect("windows", "Txt Xpander.lnk")
        failure = mock.Mock(returncode=1, stdout="", stderr="access denied")
        with mock.patch.object(ps.subprocess, "run", return_value=failure):
            with self.assertRaises(OSError) as ctx:
                ps.install_autostart("Txt Xpander", [r"C:\App\Txt Xpander.exe"])
        self.assertIn("access denied", str(ctx.exception))
        self.assertFalse(os.path.exists(path))

    def test_missing_entry_after_write_raises(self):
        self._redirect("windows", "Txt Xpander.lnk")
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(ps.subprocess, "run", return_value=ok):
            with self.assertRaises(OSError):
                ps.install_autostart("Txt Xpander", [r"C:\App\Txt Xpander.exe"])


class AutostartStateTests(unittest.TestCase):
    """absent/current/stale classification: presence alone must not mean enabled."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # Real files on disk to stand in for the installed exe/interpreter and
        # scripts: classification requires every argv element to still exist.
        self.installed = os.path.join(self.tmp, "current-app.exe")
        open(self.installed, "wb").close()
        self.command = [self.installed, os.path.join(self.tmp, "txt_xpander.pyw")]
        open(self.command[1], "wb").close()
        self.missing = [os.path.join(self.tmp, "deleted-dist", "app.exe")]
        self.other_install = [self.installed, os.path.join(self.tmp, "other", "txt_xpander.pyw")]
        os.makedirs(os.path.dirname(self.other_install[1]))
        open(self.other_install[1], "wb").close()

    def _redirect(self, system, filename):
        path = os.path.join(self.tmp, "autostart", filename)
        for patch in (
            mock.patch.object(ps, "current_os", return_value=system),
            mock.patch.object(ps, "autostart_target_path", return_value=path),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        return path

    def _write(self, system, argv):
        """Install an entry for ``argv`` with the Windows .lnk write mocked out."""
        if system != "windows":
            ps.install_autostart("Txt Xpander", argv)
            return

        path = ps.autostart_target_path("Txt Xpander")
        self._lnk = argv

        def fake_run(cmd, **kwargs):
            open(path, "wb").close()
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(ps.subprocess, "run", side_effect=fake_run):
            ps.install_autostart("Txt Xpander", argv)

    def _windows_read(self, argv):
        """Mock the WScript.Shell read-back for the argv the .lnk was written with."""
        target = argv[0]
        arguments = subprocess.list2cmdline(argv[1:]) if len(argv) > 1 else ""
        return mock.patch.object(
            ps.subprocess,
            "run",
            return_value=mock.Mock(returncode=0, stdout=f"{target}\n{arguments}\n", stderr=""),
        )

    # -- linux ------------------------------------------------------------
    def test_linux_absent(self):
        self._redirect("linux", "txt-xpander.desktop")
        self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_ABSENT)

    def test_linux_current(self):
        self._redirect("linux", "txt-xpander.desktop")
        self._write("linux", self.command)
        self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_CURRENT)

    def test_linux_stale_when_target_is_gone(self):
        self._redirect("linux", "txt-xpander.desktop")
        self._write("linux", self.missing)
        self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_STALE)

    def test_linux_stale_when_another_install_owns_it(self):
        self._redirect("linux", "txt-xpander.desktop")
        self._write("linux", self.other_install)
        self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_STALE)

    def test_stale_when_script_is_gone_even_if_interpreter_survives(self):
        """A surviving interpreter must not make a deleted checkout's entry live."""
        self._redirect("linux", "txt-xpander.desktop")
        dead = [self.installed, os.path.join(self.tmp, "deleted-checkout", "txt_xpander.pyw")]
        self._write("linux", dead)
        self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_STALE)
        # And it is the dead kind of stale — the one the app may repair.
        self.assertFalse(ps.autostart_target_exists(dead))

    # -- macOS ------------------------------------------------------------
    def test_macos_absent(self):
        self._redirect("darwin", "com.txt-xpander.plist")
        self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_ABSENT)

    def test_macos_current(self):
        self._redirect("darwin", "com.txt-xpander.plist")
        self._write("darwin", self.command)
        self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_CURRENT)

    def test_macos_stale_when_target_is_gone(self):
        self._redirect("darwin", "com.txt-xpander.plist")
        self._write("darwin", self.missing)
        self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_STALE)

    def test_macos_stale_when_another_install_owns_it(self):
        self._redirect("darwin", "com.txt-xpander.plist")
        self._write("darwin", self.other_install)
        self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_STALE)

    # -- windows ----------------------------------------------------------
    def test_windows_absent_reads_nothing(self):
        self._redirect("windows", "Txt Xpander.lnk")
        with mock.patch.object(ps.subprocess, "run") as run:
            self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_ABSENT)
        run.assert_not_called()

    def test_windows_current(self):
        self._redirect("windows", "Txt Xpander.lnk")
        self._write("windows", self.command)
        with self._windows_read(self.command) as run:
            self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_CURRENT)
        # One shortcut read, not one per caller.
        self.assertEqual(run.call_count, 1)

    def test_windows_current_ignores_case_and_separators(self):
        self._redirect("windows", "Txt Xpander.lnk")
        self._write("windows", self.command)
        shouty = [arg.upper().replace("\\", "/") for arg in self.command]
        # The subject here is the path *comparison*, not the on-disk check: an
        # uppercased temp path does not exist on a case-sensitive filesystem, so
        # off Windows the entry would classify as stale before ever being
        # compared. test_windows_current covers the unmocked chain.
        with self._windows_read(shouty), \
                mock.patch.object(ps, "autostart_target_exists", return_value=True):
            self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_CURRENT)

    def test_windows_stale_when_target_is_gone(self):
        self._redirect("windows", "Txt Xpander.lnk")
        self._write("windows", self.missing)
        with self._windows_read(self.missing):
            self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_STALE)

    def test_windows_stale_when_another_install_owns_it(self):
        self._redirect("windows", "Txt Xpander.lnk")
        self._write("windows", self.other_install)
        with self._windows_read(self.other_install):
            self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_STALE)

    def test_windows_unreadable_shortcut_is_stale_not_enabled(self):
        self._redirect("windows", "Txt Xpander.lnk")
        self._write("windows", self.command)
        failure = mock.Mock(returncode=1, stdout="", stderr="cannot open")
        with mock.patch.object(ps.subprocess, "run", return_value=failure):
            self.assertEqual(ps.autostart_state("Txt Xpander", self.command), ps.AUTOSTART_STALE)

    def test_is_enabled_is_no_longer_presence_only(self):
        """The old predicate trusted the path alone; a dead entry fooled it."""
        path = self._redirect("linux", "txt-xpander.desktop")
        self._write("linux", self.missing)
        with mock.patch.object(ps, "default_autostart_command", return_value=self.command):
            self.assertTrue(os.path.exists(path))
            self.assertFalse(ps.is_autostart_enabled("Txt Xpander"))

            self._write("linux", self.command)
            self.assertTrue(ps.is_autostart_enabled("Txt Xpander"))

    def test_windows_quoted_arguments_round_trip(self):
        """A .lnk stores args as one string; splitting it must recover the argv."""
        self._redirect("windows", "Txt Xpander.lnk")
        spaced = [self.installed, os.path.join(self.tmp, "with space", "txt_xpander.pyw")]
        os.makedirs(os.path.dirname(spaced[1]))
        open(spaced[1], "wb").close()
        self._write("windows", spaced)
        with self._windows_read(spaced):
            self.assertEqual(ps.autostart_state("Txt Xpander", spaced), ps.AUTOSTART_CURRENT)


class ClassifyAutostartTests(unittest.TestCase):
    """Direct unit coverage of the pure classifier the state resolver builds on.

    The round-trip tests above drive classify_autostart through
    autostart_state/install; these pin the argv-comparison rules themselves.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.exe = os.path.join(self.tmp, "app.exe")
        self.script = os.path.join(self.tmp, "txt_xpander.pyw")
        for path in (self.exe, self.script):
            open(path, "wb").close()
        self.command = [self.exe, self.script]

    def test_none_is_absent(self):
        self.assertEqual(ps.classify_autostart(None, self.command), ps.AUTOSTART_ABSENT)

    def test_identical_argv_is_current(self):
        self.assertEqual(
            ps.classify_autostart(list(self.command), self.command), ps.AUTOSTART_CURRENT
        )

    def test_differing_length_is_stale(self):
        # A single-element exe entry versus an interpreter+script expected command.
        self.assertEqual(ps.classify_autostart([self.exe], self.command), ps.AUTOSTART_STALE)

    def test_pythonw_versus_python_is_stale(self):
        pythonw = os.path.join(self.tmp, "pythonw.exe")
        open(pythonw, "wb").close()
        entry = [pythonw, self.script]
        expected = [self.exe, self.script]
        self.assertEqual(ps.classify_autostart(entry, expected), ps.AUTOSTART_STALE)

    def test_missing_target_is_stale_even_when_expected_matches(self):
        gone = [os.path.join(self.tmp, "nope", "app.exe"), self.script]
        # Even if the expected command were these exact strings, a path that does
        # not exist is dead at login and must classify stale, not current.
        self.assertEqual(ps.classify_autostart(gone, gone), ps.AUTOSTART_STALE)

    def test_relative_path_entry_is_stale(self):
        # A relative argv element cannot be confirmed on disk, so it is a dead
        # pointer regardless of what the expected command is.
        self.assertEqual(
            ps.classify_autostart(["app.exe", "txt_xpander.pyw"], self.command),
            ps.AUTOSTART_STALE,
        )

    def test_windows_comparison_ignores_case_and_separators(self):
        # Only meaningful under Windows path rules; force them and stub the
        # on-disk check, since the shouty variant will not exist on disk.
        shouty = [arg.upper().replace("\\", "/") for arg in self.command]
        with mock.patch.object(ps, "current_os", return_value="windows"), \
                mock.patch.object(ps, "autostart_target_exists", return_value=True):
            self.assertEqual(
                ps.classify_autostart(shouty, self.command), ps.AUTOSTART_CURRENT
            )

    def test_defaults_to_default_autostart_command_when_expected_is_none(self):
        with mock.patch.object(ps, "default_autostart_command", return_value=self.command):
            self.assertEqual(ps.classify_autostart(list(self.command)), ps.AUTOSTART_CURRENT)


class ReadShortcutFailureTests(unittest.TestCase):
    """The Windows .lnk reader is a PowerShell round-trip; garbage and failures
    must degrade to a safe classification, never a crash or a false 'enabled'."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lnk = os.path.join(self.tmp, "Txt Xpander.lnk")
        open(self.lnk, "wb").close()

    def _windows(self, run_result):
        return (
            mock.patch.object(ps, "current_os", return_value="windows"),
            mock.patch.object(ps, "autostart_target_path", return_value=self.lnk),
            mock.patch.object(ps.subprocess, "run", return_value=run_result),
        )

    def test_nonzero_exit_raises_oserror_with_detail(self):
        result = mock.Mock(returncode=1, stdout="", stderr="access is denied")
        patches = self._windows(result)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        with self.assertRaises(OSError) as ctx:
            ps.read_autostart_command("Txt Xpander")
        self.assertIn("access is denied", str(ctx.exception))

    def test_empty_output_yields_no_command(self):
        result = mock.Mock(returncode=0, stdout="\n\n", stderr="")
        patches = self._windows(result)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.assertEqual(ps.read_autostart_command("Txt Xpander"), [])

    def test_target_only_output_has_no_arguments(self):
        result = mock.Mock(returncode=0, stdout=r"C:\App\Txt Xpander.exe" + "\n", stderr="")
        patches = self._windows(result)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.assertEqual(ps.read_autostart_command("Txt Xpander"), [r"C:\App\Txt Xpander.exe"])

    def test_garbage_output_classifies_stale_not_enabled(self):
        # Empty stdout -> [] from the reader -> classify_autostart([]) is stale,
        # so the tray box shows unchecked instead of claiming a working entry.
        result = mock.Mock(returncode=0, stdout="", stderr="")
        patches = self._windows(result)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.assertEqual(ps.autostart_state("Txt Xpander"), ps.AUTOSTART_STALE)

    def test_nonzero_exit_is_caught_as_stale_by_autostart_state(self):
        result = mock.Mock(returncode=1, stdout="", stderr="cannot open")
        patches = self._windows(result)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.assertEqual(ps.autostart_state("Txt Xpander"), ps.AUTOSTART_STALE)


class TrayBackendTests(unittest.TestCase):
    """The win32 pin makes ``import pystray`` fail off Windows (issue #23)."""

    def test_windows_pins_win32(self):
        env = {}
        with mock.patch.object(ps, "current_os", return_value="windows"):
            self.assertEqual(ps.pin_tray_backend(env), "win32")
        self.assertEqual(env, {"PYSTRAY_BACKEND": "win32"})

    def test_windows_respects_an_explicit_override(self):
        env = {"PYSTRAY_BACKEND": "xorg"}
        with mock.patch.object(ps, "current_os", return_value="windows"):
            self.assertEqual(ps.pin_tray_backend(env), "xorg")
        self.assertEqual(env, {"PYSTRAY_BACKEND": "xorg"})

    def test_non_windows_leaves_the_backend_unset(self):
        for system in ("darwin", "linux"):
            with self.subTest(system=system):
                env = {}
                with mock.patch.object(ps, "current_os", return_value=system):
                    self.assertIsNone(ps.pin_tray_backend(env))
                self.assertEqual(env, {})

    def test_defaults_to_the_process_environment(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYSTRAY_BACKEND", None)
            with mock.patch.object(ps, "current_os", return_value="linux"):
                ps.pin_tray_backend()
            self.assertNotIn("PYSTRAY_BACKEND", os.environ)
            with mock.patch.object(ps, "current_os", return_value="windows"):
                ps.pin_tray_backend()
            self.assertEqual(os.environ.get("PYSTRAY_BACKEND"), "win32")


class LauncherPinTests(unittest.TestCase):
    """The pin must still be applied before ``import pystray`` in the launcher."""

    def test_launcher_pins_before_importing_pystray(self):
        launcher = os.path.join(os.path.dirname(__file__), "..", "txt_xpander.pyw")
        with open(launcher, encoding="utf-8") as handle:
            lines = [line.strip() for line in handle]
        pin = next((i for i, line in enumerate(lines) if line.startswith("platform_support.pin_tray_backend(")), None)
        pystray_import = next((i for i, line in enumerate(lines) if line == "import pystray"), None)
        self.assertIsNotNone(pin, "launcher no longer calls pin_tray_backend()")
        self.assertIsNotNone(pystray_import, "launcher no longer imports pystray")
        self.assertLess(pin, pystray_import)
        # No code line may set the variable itself: the platform guard inside
        # pin_tray_backend is what keeps the pin off macOS/Linux.
        code = [line for line in lines if not line.startswith("#")]
        self.assertEqual([line for line in code if "PYSTRAY_BACKEND" in line], [])


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


class TkMainThreadSeamTests(unittest.TestCase):
    """The macOS tray + Tk threading seam (issue #24)."""

    def test_only_macos_moves_tk_to_the_main_thread(self):
        self.assertEqual(ps.tk_runs_on_main_thread(), ps.IS_MAC)
        with mock.patch.object(ps, "IS_MAC", True):
            self.assertTrue(ps.tk_runs_on_main_thread())
        with mock.patch.object(ps, "IS_MAC", False):
            self.assertFalse(ps.tk_runs_on_main_thread())


class InsertionTimingTests(unittest.TestCase):
    """Per-OS paste/erase delays with settings.json overrides (issue #27)."""

    def test_every_platform_defines_every_key(self):
        for system in ("windows", "darwin", "linux"):
            timings = ps.default_insertion_timings(system)
            self.assertEqual(set(timings), set(ps.INSERTION_TIMING_KEYS), system)
            for key, value in timings.items():
                self.assertIsInstance(value, float, f"{system}.{key}")

    def test_windows_timings_are_the_historical_constants(self):
        # These are the values the paste path shipped with; a macOS retune must
        # not move them.
        self.assertEqual(
            {
                "clipboard_settle_delay": 0.05,
                "paste_restore_delay": 0.12,
                "erase_key_delay": 0.01,
            },
            ps.default_insertion_timings("windows"),
        )

    def test_macos_settles_faster_than_windows(self):
        # pbcopy/osascript exit only once NSPasteboard holds the payload, so the
        # Windows settle margin is latency macOS does not need.
        self.assertLess(
            ps.default_insertion_timings("darwin")["clipboard_settle_delay"],
            ps.default_insertion_timings("windows")["clipboard_settle_delay"],
        )

    def test_unknown_platform_falls_back_instead_of_raising(self):
        self.assertEqual(
            ps.default_insertion_timings("haiku"), ps.default_insertion_timings("linux")
        )

    def test_settings_override_a_single_key_and_leave_the_rest(self):
        timings = ps.insertion_timings({"paste_restore_delay": 0.3}, system="darwin")
        self.assertEqual(0.3, timings["paste_restore_delay"])
        self.assertEqual(
            ps.default_insertion_timings("darwin")["erase_key_delay"],
            timings["erase_key_delay"],
        )

    def test_unrelated_settings_keys_are_ignored(self):
        self.assertEqual(
            ps.default_insertion_timings("windows"),
            ps.insertion_timings({"terminator_mode": True, "bcb_timeout": 3}, system="windows"),
        )

    def test_bad_overrides_fall_back_to_the_platform_default(self):
        # A delay written in milliseconds, a negative, a string and a bool would
        # each freeze or break the listener thread if they reached it.
        for bad in (500, -0.1, "0.2", True, None, [0.2]):
            with self.subTest(bad=bad):
                timings = ps.insertion_timings({"erase_key_delay": bad}, system="windows")
                self.assertEqual(0.01, timings["erase_key_delay"])
                self.assertEqual(["erase_key_delay"], ps.invalid_timing_overrides({"erase_key_delay": bad}))

    def test_zero_is_a_valid_delay(self):
        timings = ps.insertion_timings({"erase_key_delay": 0}, system="windows")
        self.assertEqual(0.0, timings["erase_key_delay"])
        self.assertEqual([], ps.invalid_timing_overrides({"erase_key_delay": 0}))

    def test_no_settings_reports_no_invalid_overrides(self):
        self.assertEqual([], ps.invalid_timing_overrides(None))
        self.assertEqual([], ps.invalid_timing_overrides({}))


class TrayIconOptionTests(unittest.TestCase):
    """The pystray/NSApplication handoff on macOS (issue #24)."""

    def test_non_macos_adds_no_icon_options(self):
        """Windows must keep constructing the icon exactly as it always has."""
        with mock.patch.object(ps, "IS_MAC", False):
            self.assertEqual(ps.tray_icon_options(), {})

    def test_macos_hands_pystray_the_shared_nsapplication(self):
        appkit = mock.Mock()
        shared = object()
        appkit.NSApplication.sharedApplication.return_value = shared
        with mock.patch.object(ps, "IS_MAC", True), \
                mock.patch.dict(sys.modules, {"AppKit": appkit}):
            options = ps.tray_icon_options()
        # The singleton, not a fresh instance: Tk already created the one the
        # process is allowed to have, and pystray has to attach to that loop.
        self.assertEqual(options, {"darwin_nsapplication": shared})
        appkit.NSApplication.sharedApplication.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
