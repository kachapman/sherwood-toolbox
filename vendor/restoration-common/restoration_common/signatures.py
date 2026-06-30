#!/usr/bin/env python3
"""Per-company signature storage (base64 PNG in user config)."""

import base64
import json
import os
import shutil
import tempfile
from typing import Dict, Optional

from .paths import USER_SIGNATURES_JSON, USER_CONFIG_DIR


def migrate_legacy_signatures(legacy_path) -> None:
    """One-time copy of an old per-app signatures.json into user config."""
    if USER_SIGNATURES_JSON.exists():
        return
    if legacy_path and os.path.exists(legacy_path):
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_path, USER_SIGNATURES_JSON)


def load_signatures() -> Dict[str, str]:
    if not USER_SIGNATURES_JSON.exists():
        return {}
    with open(USER_SIGNATURES_JSON, "r") as f:
        return json.load(f)


def save_signatures(signatures: Dict[str, str]) -> None:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(USER_SIGNATURES_JSON, "w") as f:
        json.dump(signatures, f, indent=2)


def get_signature_path(company_id: str) -> Optional[str]:
    """Decode a company's stored signature to a temp PNG; return its path."""
    sigs = load_signatures()
    if company_id not in sigs:
        return None
    try:
        fd, path = tempfile.mkstemp(suffix=".png", prefix=f"sig_{company_id}_")
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(sigs[company_id]))
        return path
    except Exception as e:
        print(f"Warning: could not decode signature: {e}")
        return None


def save_signature_for_company(company_id: str, image_path: str) -> None:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    sigs = load_signatures()
    sigs[company_id] = b64
    save_signatures(sigs)
