#!/usr/bin/env bash
#
# Build an AppImage for Sherwood Toolbox (Linux, x86_64).
#
# This creates a portable single-file application.
#
# Known problematic environments this script tries to be resilient against:
#   - Fedora 43+ (newer WebKitGTK, Python 3.12/3.13, stricter library linking)
#   - AMD GPUs (especially Ryzen 6000/7000/8000 series integrated graphics)
#     which often have issues with WebKitGTK hardware acceleration / dmabuf.
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

# --- Sanity checks for common build-time issues ---
echo "==> Checking build environment (Fedora 43 + AMD aware diagnostics)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "    Python version: $PYTHON_VERSION"

# === Pre-flight checks tuned for Fedora 43 + AMD hardware ===

MISSING_PACKAGES=()
WARNINGS=()

# Check for PyGObject + Gtk
if ! python3 -c "
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
print('PyGObject + Gtk 3.0: OK')
" 2>/dev/null; then
    echo "ERROR: PyGObject (python3-gobject) is not available."
    MISSING_PACKAGES+=("python3-gobject")
fi

# Check for WebKit2 (4.1 preferred on Fedora 43+)
if python3 -c '
import gi, sys
try:
    gi.require_version("WebKit2", "4.1")
    from gi.repository import WebKit2
    print("WebKit2 4.1: OK")
except Exception:
    try:
        gi.require_version("WebKit2", "4.0")
        from gi.repository import WebKit2
        print("WebKit2 4.0 (older): OK")
    except Exception:
        print("WebKit2 bindings NOT found")
        sys.exit(1)
' 2>/dev/null; then
    :
else
    MISSING_PACKAGES+=("webkit2gtk4.1 (or gir1.2-webkit2-4.1)")
fi

# AMD GPU / Ryzen iGPU detection (heuristic) - very common on Fedora 43 users
if command -v lspci >/dev/null 2>&1; then
    AMD_IGPU=$(lspci | grep -iE 'AMD.*(Radeon|Graphics|Ryzen)' | grep -iE '6[0-9]00|7[0-9]00|8[0-9]00|780M|880M|680M' || true)
    if [ -n "$AMD_IGPU" ]; then
        WARNINGS+=("AMD Ryzen iGPU detected in lspci. WebKitGTK hardware acceleration is likely to be problematic.")
    fi
fi

# Fedora-specific package name hints
if [ -f /etc/fedora-release ]; then
    FEDORA_VER=$(cat /etc/fedora-release | grep -oE '[0-9]+' | head -1)
    if [ "$FEDORA_VER" = "43" ] || [ "$FEDORA_VER" -ge 43 ]; then
        WARNINGS+=("Building on Fedora $FEDORA_VER. Make sure you have: sudo dnf install python3-gobject webkit2gtk4.1")
    fi
fi

if [ "${#MISSING_PACKAGES[@]}" -gt 0 ]; then
    echo ""
    echo "CRITICAL: The following packages are missing on this build machine:"
    for pkg in "${MISSING_PACKAGES[@]}"; do
        echo "  - $pkg"
    done
    echo ""
    echo "This is the most common reason AppImages for pywebview fail on Fedora 43."
    echo ""
    echo "On Fedora 43 (AMD or otherwise) run:"
    echo "    sudo dnf install python3-gobject webkit2gtk4.1"
    echo ""
    echo "On Ubuntu/Debian builders:"
    echo "    sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.1"
    echo ""
    echo "Aborting AppImage build."
    exit 1
fi

for w in "${WARNINGS[@]}"; do
    echo "    WARNING: $w"
done

echo "    PyGObject + WebKitGTK: OK"

# Clean previous build
rm -rf "$APPDIR"
mkdir -p "$APPDIR"
mkdir -p "$APPDIR/opt/sherwood-toolbox"

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

echo "==> Creating Python venv (with system site packages for gi/WebKitGTK)"
VENV="$APPDIR/opt/sherwood-toolbox/.venv"
python3 -m venv --system-site-packages "$VENV"

# Fedora 43 + AMD often requires the system gi + WebKitGTK bindings.
# If the build machine doesn't have them, the resulting AppImage will be broken.
if ! "$VENV/bin/python" -c "
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, WebKit2
print('PyGObject + WebKitGTK available in venv')
" 2>/dev/null; then
    echo ""
    echo "ERROR: PyGObject or WebKit2 not importable inside the venv."
    echo "This is almost always because the build machine is missing:"
    echo "    sudo dnf install python3-gobject webkit2gtk4.1"
    echo ""
    echo "On Ubuntu/Debian builders you would need:"
    echo "    sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.1"
    echo ""
    echo "Aborting AppImage build."
    exit 1
fi

echo "==> Installing Python packages"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$APPDIR/opt/sherwood-toolbox"
"$VENV/bin/pip" install --quiet --no-deps "$APPDIR/opt/sherwood-toolbox/vendor/restoration-common"

echo "==> Creating AppRun launcher with AMD + Fedora compatibility fixes"
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export APPDIR="$HERE"

# Use the bundled Python
export PATH="$HERE/opt/sherwood-toolbox/.venv/bin:$PATH"

# === Workarounds for Fedora 43 + AMD hardware (especially Ryzen iGPUs) ===
#
# Known problem area: Fedora 43 (and recent Fedora) + AMD Ryzen integrated graphics
# (Ryzen 6000/7000/8000 series with Radeon 680M/780M/880M etc.).
#
# Symptoms users report:
#   - Black/blank window when the app starts
#   - WebKitGTK crashes or hangs during rendering
#   - dmabuf / zero-copy rendering failures with newer Mesa
#
# The following are the currently recommended mitigations. They are set
# unconditionally because they are safe and only affect WebKitGTK inside
# this AppImage.
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export WEBKIT_DISABLE_DMABUF_RENDERER=1

# If you still get a completely black window on AMD, the user can try
# forcing software rendering by setting this before launch:
#   export LIBGL_ALWAYS_SOFTWARE=1
#   ./Sherwood_Toolbox-*.AppImage

# Wayland vs X11 issues are also common on AMD + recent Fedora.
# We prefer X11 for maximum compatibility with WebKitGTK.
export GDK_BACKEND=x11

# Some users on very new Mesa also benefit from this:
# export WEBKIT_FORCE_SANDBOX=0   # only as last resort

echo "    [AppRun] Applied Fedora 43 + AMD WebKitGTK workarounds"

# Some Fedora users also benefit from disabling sandbox (rarely needed)
# export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1

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
Categories=Office;
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
ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$APPIMAGE_NAME" 2>/dev/null || \
    ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$APPIMAGE_NAME"

echo ""
echo "==> Build complete!"
echo "Created: $REPO_ROOT/$APPIMAGE_NAME"
echo ""
echo "=== Runtime notes for Fedora 43 + AMD ==="
echo "If you get a black window or crash on AMD hardware, the AppRun already sets:"
echo "  WEBKIT_DISABLE_COMPOSITING_MODE=1"
echo "  WEBKIT_DISABLE_DMABUF_RENDERER=1"
echo ""
echo "Make sure you have the runtime libraries installed:"
echo "  sudo dnf install webkit2gtk4.1 python3-gobject"
echo ""
echo "To run:"
echo "  chmod +x $APPIMAGE_NAME"
echo "  ./$APPIMAGE_NAME"
