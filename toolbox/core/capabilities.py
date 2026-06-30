"""Runtime capability detection, so tools can degrade gracefully instead of
erroring. Edit here to change how the app decides what is available.

Exposed to every template (via a context processor in app.py) as `caps`.
"""
import socket
from pathlib import Path

from ..config import Config


def _network_reachable(timeout=0.6):
    if Config.OFFLINE:
        return False
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("1.1.1.1", 53))
        return True
    except OSError:
        return False


def _crm_configured():
    # restoration_common reads creds from ~/.config/photo_report_generator/crm.ini
    return (Path.home() / ".config" / "photo_report_generator" / "crm.ini").exists()


def detect():
    """Return a small dict consumed by templates and routes."""
    return {
        "offline": Config.OFFLINE,
        "network": _network_reachable(),
        "crm_configured": _crm_configured(),
        "fork_present": Path(Config.FORK_PATH).exists(),
    }
