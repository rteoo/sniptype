@echo off
setlocal

REM ============================================================
REM Text Expander - Launch shortcut
REM ============================================================

REM Move to the directory where this script is located
cd /d "%~dp0"

echo.
echo ============================================================
echo   Starting Text Expander - checking environment...
echo ============================================================
echo.

REM ------------------------------------------------------------
REM Verify that txt_xpander.pyw exists
REM ------------------------------------------------------------
if not exist "txt_xpander.pyw" (
    echo [ERROR] File txt_xpander.pyw not found.
    echo Make sure this .bat file is in the same folder.
    echo.
    pause
    exit /b 1
)

REM ------------------------------------------------------------
REM Verify Python and required dependencies in one fast check
REM ------------------------------------------------------------
echo Checking Python and dependencies...
python -c "import importlib.util, sys; mods=('pynput','pystray','PIL','yfinance'); sys.exit(0 if all(importlib.util.find_spec(m) for m in mods) else 1)" >nul 2>&1
if %errorlevel% equ 9009 (
    echo [ERROR] Python not found.
    echo Install Python from: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Missing dependencies. Installing...
    echo.

    python -m pip install pynput pystray pillow yfinance --quiet

    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Failed to install dependencies.
        echo Run this manually:
        echo     pip install pynput pystray pillow yfinance
        echo.
        pause
        exit /b 1
    )

    echo [OK] Dependencies installed successfully.
    echo.
) else (
    echo Dependencies already installed.
    echo.
)

REM ------------------------------------------------------------
REM Silent launch with pythonw
REM ------------------------------------------------------------
echo Starting Text Expander silently...
start "" pythonw txt_xpander.pyw
exit /b 0
