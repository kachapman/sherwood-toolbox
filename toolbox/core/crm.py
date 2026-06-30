"""Graceful wrapper around restoration_common's CRM fetch so the Photo Report
and Documents tools degrade cleanly when offline or unconfigured instead of
erroring. Also parses the returned one-line address into street + City/State/ZIP
so those land in the right form fields.
"""
import re

from ..config import Config

# State + ZIP anchored at the end of an address line, e.g. "IL 62704" or
# "IL 62704-1234" (optional comma before the state).
_STATE_ZIP_RE = re.compile(r'\b([A-Za-z]{2})\s*,?\s+(\d{5}(?:-\d{4})?)\s*$')
# A remainder that is only a state and ZIP (so a preceding comma split the
# city from the state, not the street from the city).
_ONLY_STATE_ZIP_RE = re.compile(r'^[A-Za-z]{2}\s+\d{5}(?:-\d{4})?$')

# Street-type words that mark the end of the street, so the city can follow on
# the same line without a delimiter. Both spelled-out and abbreviated forms.
_STREET_SUFFIXES = {
    "street", "st", "avenue", "ave", "av", "road", "rd", "boulevard", "blvd",
    "drive", "dr", "lane", "ln", "court", "ct", "circle", "cir", "place", "pl",
    "way", "terrace", "ter", "trail", "trl", "parkway", "pkwy", "highway", "hwy",
    "route", "rte", "square", "sq", "loop", "path", "pike", "run", "pass",
    "crossing", "xing", "point", "pt", "ridge", "bend", "cove", "row", "alley",
    "plaza", "commons", "crescent", "cres", "grove", "glen", "manor", "walk",
}


def _split_street_city(blob):
    """Split a 'street city' blob (no state/zip) into (street, city).

    Prefers the last street-type word as the boundary, so spelled-out types
    like 'Road' or 'Circle' keep the city out of the street. Falls back to
    treating the final word as the city when no street type is present.
    """
    toks = blob.split()
    if not toks:
        return "", ""
    suffix_idx = -1
    for i, t in enumerate(toks):
        if t.strip(".").lower() in _STREET_SUFFIXES:
            suffix_idx = i
    if 0 <= suffix_idx < len(toks) - 1:
        return " ".join(toks[:suffix_idx + 1]), " ".join(toks[suffix_idx + 1:])
    if suffix_idx == len(toks) - 1:
        return blob, ""  # street type is the last word; no city on this line
    if len(toks) > 1:
        return " ".join(toks[:-1]), toks[-1]
    return blob, ""


def parse_address(address):
    """Split an address into street and 'City, ST ZIP'.

    Handles multi-line, comma-delimited, and single-line forms, including the
    common 'STREET CITY, ST ZIP' shape where the only comma sits between the
    city and the state. Returns street, city_state_zip, and the parts.
    """
    empty = {"street": "", "city_state_zip": "", "city": "", "state": "", "zip": ""}
    raw = (address or "").strip()
    if not raw:
        return empty

    # Collapse spaces within each line but keep line breaks as delimiters.
    lines = [" ".join(ln.split()) for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return empty

    if len(lines) >= 2:
        street, rest = lines[0], ", ".join(lines[1:])
    else:
        line = lines[0]
        if "," in line:
            left, right = (s.strip() for s in line.split(",", 1))
            if _ONLY_STATE_ZIP_RE.match(right):
                # Comma split city from state; the street and city share the left.
                street, city = _split_street_city(left)
                rest = f"{city} {right}".strip()
            else:
                street, rest = left, right
        else:
            m = _STATE_ZIP_RE.search(line)
            if m:
                street, city = _split_street_city(line[:m.start()].strip())
                rest = f"{city} {m.group(1).upper()} {m.group(2)}".strip()
            else:
                street, rest = line, ""

    street = street.strip().strip(",").strip()
    rest = rest.strip().strip(",").strip()

    m2 = _STATE_ZIP_RE.search(rest)
    state = m2.group(1).upper() if m2 else ""
    zipc = m2.group(2) if m2 else ""
    city = _STATE_ZIP_RE.sub("", rest).strip().strip(",").strip() if rest else ""

    csz = city
    if state:
        csz = f"{csz}, {state}" if csz else state
    if zipc:
        csz = f"{csz} {zipc}" if csz else zipc
    city_state_zip = csz.strip() or rest

    return {"street": street, "city_state_zip": city_state_zip,
            "city": city, "state": state, "zip": zipc}


def fetch_job_info(url):
    """Return {'ok': True, 'info': {...}} or {'ok': False, 'error': '...'}.

    On success, info includes the raw CRM fields plus parsed street and
    city_state_zip derived from job_location.
    """
    if Config.OFFLINE:
        return {"ok": False, "error": "Offline mode: CRM lookup is unavailable. Enter the fields manually."}
    if not url or not url.strip().lower().startswith("http"):
        return {"ok": False, "error": "Enter a valid CRM job URL (https://...)."}
    try:
        from restoration_common import fetch_job_info_from_url, NeedsCredentialsError
    except Exception:
        return {"ok": False, "error": "CRM support is not available in this build."}
    try:
        info = dict(fetch_job_info_from_url(url.strip()) or {})
        location = info.get("job_location", "")
        if location:
            parsed = parse_address(location)
            info.setdefault("street", parsed["street"])
            info.setdefault("city_state_zip", parsed["city_state_zip"])
            info["address"] = parsed
        return {"ok": True, "info": info}
    except NeedsCredentialsError:
        return {"ok": False,
                "error": "CRM credentials are not configured "
                         "(~/.config/photo_report_generator/crm.ini)."}
    except Exception as e:
        return {"ok": False, "error": "CRM lookup failed: %s" % e}
