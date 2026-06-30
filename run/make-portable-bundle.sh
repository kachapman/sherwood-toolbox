#!/usr/bin/env bash
# Build a self-contained sherwood-toolbox.tar.gz to install on another machine.
# Contents: everything tracked in git (the toolbox + vendored restoration_common
# + shipped companies/logos) plus your saved signatures. CRM credentials are
# never included; the other user enters their own in-app.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="sherwood-toolbox"
OUT="$REPO/$PREFIX.tar.gz"
STAGE="$(mktemp -d)"

echo "Staging tracked files (git archive HEAD)..."
git -C "$REPO" archive --format=tar --prefix="$PREFIX/" HEAD | tar -x -C "$STAGE"

# Bundle signatures so signed documents work on the new machine. NOT crm.ini.
SIG="$HOME/.config/restoration_toolkit/signatures.json"
if [ -f "$SIG" ]; then
  mkdir -p "$STAGE/$PREFIX/config"
  cp "$SIG" "$STAGE/$PREFIX/config/signatures.json"
  echo "Included signatures.json (CRM credentials intentionally left out)."
else
  echo "No signatures.json found; the bundle ships defaults only."
fi

echo "Creating $OUT ..."
rm -f "$OUT"
tar -czf "$OUT" -C "$STAGE" "$PREFIX"
rm -rf "$STAGE"

echo
echo "Built: $OUT"
echo "On the other machine:"
echo "  tar -xzf $PREFIX.tar.gz"
echo "  cd $PREFIX && ./run/install-standalone.sh"
