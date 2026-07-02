"""Runtime capability detection, so tools can degrade gracefully instead of
erroring. Edit here to change how the app decides what is available.

Exposed to every template (via a context processor in app.py) as `caps`.
"""
import socket
from pathlib import Path

from ..config import Config
from . import auth as _auth
from ..core.hub import _load_web_limits


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


def detect(role=None):
    """Return a small dict consumed by templates and routes.
    Web limits prefer persisted Admin values (web_limits.json) with Config fallbacks.
    """
    web_limits = None
    if Config.WEB_MODE:
        persisted = _load_web_limits()
        web_limits = {
            "photo_max_count": int(persisted.get("photo_max_count", Config.WEB_PHOTO_MAX_COUNT)),
            "photo_max_mb_per_file": int(persisted.get("photo_max_mb_per_file", Config.WEB_PHOTO_MAX_MB_PER_FILE)),
            "enhancer_max_mb": int(persisted.get("enhancer_max_mb", Config.WEB_ENHANCER_MAX_MB)),
            "enhancer_max_photo_pages": int(persisted.get("enhancer_max_photo_pages", Config.WEB_ENHANCER_MAX_PHOTO_PAGES)),
        }
    r = role or "employee"  # desktop default
    return {
        "offline": Config.OFFLINE,
        "network": _network_reachable(),
        "crm_configured": _crm_configured(),
        "fork_present": Path(Config.FORK_PATH).exists(),
        "web_mode": Config.WEB_MODE,
        "web_limits": web_limits,
        "role": r,
        "is_employee": r == "employee",
        "is_customer": r == "customer",
    }
