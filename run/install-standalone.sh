#!/usr/bin/env bash
# Install the Sherwood Toolbox as a local offline app on this machine:
#   - a Python venv with the toolbox + the bundled restoration_common (no PyQt5)
#   - a GNOME .desktop launcher
#   - a `sherwood-toolbox` alias (zsh and/or bash)
#   - bundled signatures, if the tarball included them (CRM credentials are not
#     bundled; enter them in-app from the Photo Report or Documents CRM panel)
# Portable and idempotent: safe to re-run. One-time online step (pip install);
# the app runs offline afterward.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO/.venv"
VENV_PY="$VENV/bin/python"
RESTORATION="$REPO/vendor/restoration-common"
APPS_DIR="$HOME/.local/share/applications"
RT_CONFIG_DIR="$HOME/.config/restoration_toolkit"

echo "[0/6] Checking prerequisites"
command -v python3 >/dev/null 2>&1 || { echo "  ERROR: python3 not found. Install Python 3 first."; exit 1; }
python3 -c "import venv" 2>/dev/null || {
  echo "  ERROR: the Python venv module is missing."
  echo "  On Debian/Ubuntu/Zorin: sudo apt install python3-venv"
  exit 1
}

echo "[1/6] Creating venv at $VENV"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV_PY" -m pip install --quiet --upgrade pip

echo "[2/6] Installing the toolbox and its dependencies"
"$VENV_PY" -m pip install --quiet -e "$REPO"

echo "[3/6] Installing the bundled restoration_common (headless, no PyQt5)"
if [ -d "$RESTORATION" ]; then
  "$VENV_PY" -m pip install --quiet --no-deps -e "$RESTORATION"
else
  echo "  ERROR: $RESTORATION is missing; the bundle is incomplete."; exit 1
fi

echo "[4/6] Installing the GNOME launcher"
mkdir -p "$APPS_DIR"
sed -e "s#__VENV_PY__#$VENV_PY#g" -e "s#__REPO__#$REPO#g" \
  "$REPO/run/sherwood-toolbox.desktop" > "$APPS_DIR/sherwood-toolbox.desktop"
chmod +x "$APPS_DIR/sherwood-toolbox.desktop"
update-desktop-database "$APPS_DIR" 2>/dev/null || true

echo "[5/6] Adding the sherwood-toolbox alias (zsh and/or bash)"
ALIAS_LINE="alias sherwood-toolbox='$VENV_PY $REPO/run/standalone.py'"
changed=0
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [ -f "$rc" ] || continue
  if grep -q "alias sherwood-toolbox=" "$rc"; then
    echo "  alias already present in $rc"
  else
    printf '\n# Sherwood Toolbox local launcher\n%s\n' "$ALIAS_LINE" >> "$rc"
    echo "  added alias to $rc"; changed=1
  fi
done
[ "$changed" = 0 ] && [ ! -f "$HOME/.zshrc" ] && [ ! -f "$HOME/.bashrc" ] && \
  echo "  no ~/.zshrc or ~/.bashrc found; run directly with: $VENV_PY $REPO/run/standalone.py"

echo "[6/6] Installing bundled signatures (if provided; never overwriting)"
if [ -f "$REPO/config/signatures.json" ]; then
  mkdir -p "$RT_CONFIG_DIR"
  if [ -f "$RT_CONFIG_DIR/signatures.json" ]; then
    echo "  signatures.json already present; left as-is"
  else
    cp "$REPO/config/signatures.json" "$RT_CONFIG_DIR/signatures.json"
    echo "  installed signatures.json"
  fi
else
  echo "  no bundled signatures (skipping)"
fi

echo
echo "Done. Launch it with:"
echo "  - GNOME: open \"Sherwood Toolbox\" from the app grid"
echo "  - Terminal: sherwood-toolbox   (open a new shell first)"
echo "  - CRM: open Photo Report or Documents and enter your CRM credentials in the CRM panel."
