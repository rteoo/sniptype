@echo off
setlocal EnableExtensions
REM Build the Tauri manager window (ui\) and copy sniptype-manager.exe into the
REM folder given as the first argument (build_release.bat passes its staged dist).
REM Needs Node (npm) and the Rust toolchain with the MSVC build tools.

set "REPO_DIR=%~dp0"
if "%REPO_DIR:~-1%"=="\" set "REPO_DIR=%REPO_DIR:~0,-1%"
set "UI_DIR=%REPO_DIR%\ui"
set "MANAGER_EXE=%UI_DIR%\src-tauri\target\release\sniptype-manager.exe"
set "DEST_DIR=%~1"

if "%DEST_DIR%"=="" (
    echo Usage: build_manager.bat ^<destination folder^>
    exit /b 1
)
if not exist "%DEST_DIR%" (
    echo Destination folder not found: "%DEST_DIR%"
    exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
    echo npm was not found. Install Node.js to build the manager window.
    exit /b 1
)
if not exist "%USERPROFILE%\.cargo\bin\cargo.exe" (
    where cargo >nul 2>&1
    if errorlevel 1 (
        echo cargo was not found. Install the Rust toolchain to build the manager window.
        exit /b 1
    )
)
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

pushd "%UI_DIR%"
call npm ci --no-audit --no-fund
if errorlevel 1 goto fail
REM Cargo can keep a binary whose embedded frontend is stale when only ui\src
REM changed; touching main.rs makes it embed the fresh build.
copy /b "src-tauri\src\main.rs" +,, "src-tauri\src\main.rs" >nul
call npx tauri build --no-bundle
if errorlevel 1 goto fail
popd

if not exist "%MANAGER_EXE%" (
    echo The manager build finished without "%MANAGER_EXE%".
    exit /b 1
)
copy /Y "%MANAGER_EXE%" "%DEST_DIR%\" >nul
if errorlevel 1 (
    echo Failed to copy sniptype-manager.exe into "%DEST_DIR%".
    exit /b 1
)
echo Manager window built: "%DEST_DIR%\sniptype-manager.exe"
exit /b 0

:fail
popd
echo The manager window failed to build.
exit /b 1
