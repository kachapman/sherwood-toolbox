"""Claim pairing and line-item matching.

Carrier and contractor files for the same loss are paired by claimant name
tokens parsed from the file name. Contractor files are named `SURNAME-Initial_...`;
carrier files embed the claimant name in varied boilerplate. A shared name token
of length >= 4 (excluding boilerplate words) identifies a pair.

Line items are matched across the two estimates on their normalized base key
(action prefix stripped), falling back to fuzzy similarity so that wrapped or
lightly reworded descriptions still line up.
"""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher

# Words that appear in file names but are not part of the claimant identity.
_BOILERPLATE = {
    "carrier", "estimate", "estimates", "revised", "revision", "exterior",
    "interior", "roof", "full", "rev", "draft", "rebuild", "ep", "story",
    "processed", "final", "copy", "the", "and", "of", "pdf",
}
_MONTHS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
           "nov", "dec"}


def section_tokens(name):
    """Alphabetic tokens (len >= 3) of a section name, lower-cased ('Roof1' ->
    {'roof'}). Shared by the paint anchoring and the section-total mapping so both
    align contractor and carrier sections the same way."""
    return {t for t in re.split(r"[^A-Za-z]+", (name or "").lower()) if len(t) >= 3}


def name_tokens(filename: str):
    """Ordered claimant tokens (len >= 3) from a file name, boilerplate removed."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    toks = []
    for t in re.split(r"[\s_\-\.]+", stem):
        t = t.lower()
        if len(t) < 3 or not t.isalpha() or t in _BOILERPLATE or t in _MONTHS:
            continue
        toks.append(t)
    return toks


def surname(filename: str, role: str) -> str:
    """The claimant surname used as the pairing key.

    Contractor files are named 'SURNAME-Initial_...' so the surname is the first
    token. Carrier files embed 'First Last' in boilerplate, so the surname is the
    last name token. Falls back to the longest token.
    """
    toks = name_tokens(filename)
    if not toks:
        return "unknown"
    if role == "contractor":
        return toks[0]
    return toks[-1]


def _key(tokens) -> str:
    """A stable display key: the longest token (usually the surname)."""
    toks = list(tokens)
    return max(toks, key=len) if toks else "unknown"


def pair_claims(carrier_files, contractor_files):
    """Return list of dicts: {claimant, carriers:[...], contractors:[...]}.

    Files are grouped by claimant surname (contractor leading token == carrier
    trailing token). Every file lands in exactly one group.
    """
    groups = {}   # surname -> {carriers:[], contractors:[], name:str}

    for f in contractor_files:
        s = surname(f, "contractor")
        g = groups.setdefault(s, {"carriers": [], "contractors": [], "name": s})
        g["contractors"].append(f)

    for f in carrier_files:
        s = surname(f, "carrier")
        g = groups.setdefault(s, {"carriers": [], "contractors": [], "name": s})
        g["carriers"].append(f)

    out = []
    for s, g in groups.items():
        out.append({
            "claimant": s.title(),
            "carriers": sorted(g["carriers"]),
            "contractors": sorted(g["contractors"]),
        })
    return sorted(out, key=lambda d: d["claimant"])


# --------------------------------------------------------------------------- #
# Line-item matching
# --------------------------------------------------------------------------- #

def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def match_line_items(carrier_items, contractor_items, threshold: float = 0.86,
                     price_guard: bool = True):
    """Match contractor items to carrier items by base key, then fuzzy.

    Returns (matched, missing, carrier_only):
      matched      -> list of (contractor_item, carrier_item)
      missing      -> contractor items with no carrier counterpart
      carrier_only -> carrier items with no contractor counterpart

    price_guard blocks a fuzzy (non-exact-base) match across a large unit-price gap,
    so a cross-software size variant ('...aluminum sheet - large' vs '...aluminum
    sheet') is not merged into a different-priced line. Turn it off when matching an
    estimate to its own revision, where the same carrier can correct a price on the
    same line by more than the gap and that is a real revision, not a new product.
    """
    # Drop "SEE REVISION" originals from both sides: a superseded contractor line
    # would otherwise consume the carrier partner its corrected replacement needs.
    carrier_items = [c for c in carrier_items if not getattr(c, "superseded", False)]
    contractor_items = [it for it in contractor_items if not getattr(it, "superseded", False)]
    # index carrier items by base key (allow multiple)
    by_base = {}
    for ci in carrier_items:
        by_base.setdefault(ci.base, []).append(ci)
    used = set()

    matched, missing = [], []
    for it in contractor_items:
        cand = [c for c in by_base.get(it.base, []) if id(c) not in used]
        if cand:
            # Several lines can share a base key (three tear-off runs at different
            # quantities); pair the closest in quantity so a line matches its true
            # counterpart, not merely the first listed. Pairing 1.43 SQ to 92.44 SQ
            # would read as a huge false increase.
            partner = min(cand, key=lambda c: abs(c.quantity - it.quantity))
            used.add(id(partner))
            matched.append((it, partner))
            continue
        # fuzzy fallback: score every unused carrier item, boosting a base that is
        # the other plus a trailing qualifier ('...shingles' vs '...shingles -
        # laminated', which the parser can produce when a description wraps). Among
        # plausible matches take the closest quantity.
        scored = []
        for c in carrier_items:
            if id(c) in used:
                continue
            # A size variant ('...aluminum sheet - large' vs '...aluminum sheet')
            # reads as a near-identical description but is a different product at a
            # different unit price. A fuzzy (non-exact-base) match across a large
            # price gap is one of those, not the same line reworded, so skip it and
            # let the variant stand as its own missing/added item.
            if (price_guard and it.unit_price > 0 and c.unit_price > 0
                    and min(it.unit_price, c.unit_price)
                    / max(it.unit_price, c.unit_price) < 0.80):
                continue
            s = _similar(it.base, c.base)
            a, b = it.base, c.base
            if len(a) >= 12 and len(b) >= 12 and (a in b or b in a):
                s = max(s, 0.90 + 0.09 * min(len(a), len(b)) / max(len(a), len(b)))
            if s >= threshold:
                scored.append((round(s, 2), abs(c.quantity - it.quantity), c))
        if scored:
            scored.sort(key=lambda t: (-t[0], t[1]))
            best = scored[0][2]
            used.add(id(best))
            matched.append((it, best))
        else:
            missing.append(it)

    carrier_only = [c for c in carrier_items if id(c) not in used]
    return matched, missing, carrier_only
