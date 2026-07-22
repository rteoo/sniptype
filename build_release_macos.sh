#!/bin/bash
# Build the macOS release: a menu-bar-only "Txt Xpander.app" bundle.
#
# Mirrors build_release.bat where it applies (stage into a temp dist first, swap
# the shipping bundle only on success, keep the previous one until the swap is
# done) and drops the Windows-only steps: there is no Startup shortcut here (the
# tray toggle writes a LaunchAgent) and no dist-side snippets.json to preserve
# (user data lives in ~/.txt_xpander).
#
# Usage:
#   ./build_release_macos.sh
#   PYTHON=/path/to/venv/bin/python ./build_release_macos.sh
#   CODESIGN_IDENTITY="Developer ID Application: ..." ./build_release_macos.sh
#
# Re-signing invalidates the bundle's TCC grants (Input Monitoring /
# Accessibility) — see README, "Build on macOS".

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Txt Xpander"
BUNDLE_ID="com.txt-xpander"
DIST_ROOT="$REPO_DIR/dist"
TARGET_APP="$DIST_ROOT/$APP_NAME.app"
PREVIOUS_APP="$DIST_ROOT/$APP_NAME.app.previous"
PYTHON="${PYTHON:-python3}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script builds the macOS bundle and only runs on macOS." >&2
    exit 1
fi

if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "PyInstaller not found for '$PYTHON'." >&2
    echo "Install it with: $PYTHON -m pip install pyinstaller" >&2
    exit 1
fi

if pgrep -f "$APP_NAME.app/Contents/MacOS/" >/dev/null 2>&1; then
    echo "\"$APP_NAME\" is currently running."
    echo "Quit it from the menu bar before rebuilding so the bundle can be replaced safely."
    exit 1
fi

WORK_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/txt_xpander_build.XXXXXX")"
trap 'rm -rf "$WORK_ROOT"' EXIT

STAGING_ROOT="$WORK_ROOT/dist"
STAGED_APP="$STAGING_ROOT/$APP_NAME.app"

# --- App icon -------------------------------------------------------------
# The repo ships a 256x256 .ico (Windows). Build the .icns from it rather than
# committing a second copy of the same artwork; sizes above the source are left
# out instead of upscaled.
ICONSET="$WORK_ROOT/$APP_NAME.iconset"
ICNS="$WORK_ROOT/$APP_NAME.icns"
mkdir -p "$ICONSET"
for spec in "16:icon_16x16" "32:icon_16x16@2x" "32:icon_32x32" "64:icon_32x32@2x" \
            "128:icon_128x128" "256:icon_128x128@2x" "256:icon_256x256"; do
    size="${spec%%:*}"
    name="${spec##*:}"
    sips -s format png -z "$size" "$size" "$REPO_DIR/source/txt_xpander.ico" \
        --out "$ICONSET/$name.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$ICNS"

# --- Package --------------------------------------------------------------
echo "Packaging $APP_NAME.app ..."
"$PYTHON" -m PyInstaller --noconfirm --clean --windowed --onedir \
    --distpath "$STAGING_ROOT" \
    --workpath "$WORK_ROOT/build" \
    --specpath "$WORK_ROOT" \
    --name "$APP_NAME" \
    --icon "$ICNS" \
    --osx-bundle-identifier "$BUNDLE_ID" \
    --add-data "$REPO_DIR/source/snippets.json:." \
    --add-data "$REPO_DIR/source/dynamic_snippets.json:." \
    --add-data "$REPO_DIR/source/txt_xpander.ico:." \
    --hidden-import pystray._darwin \
    "$REPO_DIR/source/txt_xpander.pyw"

if [[ ! -d "$STAGED_APP" ]]; then
    echo "Packaging failed: no app bundle was produced. The existing dist was left unchanged." >&2
    exit 1
fi

# Menu-bar-only: no Dock icon, no app menu, no window on launch. PyInstaller has
# no CLI flag for extra Info.plist keys, so it is written after the build —
# which breaks the seal PyInstaller put on the bundle, hence the re-sign below.
plutil -replace LSUIElement -bool true "$STAGED_APP/Contents/Info.plist" 2>/dev/null \
    || plutil -insert LSUIElement -bool true "$STAGED_APP/Contents/Info.plist"

codesign --force --deep --sign "${CODESIGN_IDENTITY:--}" "$STAGED_APP" >/dev/null 2>&1 || {
    echo "Warning: codesign failed; the bundle may be rejected by Gatekeeper." >&2
}

# --- Promote --------------------------------------------------------------
mkdir -p "$DIST_ROOT"
rm -rf "$PREVIOUS_APP"
if [[ -d "$TARGET_APP" ]]; then
    mv "$TARGET_APP" "$PREVIOUS_APP"
fi

if ! ditto "$STAGED_APP" "$TARGET_APP"; then
    echo "Failed to promote the staged bundle into dist." >&2
    if [[ -d "$PREVIOUS_APP" ]]; then
        echo "Restoring the previous bundle..."
        rm -rf "$TARGET_APP"
        mv "$PREVIOUS_APP" "$TARGET_APP"
    fi
    exit 1
fi
rm -rf "$PREVIOUS_APP"

echo
echo "Packaging complete: $TARGET_APP"
echo "User data lives in ~/.txt_xpander (override with TXT_XPANDER_HOME)."
echo
echo "First launch: the bundle is unsigned/ad-hoc signed, so Gatekeeper blocks a"
echo "double-click — right-click the app and choose Open once, or run:"
echo "  xattr -dr com.apple.quarantine \"$TARGET_APP\""
echo "Then grant Input Monitoring and Accessibility in System Settings > Privacy"
echo "& Security. Those grants are tied to the bundle's identity: rebuilding or"
echo "re-signing invalidates them and macOS asks again."
