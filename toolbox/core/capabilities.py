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
    probes = [("1.1.1.1", 53)]
    try:
        from .crm_search import CRM_BASE_URL
        from urllib.parse import urlparse
        host = urlparse(CRM_BASE_URL).hostname
        if host:
            probes.append((host, 443))
    except Exception:
        pass
    for host, port in probes:
        try:
            socket.setdefaulttimeout(timeout if port == 53 else 2.0)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            return True
        except OSError:
            continue
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
