@echo off
setlocal EnableExtensions
REM Build a new packaged release using PyInstaller.
REM The build always stages into a temporary dist folder first so an existing
REM packaged app stays intact unless the new build succeeds.

set "REPO_DIR=%~dp0"
if "%REPO_DIR:~-1%"=="\" set "REPO_DIR=%REPO_DIR:~0,-1%"
set "DIST_ROOT=%REPO_DIR%\dist"
set "TARGET_DIR=%DIST_ROOT%\Txt Xpander"
set "TARGET_EXE=%TARGET_DIR%\Txt Xpander.exe"
set "TARGET_SNIPPETS=%TARGET_DIR%\snippets.json"
set "STAGING_ROOT=%TEMP%\txt_xpander_staging_%RANDOM%%RANDOM%"
set "STAGING_DIR=%STAGING_ROOT%\Txt Xpander"
set "PREVIOUS_DIR=%DIST_ROOT%\Txt Xpander.previous"
set "WORK_ROOT=%TEMP%\txt_xpander_pyinstaller_%RANDOM%%RANDOM%"
set "WORK_DIR=%WORK_ROOT%\build"
set "SNIPPETS_BACKUP=%TEMP%\txt_xpander_snippets_backup_%RANDOM%%RANDOM%.json"
set "HAS_SNIPPETS_BACKUP=0"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\Txt Xpander.lnk"

tasklist /FI "IMAGENAME eq Txt Xpander.exe" 2>nul | find /I "Txt Xpander.exe" >nul
if not errorlevel 1 (
    echo "Txt Xpander.exe" is currently running.
    echo Close the packaged app before rebuilding dist so the update can replace the old folder safely.
    pause
    exit /b 1
)

if exist "%TARGET_DIR%" (
    echo Existing dist detected: "%TARGET_DIR%"
) else (
    echo No existing dist found. A fresh packaged release will be created.
)

REM User data now lives in %USERPROFILE%\.txt_xpander (migrated on first launch of
REM the new build), not in dist. The bundled snippets.json is only an anonymized
REM seed, so this script no longer syncs dist->source or restores data into dist.
REM A one-time safety copy of any pre-existing dist snippets is still kept, in case
REM this is the transition build and the app has not yet migrated its data.
if exist "%TARGET_SNIPPETS%" (
    echo Keeping a safety copy of the existing dist snippets.json...
    copy /Y "%TARGET_SNIPPETS%" "%SNIPPETS_BACKUP%" >nul
    if errorlevel 1 (
        echo Failed to back up the existing snippets.json file.
        pause
        exit /b 1
    )
    set "HAS_SNIPPETS_BACKUP=1"
) else (
    echo No existing dist snippets.json found.
)

if exist "%STAGING_ROOT%" (
    attrib -r "%STAGING_ROOT%\*.*" /s /d >nul 2>&1
    rmdir /s /q "%STAGING_ROOT%" >nul 2>&1
)

if exist "%PREVIOUS_DIR%" (
    attrib -r "%PREVIOUS_DIR%\*.*" /s /d >nul 2>&1
    rmdir /s /q "%PREVIOUS_DIR%" >nul 2>&1
)

set "VOICE_COLLECT_ARGS="
python -c "import transcribe_cpp, transcribe_cpp_native" >nul 2>&1
if not errorlevel 1 set "VOICE_COLLECT_ARGS=--collect-all transcribe_cpp --collect-all transcribe_cpp_native"

python -m PyInstaller --noconfirm --clean --windowed --onedir --distpath "%STAGING_ROOT%" --workpath "%WORK_DIR%" --specpath "%REPO_DIR%" --name "Txt Xpander" --icon "%REPO_DIR%\source\txt_xpander.ico" --add-data "%REPO_DIR%\source\snippets.json;." --add-data "%REPO_DIR%\source\dynamic_snippets.json;." --add-data "%REPO_DIR%\source\txt_xpander.ico;." --hidden-import pystray._win32 %VOICE_COLLECT_ARGS% --exclude-module torch --exclude-module torchvision --exclude-module torchaudio --exclude-module cv2 --exclude-module transformers --exclude-module onnxruntime --exclude-module scipy "%REPO_DIR%\source\txt_xpander.pyw"
if errorlevel 1 (
    echo.
    echo Packaging failed. The existing dist was left unchanged.
    goto cleanup_and_fail
)

if not exist "%STAGING_DIR%" (
    echo Packaging failed: staged dist was not created.
    goto cleanup_and_fail
)

REM No snippets are restored into the new dist: the app reads and writes user data
REM in %USERPROFILE%\.txt_xpander, and the bundled seed stays as-is.

if exist "%TARGET_DIR%" (
    echo Replacing the previous dist with the new packaged release...
    move "%TARGET_DIR%" "%PREVIOUS_DIR%" >nul
    if errorlevel 1 (
        echo Failed to move the existing dist out of the way.
        echo Close any running "Txt Xpander.exe" instance and try again.
        goto cleanup_and_fail
    )
)

if not exist "%DIST_ROOT%" mkdir "%DIST_ROOT%"
robocopy "%STAGING_DIR%" "%TARGET_DIR%" /e /j /nfl /ndl /njh /njs /r:0 /w:0 >nul
if errorlevel 8 (
    echo Failed to promote the new staged dist into place.
    if exist "%PREVIOUS_DIR%" (
        echo Attempting to restore previous dist...
        robocopy "%PREVIOUS_DIR%" "%TARGET_DIR%" /e /j /nfl /ndl /njh /njs /r:0 /w:0 >nul
        rmdir /s /q "%PREVIOUS_DIR%" >nul 2>&1
    )
    goto cleanup_and_fail
)

if exist "%PREVIOUS_DIR%" (
    attrib -r "%PREVIOUS_DIR%\*.*" /s /d >nul 2>&1
    rmdir /s /q "%PREVIOUS_DIR%" >nul 2>&1
)

if exist "%SHORTCUT_PATH%" (
    echo Startup shortcut already exists. Skipping shortcut prompt.
    goto finish
)

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
echo User data lives in "%USERPROFILE%\.txt_xpander" and is migrated on first launch.
if "%HAS_SNIPPETS_BACKUP%"=="1" echo Safety copy of the old dist snippets: "%SNIPPETS_BACKUP%"
goto cleanup_and_exit

:cleanup_and_fail
if exist "%STAGING_ROOT%" (
    attrib -r "%STAGING_ROOT%\*.*" /s /d >nul 2>&1
    rmdir /s /q "%STAGING_ROOT%" >nul 2>&1
)
if exist "%WORK_ROOT%" (
    attrib -r "%WORK_ROOT%\*.*" /s /d >nul 2>&1
    rmdir /s /q "%WORK_ROOT%" >nul 2>&1
)
if exist "%SNIPPETS_BACKUP%" (
    echo Preserved snippets backup: "%SNIPPETS_BACKUP%"
)
pause
exit /b 1

:cleanup_and_exit
if exist "%STAGING_ROOT%" (
    attrib -r "%STAGING_ROOT%\*.*" /s /d >nul 2>&1
    rmdir /s /q "%STAGING_ROOT%" >nul 2>&1
)
if exist "%WORK_ROOT%" (
    attrib -r "%WORK_ROOT%\*.*" /s /d >nul 2>&1
    rmdir /s /q "%WORK_ROOT%" >nul 2>&1
)
REM The snippets safety copy is intentionally left in place as an extra backup.
pause
endlocal
