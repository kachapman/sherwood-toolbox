#!/usr/bin/env python3
"""Desktop window launcher for Sherwood Toolbox.

Runs the same Flask app as run/standalone.py but displays it in a native
desktop window via pywebview instead of opening the system browser. Generated
PDFs/ZIPs are saved through a native Save As dialog via the pywebview JS API.

Run: python3 run/desktop.py   (inside the project venv)
"""
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

# Make the project importable when run directly from the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from toolbox.app import create_app  # noqa: E402

HOST = os.environ.get("TOOLBOX_HOST", "127.0.0.1")
PORT = int(os.environ.get("TOOLBOX_PORT", "8765"))
APP_MARKER = "Sherwood Toolbox"
CHECK_HOST = "127.0.0.1"
WINDOW_TITLE = "Sherwood Toolbox"
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
WINDOW_MIN_WIDTH = 1024
WINDOW_MIN_HEIGHT = 700


def _port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((CHECK_HOST, port)) == 0


def _is_our_app(port):
    try:
        with urllib.request.urlopen("http://%s:%d/" % (CHECK_HOST, port), timeout=1.5) as r:
            return APP_MARKER in r.read(4096).decode("utf-8", "ignore")
    except Exception:
        return False


def _wait_for_server(port, timeout=10):
    """Return True once the server accepts connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.1)
    return False


def _serve_app(app, port):
    """Run the WSGI server in a daemon thread."""
    try:
        from waitress import serve
        serve(app, host=HOST, port=port, threads=8)
    except ImportError:
        app.run(host=HOST, port=port, debug=False, use_reloader=False, threaded=True)


class ToolboxApi:
    """Python API exposed to the frontend via pywebview's js bridge.

    Methods are called from JavaScript as window.pywebview.api.<name>(...).
    """

    def save_file(self, filename):
        """Show a native Save As dialog for a file in the upload directory.

        Returns a dict: {'ok': True, 'path': '...'} or {'ok': False, 'error': '...'}.
        """
        from gi.repository import Gtk
        from toolbox.config import Config

        upload_dir = Path(Config.UPLOAD_DIR)
        src = upload_dir / filename
        if not src.exists():
            return {"ok": False, "error": "File not found."}

        dialog = Gtk.FileChooserDialog(
            title="Save File",
            action=Gtk.FileChooserAction.SAVE,
            buttons=(
                Gtk.STOCK_CANCEL,
                Gtk.ResponseType.CANCEL,
                Gtk.STOCK_SAVE,
                Gtk.ResponseType.OK,
            ),
        )
        dialog.set_current_name(filename)
        dialog.set_do_overwrite_confirmation(True)

        response = dialog.run()
        try:
            if response == Gtk.ResponseType.OK:
                dest = Path(dialog.get_filename())
                shutil.copy2(str(src), str(dest))
                try:
                    src.unlink()
                except OSError:
                    pass
                return {"ok": True, "path": str(dest)}
            return {"ok": False, "error": "Save cancelled."}
        finally:
            dialog.destroy()

    def open_code_docs(self):
        """Open the Estimate Enhancer code-reference attachments folder."""
        import subprocess

        path = Path(__file__).resolve().parent.parent / "toolbox" / "tools" / "estimate_enhancer" / "attachments"
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["xdg-open", str(path)])
        return {"ok": True}

    def open_archive(self):
        """Open the folder that holds locally cached processed estimates."""
        import subprocess
        from toolbox.config import Config

        path = Path(Config.UPLOAD_DIR)
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["xdg-open", str(path)])
        return {"ok": True}


def main():
    import webview

    url = "http://%s:%d/" % (HOST, PORT)

    if _port_open(PORT):
        if _is_our_app(PORT):
            print("Sherwood Toolbox is already running at %s; opening its window." % url)
        else:
            print(
                "Port %d is in use by another program, so the toolbox was not started.\n"
                "Free that port, or set TOOLBOX_PORT to a different one and relaunch."
                % PORT
            )
            sys.exit(1)
    else:
        app = create_app()
        server_thread = threading.Thread(
            target=_serve_app, args=(app, PORT), daemon=True
        )
        server_thread.start()

        if not _wait_for_server(PORT):
            print("The toolbox server did not start in time.")
            sys.exit(1)

        print("Sherwood Toolbox running at %s  (close window to stop)" % url)

    window = webview.create_window(
        WINDOW_TITLE,
        url,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT),
        text_select=True,
        js_api=ToolboxApi(),
    )

    webview.start()


if __name__ == "__main__":
    main()
