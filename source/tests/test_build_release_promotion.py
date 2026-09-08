"""Failure-inject the Windows release promotion in disposable directories."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPOSITORY_ROOT / "build_release.bat"
TEMP_ROOT = Path(__file__).resolve().parent / "tmp"


@unittest.skipUnless(os.name == "nt", "Windows batch promotion requires cmd.exe")
class BuildReleasePromotionTests(unittest.TestCase):
    def setUp(self):
        TEMP_ROOT.mkdir(exist_ok=True)
        self.root = Path(
            tempfile.mkdtemp(prefix="build-release-promotion-", dir=TEMP_ROOT)
        ).resolve()
        self._assert_under_temp_root(self.root)
        self.addCleanup(self._cleanup_root)
        self._seed_tree()
        self._install_fake_robocopy()

    def _cleanup_root(self):
        self._assert_under_temp_root(self.root)
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def _assert_under_temp_root(path):
        temp_root = TEMP_ROOT.resolve()
        candidate = Path(path).resolve()
        if temp_root not in candidate.parents:
            raise AssertionError(f"temporary path escaped {temp_root}: {candidate}")

    def _seed_tree(self):
        old = self.root / "dist" / "Sniptype"
        staged = self.root / "staging" / "Sniptype"
        old.mkdir(parents=True)
        staged.mkdir(parents=True)
        (old / "Sniptype.exe").write_text("old executable", encoding="utf-8")
        (old / "old-only.txt").write_text("old file", encoding="utf-8")
        (staged / "Sniptype.exe").write_text("new executable", encoding="utf-8")
        (staged / "new-only.txt").write_text("new file", encoding="utf-8")

    def _install_fake_robocopy(self):
        tools = self.root / "tools"
        tools.mkdir()
        (tools / "robocopy.cmd").write_text(
            """@echo off
setlocal
if /I "%SNIPTYPE_TEST_ROBOCOPY_MODE%"=="fail-all" exit /b 8
if /I "%SNIPTYPE_TEST_ROBOCOPY_MODE%"=="fail-promotion" (
    if /I "%~1"=="%SNIPTYPE_TEST_STAGING_DIR%" (
        if not exist "%~2" mkdir "%~2" >nul 2>&1
        >"%~2\\stale-new-file.txt" echo stale
        exit /b 8
    )
)
python -c "import shutil,sys; shutil.copytree(sys.argv[1],sys.argv[2],dirs_exist_ok=True)" "%~1" "%~2"
if errorlevel 1 exit /b 8
exit /b 0
""",
            encoding="ascii",
        )

    def _promotion_wrapper(self):
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        start = source.index("\n:promote_staged_release") + 1
        end = source.index("\n:cleanup_and_fail", start)
        promotion_labels = source[start:end]
        wrapper = self.root / "promotion-wrapper.bat"
        wrapper_text = f"""@echo off
setlocal EnableExtensions
set "DIST_ROOT={self.root / 'dist'}"
set "TARGET_DIR=%DIST_ROOT%\\Sniptype"
set "TARGET_EXE=%TARGET_DIR%\\Sniptype.exe"
set "STAGING_ROOT={self.root / 'staging'}"
set "STAGING_DIR=%STAGING_ROOT%\\Sniptype"
set "PREVIOUS_DIR=%DIST_ROOT%\\Sniptype.previous"
call :promote_staged_release
exit /b %errorlevel%

{promotion_labels}"""
        wrapper.write_bytes(wrapper_text.replace("\n", "\r\n").encode("utf-8"))
        return wrapper

    def _run_promotion(self, mode):
        environment = os.environ.copy()
        staging = self.root / "staging" / "Sniptype"
        environment.update(
            {
                "SNIPTYPE_TEST_ROBOCOPY_MODE": mode,
                "SNIPTYPE_TEST_STAGING_DIR": str(staging),
                "PATH": f"{self.root / 'tools'};{environment['PATH']}",
            }
        )
        return subprocess.run(
            ["cmd.exe", "/d", "/c", str(self._promotion_wrapper())],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )

    def _run_full_script_with_leftover_previous(self):
        disposable_repo = self.root / "full-script-repo"
        disposable_repo.mkdir()
        script = disposable_repo / "build_release.bat"
        shutil.copyfile(BUILD_SCRIPT, script)
        previous = disposable_repo / "dist" / "Sniptype.previous"
        previous.mkdir(parents=True)
        (previous / "recovery-marker.txt").write_text("keep", encoding="utf-8")
        temp = self.root / "process-temp"
        temp.mkdir()
        environment = os.environ.copy()
        environment.update({"TEMP": str(temp), "TMP": str(temp)})
        return subprocess.run(
            ["cmd.exe", "/d", "/c", str(script)],
            cwd=disposable_repo,
            env=environment,
            input="\r\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        ), previous

    @staticmethod
    def _files(path):
        if not path.exists():
            return None
        return {
            child.relative_to(path).as_posix(): child.read_bytes()
            for child in path.rglob("*")
            if child.is_file()
        }

    def test_successful_promotion_removes_rollback_only_after_copy(self):
        result = self._run_promotion("success")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        target = self.root / "dist" / "Sniptype"
        self.assertEqual(
            {
                "Sniptype.exe": b"new executable",
                "new-only.txt": b"new file",
            },
            self._files(target),
        )
        self.assertIsNone(self._files(self.root / "dist" / "Sniptype.previous"))

    def test_missing_staged_executable_restores_exact_previous_tree(self):
        (self.root / "staging" / "Sniptype" / "Sniptype.exe").unlink()

        result = self._run_promotion("success")

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        expected_old = {
            "Sniptype.exe": b"old executable",
            "old-only.txt": b"old file",
        }
        self.assertEqual(expected_old, self._files(self.root / "dist" / "Sniptype"))
        self.assertEqual(expected_old, self._files(self.root / "dist" / "Sniptype.previous"))

    def test_failed_promotion_restores_exact_tree_and_keeps_rollback_copy(self):
        result = self._run_promotion("fail-promotion")

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        expected_old = {
            "Sniptype.exe": b"old executable",
            "old-only.txt": b"old file",
        }
        self.assertEqual(expected_old, self._files(self.root / "dist" / "Sniptype"))
        self.assertEqual(expected_old, self._files(self.root / "dist" / "Sniptype.previous"))
        self.assertFalse((self.root / "dist" / "Sniptype" / "stale-new-file.txt").exists())

    def test_failed_restore_keeps_rollback_recoverable_on_next_startup(self):
        result = self._run_promotion("fail-all")

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        expected_old = {
            "Sniptype.exe": b"old executable",
            "old-only.txt": b"old file",
        }
        self.assertIsNone(self._files(self.root / "dist" / "Sniptype"))
        self.assertEqual(expected_old, self._files(self.root / "dist" / "Sniptype.previous"))

    def test_first_install_failure_leaves_no_partial_package(self):
        shutil.rmtree(self.root / "dist" / "Sniptype")

        result = self._run_promotion("fail-promotion")

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIsNone(self._files(self.root / "dist" / "Sniptype"))
        self.assertIsNone(self._files(self.root / "dist" / "Sniptype.previous"))

    def test_full_script_refuses_leftover_previous_before_process_probe(self):
        result, previous = self._run_full_script_with_leftover_previous()

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("No files were deleted", result.stdout)
        self.assertNotIn("currently running", result.stdout.lower())
        self.assertEqual({"recovery-marker.txt": b"keep"}, self._files(previous))


if __name__ == "__main__":
    unittest.main()
