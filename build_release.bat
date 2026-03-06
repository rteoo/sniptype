@echo off
setlocal
REM Build a new packaged release using PyInstaller
REM Run from repository root with PyInstaller installed.

python -m PyInstaller --noconfirm --clean --windowed --onedir --name "Txt Xpander" --icon source\txt_xpander.ico --add-data "source\snippets.json;." --add-data "source\txt_xpander.ico;." --hidden-import pystray._win32 source\txt_xpander.pyw
if errorlevel 1 (
    echo.
    echo Packaging failed.
    pause
    exit /b 1
)

set "TARGET_DIR=%~dp0dist\Txt Xpander"
set "TARGET_EXE=%TARGET_DIR%\Txt Xpander.exe"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\Txt Xpander.lnk"

echo.
set /p "ADD_STARTUP_SHORTCUT=Add a Startup shortcut for Txt Xpander? [Y/N]: "
if /I "%ADD_STARTUP_SHORTCUT%"=="Y" goto install_startup
if /I "%ADD_STARTUP_SHORTCUT%"=="YES" goto install_startup
goto finish

:install_startup
if not exist "%TARGET_EXE%" (
    echo Packaged executable not found: "%TARGET_EXE%"
    goto finish
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $shortcut = $ws.CreateShortcut('%SHORTCUT_PATH%'); $shortcut.TargetPath = '%TARGET_EXE%'; $shortcut.WorkingDirectory = '%TARGET_DIR%'; $shortcut.IconLocation = '%TARGET_EXE%,0'; $shortcut.Save()"
if errorlevel 1 (
    echo Failed to create the Startup shortcut.
) else (
    echo Startup shortcut created: "%SHORTCUT_PATH%"
)

:finish
echo Packaging complete. The release folder is in dist\"Txt Xpander"\
pause
endlocal
