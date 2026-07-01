#!/usr/bin/env bash
#
# Build an AppImage for Sherwood Toolbox (Linux, x86_64).
#
# This creates a portable single-file application.
#
# Requirements (on the build machine):
#   - bash, python3, python3-venv, rsync, wget (or curl)
#   - fuse (for appimagetool --appimage-extract-and-run)
#
# On the target Fedora machine you will likely need:
#   sudo dnf install webkit2gtk4.1 python3-gobject
#
# Usage:
#   ./run/build-appimage.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VERSION="$(grep -E '^version\s*=' "$REPO_ROOT/pyproject.toml" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
APPIMAGE_NAME="Sherwood_Toolbox-${VERSION}-x86_64.AppImage"
APPDIR="$REPO_ROOT/AppDir"

echo "==> Building Sherwood Toolbox AppImage v${VERSION}"

# Clean previous build
rm -rf "$APPDIR"
mkdir -p "$APPDIR"

echo "==> Copying application files"
rsync -a \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.deb' \
    --exclude='*.AppImage' \
    --exclude='AppDir' \
    "$REPO_ROOT/" "$APPDIR/opt/sherwood-toolbox/"

echo "==> Creating Python venv (with system site packages for gi/webkit)"
VENV="$APPDIR/opt/sherwood-toolbox/.venv"
python3 -m venv --system-site-packages "$VENV"

echo "==> Installing Python packages"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$APPDIR/opt/sherwood-toolbox"
"$VENV/bin/pip" install --quiet --no-deps "$APPDIR/opt/sherwood-toolbox/vendor/restoration-common"

echo "==> Creating AppRun launcher"
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export APPDIR="$HERE"

# Make sure we use the bundled Python
export PATH="$HERE/opt/sherwood-toolbox/.venv/bin:$PATH"

exec "$HERE/opt/sherwood-toolbox/.venv/bin/python" \
     "$HERE/opt/sherwood-toolbox/run/desktop.py" "$@"
EOF
chmod +x "$APPDIR/AppRun"

echo "==> Creating desktop entry"
cat > "$APPDIR/sherwood-toolbox.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Sherwood Toolbox
Comment=Local estimating tools, runs offline
Exec=sherwood-toolbox
Icon=sherwood-toolbox
Terminal=false
Categories=Office;Utility;
StartupNotify=true
EOF

echo "==> Installing icon"
ICON_SRC="$APPDIR/opt/sherwood-toolbox/toolbox/core/static/img/app_icon.png"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "$ICON_SRC" "$APPDIR/sherwood-toolbox.png"
cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/sherwood-toolbox.png"
ln -sf sherwood-toolbox.png "$APPDIR/.DirIcon"

echo "==> Downloading appimagetool if necessary"
APPIMAGETOOL="/tmp/appimagetool-x86_64.AppImage"
if [ ! -f "$APPIMAGETOOL" ]; then
    if command -v wget >/dev/null 2>&1; then
        wget -q --show-progress -O "$APPIMAGETOOL" \
            "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    else
        curl -L -o "$APPIMAGETOOL" \
            "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    fi
    chmod +x "$APPIMAGETOOL"
fi

echo "==> Building AppImage"
cd "$REPO_ROOT"
rm -f "$APPIMAGE_NAME"
"$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$APPIMAGE_NAME" 2>/dev/null || \
    "$APPIMAGETOOL" "$APPDIR" "$APPIMAGE_NAME"

echo ""
echo "==> Build complete!"
echo "Created: $REPO_ROOT/$APPIMAGE_NAME"
echo ""
echo "On Fedora 43 you may need to install runtime dependencies:"
echo "  sudo dnf install webkit2gtk4.1 python3-gobject"
echo ""
echo "Then run:"
echo "  chmod +x $APPIMAGE_NAME"
echo "  ./$APPIMAGE_NAME"
