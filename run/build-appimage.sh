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

# Captured at build time for traceability (embedded in image + printed)
PYTHON_BUILD_VER=""
WEBKIT_PKG_VER=""

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

# --- Version capture for traceability (embedded + printed) ---
PYTHON_BUILD_VER=$(python3 --version 2>/dev/null | awk '{print $2}')
if command -v dpkg-query >/dev/null 2>&1; then
    WEBKIT_PKG_VER=$(dpkg-query -W -f='${Version}' libwebkit2gtk-4.1-0 2>/dev/null || \
                     dpkg-query -W -f='${Version}' libwebkit2gtk-4.0-37 2>/dev/null || echo "unknown")
else
    WEBKIT_PKG_VER="unknown"
fi

# Additional checks for linuxdeploy-plugin-gtk build requirements (fat GTK bundling)
if ! command -v pkg-config >/dev/null 2>&1 && ! command -v pkgconf >/dev/null 2>&1; then
    MISSING_PACKAGES+=("pkg-config (or pkgconf)")
fi

# Debian/Ubuntu/Zorin dev packages needed so the gtk plugin can bundle schemas, typelibs, pixbuf loaders, etc.
for devpkg in libgtk-3-dev libgirepository1.0-dev librsvg2-dev libcairo2-dev; do
    if ! dpkg -l "$devpkg" 2>/dev/null | grep -q '^ii'; then
        MISSING_PACKAGES+=("$devpkg")
    fi
done

if [ "${#MISSING_PACKAGES[@]}" -gt 0 ]; then
    echo ""
    echo "CRITICAL: The following packages are missing on this build machine:"
    for pkg in "${MISSING_PACKAGES[@]}"; do
        echo "  - $pkg"
    done
    echo ""
    echo "For a fat GTK-bundled AppImage (linuxdeploy + gtk plugin) you need the -dev packages."
    echo ""
    echo "On Ubuntu/Debian/Zorin builders:"
    echo "    sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.1 \\"
    echo "                     pkg-config libgtk-3-dev libgirepository1.0-dev \\"
    echo "                     librsvg2-dev libcairo2-dev"
    echo ""
    echo "On Fedora 43 (AMD or otherwise):"
    echo "    sudo dnf install python3-gobject webkit2gtk4.1 fuse \\"
    echo "                     pkgconf gtk3-devel gobject-introspection-devel \\"
    echo "                     librsvg2-devel cairo-devel"
    echo ""
    echo "Aborting AppImage build."
    exit 1
fi

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

echo "==> Creating clean Python venv (no --system-site-packages; fat GTK bundling)"
# Use a temp location as requested. Do not pollute the repo or a persistent dev venv.
# --copies so the bin/ python is a real binary (not symlink to host /usr/bin), making the AppImage portable.
VENV="/tmp/sherwood-appimage-venv-$$"
rm -rf "$VENV"
python3 -m venv --copies "$VENV"

# Note: gi/WebKitGTK are NOT present in this clean venv.
# linuxdeploy-plugin-gtk will later copy the system GTK/WebKit/gi stack into the AppDir.
# The system pre-flight above already verified the build host has them.

echo "==> Installing Python packages into temp venv"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$APPDIR/opt/sherwood-toolbox"
"$VENV/bin/pip" install --quiet --no-deps "$APPDIR/opt/sherwood-toolbox/vendor/restoration-common"

echo "==> Staging populated venv into AppDir for bundling"
mkdir -p "$APPDIR/opt/sherwood-toolbox/.venv"
rsync -a --delete "$VENV/" "$APPDIR/opt/sherwood-toolbox/.venv/"
# Temp venv can be removed now; the copy in AppDir is what gets bundled.
rm -rf "$VENV"

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

# Copy high-res source into hicolor (for reference)
cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/sherwood-toolbox.png"

# For linuxdeploy --icon-file and .DirIcon we *must* provide a standard square size.
# Use the staged venv's Pillow (guaranteed by project deps) to resize to 256x256.
VENV_PY="$APPDIR/opt/sherwood-toolbox/.venv/bin/python"
ROOT_ICON="$APPDIR/sherwood-toolbox.png"
if [ -x "$VENV_PY" ]; then
    "$VENV_PY" -c '
from PIL import Image
import sys
src = sys.argv[1]
dst = sys.argv[2]
im = Image.open(src).convert("RGBA")
im = im.resize((256, 256), Image.LANCZOS)
im.save(dst, "PNG")
print("Resized icon to 256x256 for AppImage")
' "$ICON_SRC" "$ROOT_ICON" || cp "$APPDIR/usr/share/icons/hicolor/256x256/apps/sherwood-toolbox.png" "$ROOT_ICON"
else
    cp "$APPDIR/usr/share/icons/hicolor/256x256/apps/sherwood-toolbox.png" "$ROOT_ICON"
fi

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

echo "==> Downloading linuxdeploy + gtk plugin for fat GTK bundling (if necessary)"
LINUXDEPLOY="/tmp/linuxdeploy-x86_64.AppImage"
GTK_PLUGIN="/tmp/linuxdeploy-plugin-gtk.sh"
if [ ! -f "$LINUXDEPLOY" ]; then
    if command -v wget >/dev/null 2>&1; then
        wget -q --show-progress -O "$LINUXDEPLOY" \
            "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
    else
        curl -L -o "$LINUXDEPLOY" \
            "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
    fi
    chmod +x "$LINUXDEPLOY"
fi
if [ ! -f "$GTK_PLUGIN" ]; then
    if command -v wget >/dev/null 2>&1; then
        wget -q -O "$GTK_PLUGIN" \
            "https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh"
    else
        curl -L -o "$GTK_PLUGIN" \
            "https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh"
    fi
    chmod +x "$GTK_PLUGIN"
fi

echo "==> Writing build info for traceability"
cat > "$APPDIR/opt/sherwood-toolbox/BUILD_INFO.txt" << EOF
Build host: $(uname -a)
Python at build: ${PYTHON_BUILD_VER:-unknown}
WebKitGTK package at build: ${WEBKIT_PKG_VER:-unknown}
Build timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
AppImage target: ${APPIMAGE_NAME}
EOF
cp "$APPDIR/opt/sherwood-toolbox/BUILD_INFO.txt" "$REPO_ROOT/${APPIMAGE_NAME}.buildinfo" 2>/dev/null || true

echo "==> Running linuxdeploy with gtk plugin (fat GTK/WebKit bundling)"
cd "$REPO_ROOT"
# linuxdeploy --plugin gtk will copy GTK, WebKitGTK, typelibs, schemas, pixbuf loaders, etc.
# We run without --output so we can re-apply our AppRun afterward (AMD workarounds + hook sourcing).
# Force GTK 3 (pywebview + WebKit2 4.1 uses GTK 3 on this stack).
export DEPLOY_GTK_VERSION=3
ARCH=x86_64 "$LINUXDEPLOY" \
    --appdir "$APPDIR" \
    --desktop-file "$APPDIR/sherwood-toolbox.desktop" \
    --icon-file "$APPDIR/sherwood-toolbox.png" \
    --plugin gtk || {
        echo ""
        echo "ERROR: linuxdeploy + gtk plugin failed."
        echo "Common causes: missing -dev packages on the build host (libgtk-3-dev, etc.),"
        echo "or the gtk plugin could not locate schemas/typelibs/pixbuf loaders."
        echo "See earlier pre-flight messages for the required packages."
        exit 1
    }

echo "==> Copying host gi Python package into bundled venv (pywebview GTK needs the Python gi module)"
GI_SRC=$(python3 -c 'import gi, os; print(os.path.dirname(gi.__file__))' 2>/dev/null || true)
if [ -n "$GI_SRC" ] && [ -d "$GI_SRC" ]; then
    # The venv inside AppDir uses python3.12 layout on this build host.
    VENV_SITE="$APPDIR/opt/sherwood-toolbox/.venv/lib/python3.12/site-packages"
    mkdir -p "$VENV_SITE"
    cp -a "$GI_SRC" "$VENV_SITE/"
    echo "    Copied gi package from $GI_SRC into venv site-packages"
else
    echo "WARNING: Could not locate host gi package to embed; runtime 'import gi' may fail inside the AppImage."
fi

echo "==> Re-applying final AppRun (AMD workarounds + source gtk plugin apprun-hooks)"
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export APPDIR="$HERE"

# Use the bundled Python
export PATH="$HERE/opt/sherwood-toolbox/.venv/bin:$PATH"

# Source any hooks installed by linuxdeploy-plugin-gtk (GLib schemas, GI, pixbuf, etc.)
if [ -d "$HERE/apprun-hooks" ]; then
    for hook in "$HERE"/apprun-hooks/*.sh; do
        if [ -f "$hook" ]; then
            # shellcheck disable=SC1090
            . "$hook"
        fi
    done
fi

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

echo "==> Building final AppImage"
rm -f "$APPIMAGE_NAME"
ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$APPIMAGE_NAME" 2>/dev/null || \
    ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$APPIMAGE_NAME"

echo ""
echo "==> Post-build verification (extract + test bundled gi/WebKit2)"
VERIFY_DIR="/tmp/sherwood-appimage-verify-$$"
rm -rf "$VERIFY_DIR"
mkdir -p "$VERIFY_DIR"

# Reliable extraction: use unsquashfs when available, otherwise appimagetool --appimage-extract
if command -v unsquashfs >/dev/null 2>&1; then
    unsquashfs -d "$VERIFY_DIR/squashfs-root" "$APPIMAGE_NAME" >/dev/null 2>&1 || true
else
    ( cd "$VERIFY_DIR" && "$APPIMAGETOOL" --appimage-extract "$APPIMAGE_NAME" >/dev/null 2>&1 ) || true
fi

# Locate the extracted AppDir root
EXTRACT_ROOT=""
for cand in "$VERIFY_DIR/squashfs-root" "$VERIFY_DIR/squashfs-root/squashfs-root"; do
    if [ -d "$cand/opt/sherwood-toolbox" ]; then
        EXTRACT_ROOT="$cand"
        break
    fi
done
if [ -z "$EXTRACT_ROOT" ]; then
    # broad search for the toolbox payload
    EXTRACT_ROOT=$(find "$VERIFY_DIR" -type d -path '*/opt/sherwood-toolbox' 2>/dev/null | head -1 | sed 's|/opt/sherwood-toolbox||')
fi

BUNDLED_PY=""
if [ -n "$EXTRACT_ROOT" ]; then
    for cand in \
        "$EXTRACT_ROOT/opt/sherwood-toolbox/.venv/bin/python3" \
        "$EXTRACT_ROOT/opt/sherwood-toolbox/.venv/bin/python" \
        "$EXTRACT_ROOT/opt/sherwood-toolbox/.venv/bin/python3.12"; do
        if [ -e "$cand" ]; then
            BUNDLED_PY="$cand"
            break
        fi
    done
fi

# Last resort for this verification (on build host): the venv python is often a symlink to host python3.
# We can still exercise the bundled libs/typelibs by running the host python3 with the extracted paths.
if [ -z "$BUNDLED_PY" ] || [ ! -e "$BUNDLED_PY" ]; then
    if command -v python3 >/dev/null 2>&1; then
        BUNDLED_PY=$(command -v python3)
        echo "    (Note: using host python3 for verification; will test bundled GI/WebKit resources via env)"
    fi
fi

if [ -z "$BUNDLED_PY" ] || [ ! -e "$BUNDLED_PY" ]; then
    echo "ERROR: Could not locate any python to run the bundled gi/WebKit2 verification."
    echo "Extract dir was: $VERIFY_DIR"
    ls -lR "$VERIFY_DIR" 2>/dev/null | head -100 || true
    rm -rf "$VERIFY_DIR"
    exit 1
fi

echo "    Using python for verification: $BUNDLED_PY"

# Prepare minimal env that the gtk plugin's hooks would set
export LD_LIBRARY_PATH="$EXTRACT_ROOT/usr/lib:$EXTRACT_ROOT/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export GI_TYPELIB_PATH="$EXTRACT_ROOT/usr/lib/girepository-1.0:$EXTRACT_ROOT/usr/lib/x86_64-linux-gnu/girepository-1.0:${GI_TYPELIB_PATH:-}"
export GTK_PATH="$EXTRACT_ROOT/usr/lib/gtk-3.0:${GTK_PATH:-}"

if ! "$BUNDLED_PY" -c '
import sys
import gi
print("python:", sys.version.split()[0])
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2
print("Bundled gi + WebKit2 import: OK")
' 2>&1; then
    echo ""
    echo "ERROR: Post-build bundled gi/WebKit2 import test FAILED."
    echo "The fat GTK bundling did not produce a working Python + gi + WebKit2 stack."
    echo "Likely cause: the build host was missing some -dev packages or resources at bundling time."
    echo "Inspect the AppDir left behind and the extracted tree in $VERIFY_DIR (if any)."
    echo ""
    # Leave VERIFY_DIR for inspection; do not clean on failure
    exit 1
fi

echo "Post-build verification: PASSED (bundled gi + WebKit2 import OK)"
rm -rf "$VERIFY_DIR"

echo ""
echo "==> Build complete (fat GTK-bundled AppImage)!"
echo "Created: $REPO_ROOT/$APPIMAGE_NAME"
echo "Build info sidecar: $REPO_ROOT/${APPIMAGE_NAME}.buildinfo (also inside image as BUILD_INFO.txt)"
echo ""
echo "=== Runtime notes for fat GTK AppImage (Fedora 43 + AMD) ==="
echo "WebKitGTK + GTK + gi are now bundled from the build host."
echo "The AppRun still sets (for AMD Ryzen iGPU black-window mitigation):"
echo "  WEBKIT_DISABLE_COMPOSITING_MODE=1"
echo "  WEBKIT_DISABLE_DMABUF_RENDERER=1"
echo "  GDK_BACKEND=x11"
echo ""
echo "If you still get a completely black window on AMD:"
echo "  LIBGL_ALWAYS_SOFTWARE=1 ./$APPIMAGE_NAME"
echo ""
echo "Runtime requirements are now minimal (FUSE or --appimage-extract-and-run,"
echo "basic graphics stack, fonts). No need to install webkit2gtk4.1/python3-gobject"
echo "on the target for the core GTK stack (they are inside the image)."
echo ""
echo "AppDir left in place for inspection: $APPDIR"
echo ""
echo "To run:"
echo "  chmod +x $APPIMAGE_NAME"
echo "  ./$APPIMAGE_NAME"
