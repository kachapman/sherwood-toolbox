#!/usr/bin/env python3
"""Standalone local launcher. Serves the toolbox on 127.0.0.1 and opens the
default browser.

Runs online by default: online features (CRM lookup) work when there is a
network, and the app degrades on its own when there is not (capabilities
detects reachability). To force a fully offline session, set
TOOLBOX_OFFLINE=1 in the environment before launching.

Stable port: the app always uses a fixed port (8765 by default, or
TOOLBOX_PORT). This matters because each tool's browser state (for example the
Ice and Water Shield calculator's saved history) is stored per origin, which
includes the port. A changing port would orphan that data, so the launcher
never silently falls back to a random port: if the port is already serving this
app it just opens the browser to it, and if it is taken by something else it
stops with a clear message instead of starting on a different origin.

Run: python3 run/standalone.py   (inside the project venv)
"""
import os
import socket
import sys
import threading
import webbrowser
import urllib.request
from pathlib import Path

# Make the project importable when run directly from the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from toolbox.app import create_app  # noqa: E402

HOST = "127.0.0.1"
PORT = int(os.environ.get("TOOLBOX_PORT", "8765"))
APP_MARKER = "Sherwood Toolbox"


def _port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((HOST, port)) == 0


def _is_our_app(port):
    try:
        with urllib.request.urlopen("http://%s:%d/" % (HOST, port), timeout=1.5) as r:
            return APP_MARKER in r.read(4096).decode("utf-8", "ignore")
    except Exception:
        return False


def main():
    url = "http://%s:%d/" % (HOST, PORT)

    if _port_open(PORT):
        if _is_our_app(PORT):
            print("Sherwood Toolbox is already running at %s; opening it." % url)
            webbrowser.open(url)
            return
        print(
            "Port %d is in use by another program, so the toolbox was not started.\n"
            "Free that port, or set TOOLBOX_PORT to a different one and relaunch.\n"
            "Note: a different port starts with its own separate saved history."
            % PORT
        )
        sys.exit(1)

    app = create_app()
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print("Sherwood Toolbox running at %s  (Ctrl+C to stop)" % url)

    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT, threads=8)
    except ImportError:
        app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
