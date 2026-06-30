#!/usr/bin/env python3
"""CRM credential storage (unified location with legacy fallbacks)."""

import configparser
from pathlib import Path

from .paths import (
    UNIFIED_CRM_DIR,
    UNIFIED_CRM_PATH,
    OLD_BANEY_CRM_PATH,
    OLD_VANGUARD_CRM_PATH,
)


class NeedsCredentialsError(RuntimeError):
    """Raised when no usable saved credentials are available."""


def _read_crm_ini(path: Path) -> tuple:
    cfg = configparser.ConfigParser()
    if not path.exists():
        raise NeedsCredentialsError("No saved credentials found.")
    cfg.read(path)
    if "crm" not in cfg:
        raise NeedsCredentialsError("No [crm] section in credentials file.")
    username = cfg["crm"].get("username", "").strip()
    password = cfg["crm"].get("password", "").strip()
    if not username or not password:
        raise NeedsCredentialsError("Saved credentials are incomplete.")
    return (username, password)


def load_crm_credentials() -> tuple:
    """Return (username, password) from the unified file, then legacy files."""
    for path in (UNIFIED_CRM_PATH, OLD_BANEY_CRM_PATH, OLD_VANGUARD_CRM_PATH):
        try:
            return _read_crm_ini(path)
        except NeedsCredentialsError:
            continue
    raise NeedsCredentialsError("No saved credentials found.")


def save_crm_credentials(username: str, password: str) -> None:
    UNIFIED_CRM_DIR.mkdir(parents=True, exist_ok=True)
    cfg = configparser.ConfigParser()
    if UNIFIED_CRM_PATH.exists():
        cfg.read(UNIFIED_CRM_PATH)
    if "crm" not in cfg:
        cfg["crm"] = {}
    cfg["crm"]["username"] = username
    cfg["crm"]["password"] = password
    with open(UNIFIED_CRM_PATH, "w") as f:
        cfg.write(f)
    UNIFIED_CRM_PATH.chmod(0o600)


def clear_crm_credentials() -> None:
    if not UNIFIED_CRM_PATH.exists():
        return
    cfg = configparser.ConfigParser()
    cfg.read(UNIFIED_CRM_PATH)
    if "crm" in cfg:
        cfg.remove_section("crm")
    with open(UNIFIED_CRM_PATH, "w") as f:
        cfg.write(f)
