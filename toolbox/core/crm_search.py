from __future__ import annotations

import time

try:
    from restoration_common import crm_login, load_crm_credentials
    try:
        from restoration_common.paths import CRM_BASE_URL
    except ImportError:
        from restoration_common.paths import CRM_LOGIN_URL
        CRM_BASE_URL = CRM_LOGIN_URL.rsplit("/", 1)[0]
    _HAVE_CRM = True
except Exception:
    _HAVE_CRM = False
    CRM_BASE_URL = "https://office.publicadjustermidwest.com"

import os as _os
CRM_BASE_URL = _os.environ.get("TOOLBOX_CRM_BASE_URL", CRM_BASE_URL)

API = CRM_BASE_URL.rstrip("/") + "/api/2.0"
FILEHANDLER = CRM_BASE_URL.rstrip("/") + "/Products/Files/HttpHandlers/filehandler.ashx"

_SESSION = None
_SESSION_TS = 0.0
_SESSION_TTL = 600

_DEALS_CACHE = None
_DEALS_TS = 0.0


class CrmError(Exception):
    pass


def _session(force=False):
    global _SESSION, _SESSION_TS
    if not _HAVE_CRM:
        raise CrmError("CRM support is not available in this build.")
    if not force and _SESSION is not None and time.time() - _SESSION_TS < _SESSION_TTL:
        return _SESSION
    try:
        user, password = load_crm_credentials()
    except Exception:
        raise CrmError("CRM credentials are not configured on this machine.")
    try:
        s = crm_login(user, password)
    except Exception as e:
        raise CrmError(f"CRM login failed: {e}")
    s.headers["Accept"] = "application/json"
    _SESSION, _SESSION_TS = s, time.time()
    return s


def _api_get(path, params=None, _retry=True):
    s = _session()
    try:
        r = s.get(API + path, params=params, timeout=25)
    except Exception as e:
        raise CrmError(f"Could not reach the CRM: {e}")
    if r.status_code in (401, 403) or "auth" in r.url.lower():
        if _retry:
            _session(force=True)
            return _api_get(path, params, _retry=False)
        raise CrmError("CRM session expired; could not re-authenticate.")
    if r.status_code != 200:
        raise CrmError(f"CRM returned HTTP {r.status_code}.")
    try:
        d = r.json()
    except Exception:
        raise CrmError("CRM returned an unexpected (non-JSON) response.")
    return d.get("response", d) if isinstance(d, dict) else d


def _all_deals():
    global _DEALS_CACHE, _DEALS_TS
    if _DEALS_CACHE is not None and time.time() - _DEALS_TS < _SESSION_TTL:
        return _DEALS_CACHE
    out, start = [], 0
    while start < 20000:
        s = _session()
        r = s.get(API + "/crm/opportunity/filter",
                  params={"count": 500, "startIndex": start}, timeout=25)
        d = r.json()
        resp = d.get("response", []) if isinstance(d, dict) else (d or [])
        for o in resp:
            out.append({"id": o.get("id"), "title": o.get("title", ""),
                        "stage": (o.get("stage") or {}).get("title", "")})
        total = d.get("total", 0) if isinstance(d, dict) else 0
        start += len(resp)
        if not resp or start >= total:
            break
    _DEALS_CACHE, _DEALS_TS = out, time.time()
    return out


def search_deals(query, limit=15):
    q = (query or "").strip().lower()
    if not q:
        return []
    matches = [d for d in _all_deals() if q in (d["title"] or "").lower()]
    return matches[:limit]


def deal_files(deal_id):
    resp = _api_get(f"/crm/opportunity/{int(deal_id)}/files")
    files, seen = [], set()
    for f in resp or []:
        if (f.get("fileExst") or "").lower() != ".pdf":
            continue
        key = (f.get("title", ""), f.get("pureContentLength", 0))
        if key in seen:
            continue
        seen.add(key)
        files.append({
            "id": f.get("id"),
            "title": f.get("title", ""),
            "size": f.get("contentLength", ""),
            "bytes": f.get("pureContentLength", 0) or 0,
            "updated": (f.get("updated") or "")[:10],
        })
    return {"files": files}


def download_file(file_id, dest):
    s = _session()
    try:
        r = s.get(FILEHANDLER, params={"action": "download", "fileid": int(file_id)},
                  timeout=90)
    except Exception as e:
        raise CrmError(f"Could not download the file: {e}")
    if r.status_code != 200 or not r.content:
        raise CrmError(f"CRM file download failed (HTTP {r.status_code}).")
    with open(dest, "wb") as fh:
        fh.write(r.content)
    return dest
