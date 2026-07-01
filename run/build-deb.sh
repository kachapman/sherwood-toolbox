#!/usr/bin/env bash
# Build the sherwood-toolbox .deb from the current project tree.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(grep -E '^version\s*=' "$REPO/pyproject.toml" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
ARCH="amd64"
PKG="sherwood-toolbox"
DEB="${PKG}_${VERSION}_${ARCH}.deb"
OUT="$REPO/$DEB"
STAGE="$(mktemp -d)"

mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/opt/$PKG"
mkdir -p "$STAGE/usr/bin"
mkdir -p "$STAGE/usr/share/applications"
mkdir -p "$STAGE/usr/share/pixmaps"

# Debian control scripts.
cp "$REPO/debian/control" "$STAGE/DEBIAN/control"
cp "$REPO/debian/postinst" "$STAGE/DEBIAN/postinst"
cp "$REPO/debian/prerm" "$STAGE/DEBIAN/prerm"
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"

# Application source (exclude venv/git/build artifacts).
rsync -a \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.deb' \
  "$REPO/" "$STAGE/opt/$PKG/"

# Launcher wrapper.
cp "$REPO/run/sherwood-toolbox-wrapper.sh" "$STAGE/usr/bin/sherwood-toolbox"
chmod +x "$STAGE/usr/bin/sherwood-toolbox"

# Desktop entry and icon (use the debian-ready version with absolute paths).
cp "$REPO/debian/sherwood-toolbox.desktop" "$STAGE/usr/share/applications/sherwood-toolbox.desktop"
cp "$REPO/toolbox/core/static/img/app_icon.png" "$STAGE/usr/share/pixmaps/sherwood-toolbox.png"

# Build the package.
dpkg-deb --build "$STAGE" "$OUT"
rm -rf "$STAGE"

echo "Built: $OUT"
