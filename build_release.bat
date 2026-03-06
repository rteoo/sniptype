@echo off
REM Build a new packaged release using PyInstaller
REM Run from repository root with PyInstaller installed.

python -m PyInstaller --noconfirm --clean --windowed --onedir --name "Txt Xpander" --icon source\txt_xpander.ico --add-data "source\snippets.json;." --add-data "source\txt_xpander.ico;." --hidden-import pystray._win32 source\txt_xpander.pyw
echo.
echo Packaging complete.  The release folder is in dist\"Txt Xpander"\
pause