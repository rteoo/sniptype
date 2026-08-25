@echo off
setlocal

REM ============================================================
REM Sniptype - Launch shortcut
REM ============================================================

REM Move to the directory where this script is located
cd /d "%~dp0"

echo.
echo ============================================================
echo   Starting Sniptype - checking environment...
echo ============================================================
echo.

REM ------------------------------------------------------------
REM Verify that sniptype.pyw exists
REM ------------------------------------------------------------
if not exist "sniptype.pyw" (
    echo [ERROR] File sniptype.pyw not found.
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
    echo [ERROR] Required dependencies are missing.
    echo Install them in your chosen environment, then run this launcher again:
    echo     python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
) else (
    echo Dependencies already installed.
    echo.
)

REM ------------------------------------------------------------
REM Silent launch with pythonw
REM ------------------------------------------------------------
echo Starting Sniptype silently...
start "" pythonw sniptype.pyw
exit /b 0
