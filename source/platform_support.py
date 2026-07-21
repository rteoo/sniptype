"""Cross-platform seam for the OS-specific couplings.

Windows is the only fully-implemented backend today; this module centralizes the
platform decisions (paste modifier, single-instance strategy, autostart install)
so adding a macOS/Linux backend is additive and Windows behavior stays unchanged.

Pure helpers here are unit-tested; the clipboard backends live in
``clipboard_support`` (selected from :func:`current_os`) and the single-instance
mutex remains in ``txt_xpander`` (see README "Cross-platform status").
"""

import os
import shlex
import subprocess
import sys


APP_NAME = "Txt Xpander"


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

def autostart_target_path(app_name=APP_NAME):
    """Return the per-OS path where the autostart entry lives."""
    home = os.path.expanduser("~")
    system = current_os()
    if system == "windows":
        return os.path.join(
            os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming")),
            "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
            f"{app_name}.lnk",
        )
    if system == "darwin":
        return os.path.join(home, "Library", "LaunchAgents", f"com.{_slug(app_name)}.plist")
    return os.path.join(home, ".config", "autostart", f"{_slug(app_name)}.desktop")


def _slug(name):
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")


def macos_launch_agent(app_name, program_path, arguments=None):
    """Return the LaunchAgent plist XML for macOS autostart."""
    label = f"com.{_slug(app_name)}"
    argv = [program_path] + list(arguments or [])
    argv_xml = "".join(f"<string>{_xml_escape(arg)}</string>" for arg in argv)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"  <key>Label</key><string>{label}</string>\n"
        "  <key>ProgramArguments</key>\n"
        f"  <array>{argv_xml}</array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "</dict>\n"
        "</plist>\n"
    )


def _xml_escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
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


def default_autostart_command():
    """Return the argv that starts this app: packaged exe, or the source launcher.

    Mirrors ``build_release.bat``: the frozen build points straight at the
    executable, a source checkout at ``pythonw txt_xpander.pyw``.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]

    launcher = os.path.join(os.path.dirname(os.path.abspath(__file__)), "txt_xpander.pyw")
    interpreter = sys.executable
    if current_os() == "windows":
        windowless = os.path.join(os.path.dirname(interpreter), "pythonw.exe")
        if os.path.exists(windowless):
            interpreter = windowless
    return [interpreter, launcher]


def is_autostart_enabled(app_name=APP_NAME):
    """True when the per-OS autostart entry is present."""
    return os.path.exists(autostart_target_path(app_name))


def install_autostart(app_name=APP_NAME, command=None):
    """Create the per-user autostart entry and return its path.

    ``command`` is an argv list; it defaults to :func:`default_autostart_command`.
    Raises ``OSError`` when the entry could not be written — callers surface the
    failure instead of reporting a success that did not happen.
    """
    argv = list(command or default_autostart_command())
    if not argv:
        raise OSError("Comando de inicialização automática vazio.")

    path = autostart_target_path(app_name)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    system = current_os()
    if system == "windows":
        _write_windows_shortcut(path, argv)
    elif system == "darwin":
        _write_text_file(path, macos_launch_agent(app_name, argv[0], argv[1:]))
    else:
        _write_text_file(path, linux_desktop_entry(app_name, _join_command(argv)))

    if not os.path.exists(path):
        raise OSError(f"Entrada de inicialização automática não foi criada: {path}")
    return path


def remove_autostart(app_name=APP_NAME):
    """Remove the autostart entry. Return True if one was removed."""
    path = autostart_target_path(app_name)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


def _write_text_file(path, content):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _join_command(argv):
    if current_os() == "windows":
        return subprocess.list2cmdline(argv)
    return " ".join(shlex.quote(arg) for arg in argv)


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _write_windows_shortcut(path, argv):
    """Create a Startup .lnk via WScript.Shell (same COM object as build_release.bat)."""
    target = argv[0]
    arguments = subprocess.list2cmdline(argv[1:]) if len(argv) > 1 else ""
    # The app dir is where the last argument lives (the exe when frozen, the
    # .pyw launcher from source), not where the interpreter is installed.
    working_dir = os.path.dirname(argv[-1])
    if not os.path.isdir(working_dir):
        working_dir = os.path.dirname(target)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut({_ps_quote(path)}); "
        f"$sc.TargetPath = {_ps_quote(target)}; "
        f"$sc.Arguments = {_ps_quote(arguments)}; "
        f"$sc.WorkingDirectory = {_ps_quote(working_dir)}; "
        f"$sc.IconLocation = {_ps_quote(target + ',0')}; "
        "$sc.Save()"
    )
    # CREATE_NO_WINDOW: the app runs under pythonw, a console flash would be visible.
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        creationflags=0x08000000,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise OSError(f"Falha ao criar o atalho de inicialização: {detail}")
