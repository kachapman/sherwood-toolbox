"""Minimal token-based auth for web mode.

Tokens are generated in Admin (employees only). Stored as sha256 hashes.
Plaintext token is shown only at creation time.

Roles: "employee" (full access) or "customer" (Enhancer + IWS only).

In non-WEB_MODE (desktop/AppImage), everything behaves as employee.
"""
import hashlib
import json
import secrets
import time
from pathlib import Path

from ..config import Config

TOKENS_FILE = Config.DATA_DIR / "web_tokens.json"


def _load():
    try:
        if TOKENS_FILE.exists():
            return json.loads(TOKENS_FILE.read_text())
    except Exception:
        pass
    return {"tokens": {}}


def _save(data):
    Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(json.dumps(data, indent=2))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def has_any_tokens() -> bool:
    data = _load()
    return bool(data.get("tokens"))


def create_token(role: str, label: str = None) -> str:
    if role not in ("employee", "customer"):
        raise ValueError("role must be 'employee' or 'customer'")
    data = _load()
    token = secrets.token_urlsafe(32)
    h = _hash(token)
    data.setdefault("tokens", {})[h] = {
        "role": role,
        "created": int(time.time()),
        "label": (label or "").strip()[:64],
    }
    _save(data)
    return token  # plaintext shown only once


def list_tokens():
    data = _load()
    out = []
    for h, meta in (data.get("tokens") or {}).items():
        out.append({
            "id": h[:8],
            "role": meta.get("role"),
            "created": meta.get("created"),
            "label": meta.get("label", ""),
        })
    return sorted(out, key=lambda x: x["created"], reverse=True)


def revoke(token_id: str) -> bool:
    """Revoke by short id (first 8 hex chars of hash)."""
    data = _load()
    for h in list((data.get("tokens") or {}).keys()):
        if h.startswith(token_id):
            data["tokens"].pop(h, None)
            _save(data)
            return True
    return False


def validate(token: str):
    """Return role or None."""
    if not token:
        return None
    h = _hash(token)
    data = _load()
    meta = (data.get("tokens") or {}).get(h)
    if meta:
        return meta.get("role")
    return None


def bootstrap_accept(plaintext: str, label: str = "first"):
    """If no tokens exist, store the given plaintext as an employee token.
    Returns True if it was stored, False if tokens already existed."""
    if has_any_tokens():
        return False
    data = _load()
    h = _hash(plaintext)
    data.setdefault("tokens", {})[h] = {
        "role": "employee",
        "created": int(time.time()),
        "label": (label or "first")[:64],
    }
    _save(data)
    return True


# --- Request helpers (cookie-based "remember me") ---

TOKEN_COOKIE = "toolbox_token"


def get_token_from_request(request):
    """Pull token from cookie, form, query, or Authorization header."""
    # Cookie first (remember me)
    tok = request.cookies.get(TOKEN_COOKIE)
    if tok:
        return tok
    # Form or query (for login POST or quick tests)
    tok = request.form.get("token") or request.args.get("token")
    if tok:
        return tok
    # Bearer
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip()
    return None


def get_current_role(request):
    """Return 'employee' | 'customer' | None (no valid token)."""
    tok = get_token_from_request(request)
    role = validate(tok)
    return role


def is_employee(request):
    return get_current_role(request) == "employee"


def is_customer(request):
    return get_current_role(request) == "customer"


def set_token_cookie(resp, token, remember=True):
    """Attach token cookie to response. For web, prefer secure in production."""
    if not token:
        return resp
    # In web deployment behind reverse proxy with TLS, set secure=True.
    # For LAN testing, keep False so http works.
    resp.set_cookie(
        TOKEN_COOKIE,
        token,
        httponly=True,
        samesite="Lax",
        secure=False,  # set True in prod if https
        max_age=(60 * 60 * 24 * 30) if remember else None,
    )
    return resp


def clear_token_cookie(resp):
    resp.delete_cookie(TOKEN_COOKIE)
    return resp

