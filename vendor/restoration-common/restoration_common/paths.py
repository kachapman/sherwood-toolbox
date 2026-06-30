#!/usr/bin/env python3
"""Shared path constants for the restoration toolkit.

The package ships canonical company data and logos under ``data/``. User edits
(add / edit / remove company, saved signatures, CRM credentials) live under
``~/.config/restoration_toolkit`` so the shipped defaults stay pristine and
``site-packages`` is never written.
"""

import os
from pathlib import Path

# Package data (shipped, read-only). Editable install keeps these on disk, so
# they resolve to real filesystem paths that reportlab can open directly.
PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
LOGO_DIR = DATA_DIR / "logos"
DEFAULT_COMPANIES_JSON = DATA_DIR / "companies.json"

# User-writable state.
USER_CONFIG_DIR = Path.home() / ".config" / "restoration_toolkit"
USER_COMPANIES_JSON = USER_CONFIG_DIR / "companies.json"
USER_SIGNATURES_JSON = USER_CONFIG_DIR / "signatures.json"

# CRM credential locations (unified + legacy fallbacks).
UNIFIED_CRM_DIR = Path.home() / ".config" / "photo_report_generator"
UNIFIED_CRM_PATH = UNIFIED_CRM_DIR / "crm.ini"
OLD_BANEY_CRM_PATH = Path.home() / ".config" / "baney" / "crm.ini"
OLD_VANGUARD_CRM_PATH = Path.home() / ".config" / "vanguard" / "crm.ini"

# CRM login endpoint. The base URL can be overridden with TOOLBOX_CRM_BASE_URL
# so the same build works across different CRM deployments.
CRM_BASE_URL = os.environ.get(
    "TOOLBOX_CRM_BASE_URL", "https://office.publicadjustermidwest.com"
).rstrip("/")
CRM_LOGIN_URL = f"{CRM_BASE_URL}/Auth.aspx"
