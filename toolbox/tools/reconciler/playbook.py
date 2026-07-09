"""Mine the contractor corpus into a 'playbook' of commonly-added items.

Frequency is counted per distinct claim (not per file) so that multiple revisions
of the same claimant's estimate do not inflate a line's weight. The playbook is
the checklist applied to carrier estimates that have no same-claimant contractor
file.
"""

from __future__ import annotations

import glob
import json
import os
import statistics
from collections import defaultdict

from .extract import extract_estimate
from .match import name_tokens, _key


def _median(xs):
    return round(statistics.median(xs), 2) if xs else 0.0


def build_playbook(contractor_dir: str):
    files = sorted(glob.glob(os.path.join(contractor_dir, "*.pdf")))

    # group files into claims so revisions count once
    claims = defaultdict(list)
    for f in files:
        claims[_key(name_tokens(f))].append(f)

    n_claims = len(claims)
    # per base key: aggregate across claims
    agg = defaultdict(lambda: {
        "descs": defaultdict(int), "category": None, "unit": defaultdict(int),
        "claims": set(), "qty": [], "unit_price": [], "rcv": [],
    })
    op_claims = 0
    op_rates = []

    for claimant, cfiles in claims.items():
        # use the largest (most complete) estimate as the claim representative
        ests = [extract_estimate(f, "contractor") for f in cfiles]
        rep = max(ests, key=lambda e: len(e.items))
        if rep.has_op:
            op_claims += 1
            if rep.line_item_total:
                op_rates.append(round((rep.overhead + rep.profit) / rep.line_item_total, 3))
        seen_bases = set()
        for it in rep.items:
            if not it.base:
                continue
            a = agg[it.base]
            a["descs"][it.description] += 1
            a["unit"][it.unit] += 1
            a["category"] = a["category"] or it.category
            a["qty"].append(it.quantity)
            a["unit_price"].append(it.unit_price)
            a["rcv"].append(it.rcv)
            if it.base not in seen_bases:
                a["claims"].add(claimant)
                seen_bases.add(it.base)

    items = []
    for base, a in agg.items():
        desc = max(a["descs"].items(), key=lambda kv: kv[1])[0]
        unit = max(a["unit"].items(), key=lambda kv: kv[1])[0]
        freq = len(a["claims"])
        items.append({
            "base": base,
            "description": desc,
            "category": a["category"],
            "unit": unit,
            "claim_frequency": freq,
            "claim_fraction": round(freq / n_claims, 3),
            "median_qty": _median(a["qty"]),
            "median_unit_price": _median(a["unit_price"]),
            "median_rcv": _median(a["rcv"]),
        })
    items.sort(key=lambda d: (-d["claim_frequency"], -d["median_rcv"]))

    return {
        "n_claims": n_claims,
        "claimants": sorted(claims.keys()),
        "op": {
            "claims_with_op": op_claims,
            "op_fraction": round(op_claims / n_claims, 3) if n_claims else 0.0,
            "typical_rate": _median(op_rates) if op_rates else 0.20,
        },
        "items": items,
    }


def save_playbook(pb, path="playbook.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pb, f, indent=2)
    return path


def load_playbook(path="playbook.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import sys
    cd = sys.argv[1] if len(sys.argv) > 1 else "contractor files"
    pb = build_playbook(cd)
    save_playbook(pb)
    print(f"claims={pb['n_claims']}  distinct items={len(pb['items'])}")
    print(f"O&P: {pb['op']['claims_with_op']}/{pb['n_claims']} claims "
          f"({pb['op']['op_fraction']*100:.0f}%), typical rate "
          f"{pb['op']['typical_rate']*100:.0f}%")
    print("\nTop 25 commonly-added items (by claim frequency):")
    for it in pb["items"][:25]:
        print(f"  {it['claim_frequency']:>2}/{pb['n_claims']} "
              f"[{it['category']:<15}] {it['description'][:42]:<42} "
              f"med_qty={it['median_qty']:>8.1f} {it['unit']:<3} "
              f"med$/u={it['median_unit_price']:>8.2f}")
