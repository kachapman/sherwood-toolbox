#!/bin/bash
# System wrapper for the Sherwood Toolbox Debian package.
# Launches the pywebview desktop window instead of an external browser.
set -e

APP_DIR="/opt/sherwood-toolbox"
VENV_PY="$APP_DIR/.venv/bin/python"

# Seed bundled signatures into the user's config if they don't already have any.
USER_SIG="$HOME/.config/restoration_toolkit/signatures.json"
BUNDLE_SIG="$APP_DIR/config/signatures.json"
if [ ! -f "$USER_SIG" ] && [ -f "$BUNDLE_SIG" ]; then
    mkdir -p "$(dirname "$USER_SIG")"
    cp "$BUNDLE_SIG" "$USER_SIG"
fi

# Use a stable port that does not conflict with the Vanguard Adjusting Dashboard
# already listening on 8765 on this machine. Users can override with TOOLBOX_PORT.
export TOOLBOX_PORT="${TOOLBOX_PORT:-8766}"

exec "$VENV_PY" "$APP_DIR/run/desktop.py" "$@"
