"""OnlyOffice CRM client for the reconciler: search deals, list a deal's PDF
files, and download one server-side. The CRM (office.publicadjustermidwest.com)
is an ONLYOFFICE Community Server, which exposes a JSON REST API, so this reads
structured data instead of scraping HTML.

Auth reuses restoration_common's `crm_login`, which returns a requests.Session
carrying the `asc_auth_key` cookie. The session is cached briefly and re-logged-in
on expiry, so a search -> list -> download sequence is one login, not three.

Only the file id crosses the wire from the browser; the download URL is built
here from that id, so the server never fetches an arbitrary client-supplied URL.
"""

from __future__ import annotations

import re
import time

try:
    from restoration_common import crm_login, load_crm_credentials
    try:
        from restoration_common.paths import CRM_BASE_URL
    except ImportError:
        # Older restoration_common exposes only CRM_LOGIN_URL ("<base>/Auth.aspx").
        from restoration_common.paths import CRM_LOGIN_URL
        CRM_BASE_URL = CRM_LOGIN_URL.rsplit("/", 1)[0]
    _HAVE_CRM = True
except Exception:                       # restoration_common absent in some builds
    _HAVE_CRM = False
    CRM_BASE_URL = "https://office.publicadjustermidwest.com"

import os as _os
CRM_BASE_URL = _os.environ.get("TOOLBOX_CRM_BASE_URL", CRM_BASE_URL)

API = CRM_BASE_URL.rstrip("/") + "/api/2.0"
FILEHANDLER = CRM_BASE_URL.rstrip("/") + "/Products/Files/HttpHandlers/filehandler.ashx"

_SESSION = None
_SESSION_TS = 0.0
_SESSION_TTL = 600          # seconds before a fresh login


class CrmError(Exception):
    """A user-facing CRM problem (not configured, auth failed, unreachable)."""


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Deals + files
# --------------------------------------------------------------------------- #

_DEALS_CACHE = None
_DEALS_TS = 0.0


def _all_deals():
    """Every opportunity as {id, title, stage}, paginated and cached. OnlyOffice's
    `searchText` does not actually filter by title (it returns a broad page), so
    the deal list is pulled once and searched client-side."""
    global _DEALS_CACHE, _DEALS_TS
    if _DEALS_CACHE is not None and time.time() - _DEALS_TS < _SESSION_TTL:
        return _DEALS_CACHE
    out, start = [], 0
    while start < 20000:            # hard safety bound
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
    """Deals whose title contains `query` (case-insensitive). Returns
    [{id, title, stage}], most-recently-created first."""
    q = (query or "").strip().lower()
    if not q:
        return []
    matches = [d for d in _all_deals() if q in (d["title"] or "").lower()]
    return matches[:limit]


def deal_files(deal_id):
    """PDF files attached to a deal, deduped by (title, size) and ranked so the
    likely estimates sort first. Returns [{id, title, size, bytes, updated,
    is_estimate, slot}]."""
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
    return rank_and_guess(files, deal_id, resp)


# --------------------------------------------------------------------------- #
# Ranking + slot guessing (heuristic, from the filename)
# --------------------------------------------------------------------------- #

# Documents that are clearly not estimates, pushed to the bottom.
_JUNK = re.compile(
    r"w-?9\b|licen[sc]e|\bpa contract\b|invoice|verification report|complaint|"
    r"declaration|renewal|\bform\b|engineer|profile|hail-verification|"
    r"wind-verification|\bpolicy\b|damage report|evaluation|\bphotos?\b|"
    r"property owner report|full report|payment|letter|contract\b", re.I)
# Words that make a file look like an estimate.
_EST = re.compile(r"estimate|xactimate|symbility|\bscope\b|supplement|repair|"
                  r"c[_-]roof|_exterior|_interior|reconcil", re.I)
_OG = re.compile(r"\bo\.?g\.?\b|original", re.I)
# Common carriers, to spot a carrier estimate (not its policy/declarations).
_CARRIER = re.compile(
    r"state\s*farm|allstate|liberty|farmers|usaa|nationwide|american family|"
    r"erie|travelers|progressive|safeco|\bsf[-_ ]|\bcarrier\b", re.I)
# Contractor-side estimate naming (Xactimate exports, our file conventions).
_CONTRACTOR = re.compile(
    r"c[_-]roof|_exterior|_interior|supplement|xactimate|\bscope\b", re.I)
# A higher revision / newer carrier estimate (current, vs the original).
_REVISED = re.compile(r"revis|\bsf[-_]?\d|\b-?\d\b\s*$|final", re.I)


def _estimate_score(title, biggest_bytes, byts):
    t = title or ""
    score = 0.0
    if _EST.search(t):
        score += 3
    if _CARRIER.search(t):
        score += 2
    if _CONTRACTOR.search(t):
        score += 2
    if _OG.search(t):
        score += 1
    if _JUNK.search(t):
        score -= 6
    # Estimates tend to be the larger PDFs; nudge by relative size.
    if biggest_bytes:
        score += 1.5 * (byts / biggest_bytes)
    return score


def rank_and_guess(files, deal_id, raw):
    """Score files by estimate-likelihood, sort best first, and pre-guess a slot
    (carrier | contractor | original). The dropdowns still list every file, so a
    wrong guess is a one-click fix; this just saves the common case."""
    biggest = max((f["bytes"] for f in files), default=0)
    for f in files:
        f["score"] = round(_estimate_score(f["title"], biggest, f["bytes"]), 2)
        f["is_estimate"] = f["score"] >= 2
    files.sort(key=lambda f: (-f["score"], f["title"].lower()))

    estimates = [f for f in files if f["is_estimate"]]
    guess = {"carrier": None, "contractor": None, "og": None}

    # Contractor supplement: the largest estimate that is not an insurer-named
    # carrier estimate (contractor Xactimate exports dominate in size), or the
    # strongest contractor-named one.
    named = [f for f in estimates if _CONTRACTOR.search(f["title"])
             and not _CARRIER.search(f["title"])]
    non_carrier = [f for f in estimates if not _CARRIER.search(f["title"])]
    pool = named or non_carrier
    if pool:
        guess["contractor"] = max(pool, key=lambda f: f["bytes"])["id"]

    # Carrier estimates: insurer/"carrier"-named, minus the contractor pick. When
    # there are two, the newer (by CRM date, then a "revised" hint) is the current
    # carrier and the older is the original.
    carriers = [f for f in estimates if f["id"] != guess["contractor"]
                and _CARRIER.search(f["title"])]
    carriers.sort(key=lambda f: (f["updated"], 1 if _REVISED.search(f["title"]) else 0),
                  reverse=True)
    if carriers:
        guess["carrier"] = carriers[0]["id"]

    # Original carrier: prefer an explicitly "OG"/"original" estimate (even if it
    # carries no insurer name), else the older of the carrier estimates.
    taken = {guess["carrier"], guess["contractor"]}
    og_named = [f for f in estimates if _OG.search(f["title"]) and f["id"] not in taken]
    if og_named:
        guess["og"] = og_named[0]["id"]
    elif len(carriers) >= 2:
        guess["og"] = carriers[-1]["id"]

    for f in files:
        f["slot"] = next((k for k, v in guess.items() if v == f["id"]), "")
    return {"files": files, "guess": guess}


def download_file(file_id, dest):
    """Download one CRM file (by its numeric id) to `dest` via the session."""
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
