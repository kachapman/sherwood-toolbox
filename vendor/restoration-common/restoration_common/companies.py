#!/usr/bin/env python3
"""Company configuration loading, saving, and helpers.

Model: the package ships canonical defaults in ``data/companies.json``. Once the
user adds, edits, or removes a company through the GUI, the full list is written
to ``~/.config/restoration_toolkit/companies.json``, which then becomes
authoritative. This keeps removal predictable (an omitted company stays removed)
and never writes into the package.
"""

import json
from typing import Any, Dict, List, Optional

from .paths import DEFAULT_COMPANIES_JSON, USER_COMPANIES_JSON, USER_CONFIG_DIR


def _read_json_list(path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, "r") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def load_default_companies() -> List[Dict[str, Any]]:
    """Return the shipped canonical companies."""
    return _read_json_list(DEFAULT_COMPANIES_JSON)


def load_companies() -> List[Dict[str, Any]]:
    """Return the active company list.

    The user file is authoritative when present; otherwise the shipped
    defaults are used.
    """
    if USER_COMPANIES_JSON.exists():
        user = _read_json_list(USER_COMPANIES_JSON)
        if user:
            return user
    return load_default_companies()


def save_companies(companies: List[Dict[str, Any]]) -> None:
    """Persist the full company list to the user config file."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(USER_COMPANIES_JSON, "w") as f:
        json.dump(companies, f, indent=2)


def get_company_by_id(company_id: str) -> Optional[Dict[str, Any]]:
    for c in load_companies():
        if c.get("id") == company_id:
            return c
    return None


def flat_address(company: Dict[str, Any]) -> str:
    """Join the structured address into a single line for the photo report.

    Normalizes spacing so the rendered address reads ``street, city_state_zip``.
    """
    address = (company.get("address") or "").strip().rstrip(",").strip()
    csz = (company.get("city_state_zip") or "").strip()
    if csz:
        return f"{address}, {csz}"
    return address
