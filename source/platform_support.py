"""Cross-platform seam for the OS-specific couplings.

Windows is the only fully-implemented backend today; this module centralizes the
platform decisions (paste modifier, single-instance strategy, autostart install)
so adding a macOS/Linux backend is additive and Windows behavior stays unchanged.

Pure helpers here are unit-tested; the Win32 clipboard and mutex remain in
``runtime_support``/``txt_xpander`` for now (see README "Cross-platform status").
"""

import os
import sys


def current_os():
    """Return 'windows', 'darwin' (macOS) or 'linux'."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


IS_WINDOWS = current_os() == "windows"
IS_MAC = current_os() == "darwin"
IS_LINUX = current_os() == "linux"


def paste_modifier_is_cmd():
    """True where the paste shortcut is Cmd+V (macOS) rather than Ctrl+V."""
    return IS_MAC


# ---------------------------------------------------------------------------
# Single instance via PID lockfile (used where a native mutex is unavailable)
# ---------------------------------------------------------------------------

def _pid_is_running(pid):
    if pid <= 0:
        return False

    if IS_WINDOWS:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return False
    return True


def acquire_lockfile(path):
    """Acquire a PID lockfile. Return True if acquired, False if already held.

    A stale lock (whose PID is no longer running) is reclaimed. This is the
    portable single-instance strategy for non-Windows backends; Windows keeps its
    named mutex.
    """
    try:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    existing_pid = int((handle.read().strip() or "0"))
            except (ValueError, OSError):
                existing_pid = 0
            if existing_pid and existing_pid != os.getpid() and _pid_is_running(existing_pid):
                return False
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return True
    except OSError:
        # If we cannot manage the lockfile, do not block startup.
        return True


def release_lockfile(path):
    """Remove our lockfile if it still holds our PID. Best effort."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            if int((handle.read().strip() or "0")) != os.getpid():
                return
        os.remove(path)
    except (ValueError, OSError):
        pass


# ---------------------------------------------------------------------------
# Autostart install (per-OS location and payload)
# ---------------------------------------------------------------------------

def autostart_target_path(app_name="Txt Xpander"):
    """Return the per-OS path where the autostart entry lives."""
    home = os.path.expanduser("~")
    if IS_WINDOWS:
        return os.path.join(
            os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming")),
            "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
            f"{app_name}.lnk",
        )
    if IS_MAC:
        return os.path.join(home, "Library", "LaunchAgents", f"com.{_slug(app_name)}.plist")
    return os.path.join(home, ".config", "autostart", f"{_slug(app_name)}.desktop")


def _slug(name):
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")


def macos_launch_agent(app_name, program_path):
    """Return the LaunchAgent plist XML for macOS autostart."""
    label = f"com.{_slug(app_name)}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"  <key>Label</key><string>{label}</string>\n"
        "  <key>ProgramArguments</key>\n"
        f"  <array><string>{program_path}</string></array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "</dict>\n"
        "</plist>\n"
    )


def linux_desktop_entry(app_name, program_command):
    """Return the .desktop file content for Linux autostart."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={app_name}\n"
        f"Exec={program_command}\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
