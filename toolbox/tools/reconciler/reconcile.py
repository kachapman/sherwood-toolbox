"""Reconcile a carrier estimate against the contractor scope and the playbook.

Two modes:

  * reconciled  -> a same-claimant contractor file exists. Line items are matched
                   and the RCV difference between the two files is bridged with an
                   exact identity (see rcv_bridge).
  * estimated   -> no contractor file. The playbook checklist of commonly-added
                   items projects the likely-missing scope and O&P.

Suggestion tiers:
  MISSING      contractor item absent from carrier (reconciled mode, high conf)
  SUGGESTED    playbook item absent from carrier (estimated mode; conf ~ frequency)
  MISSING_OP   carrier applied no Overhead & Profit
  INFO         shared item where the contractor unit price is higher (advisory)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .match import match_line_items


def base(it) -> float:
    return round(it.quantity * it.unit_price, 2)


def _confidence_note(est):
    """Actionable parse-confidence caveat for a carrier estimate, or None."""
    if est.ocr and (est.confidence == "low" or est.parse_ratio < 0.85):
        return (f"carrier is an image-only scan; OCR read only "
                f"{est.parse_ratio*100:.0f}% of the line-item total, so the carrier "
                f"RCV and the gap below are approximate. Re-export the carrier "
                f"estimate as a text PDF for an exact reconciliation.")
    if est.confidence == "low":
        return (f"carrier parsed at low confidence "
                f"({est.parse_ratio*100:.0f}% of total); verify figures manually.")
    if est.confidence == "medium":
        return (f"carrier parsed at medium confidence "
                f"({est.parse_ratio*100:.0f}% of total).")
    return None


@dataclass
class Suggestion:
    status: str            # MISSING | SUGGESTED | MISSING_OP | INFO
    description: str
    category: str
    quantity: float
    unit: str
    carrier_unit_price: float
    contractor_unit_price: float
    dollars: float         # estimated recoverable RCV impact
    confidence: str
    note: str = ""


@dataclass
class SharedItem:
    """A line item both estimates carry, with the price and quantity breakdown.
    All figures are pulled from the two estimates as printed."""
    description: str
    category: str
    unit: str
    carrier_quantity: float
    contractor_quantity: float
    quantity_delta: float          # contractor - carrier
    carrier_unit_price: float
    contractor_unit_price: float
    price_delta: float             # contractor - carrier
    carrier_rcv: float
    contractor_rcv: float
    rcv_delta: float               # contractor - carrier


@dataclass
class Recon:
    claimant: str
    mode: str                       # 'reconciled' | 'estimated'
    carrier_name: str
    carrier_grand: float
    carrier_conf: str
    carrier_ocr: bool
    contractor_name: str = ""
    contractor_grand: float = 0.0
    contractor_conf: str = ""
    carrier_has_op: bool = False
    contractor_has_op: bool = False
    suggestions: list = field(default_factory=list)
    shared: list = field(default_factory=list)
    bridge: dict = field(default_factory=dict)
    est_recoverable: float = 0.0
    notes: list = field(default_factory=list)


# --------------------------------------------------------------------------- #
# RCV bridge
# --------------------------------------------------------------------------- #

def rcv_bridge(carrier, contractor, matched, missing, carrier_only):
    """Exact build-up from carrier RCV to contractor RCV.

    Identity (in line-item base dollars):
        contractor_base - carrier_base
            = missing_base + matched_delta - carrier_only_base

    Grand totals add tax and O&P on top of base, so:
        contractor_grand - carrier_grand
            = (base gap) + tax_gap + op_gap + residual

    The residual captures parse incompleteness and rounding; a small residual
    means the two files are fully reconciled.
    """
    missing_base = round(sum(base(it) for it in missing), 2)
    matched_delta = round(sum(base(ci) - base(cr) for ci, cr in matched), 2)
    carrier_only_base = round(sum(base(cr) for cr in carrier_only), 2)

    op_gap = round((contractor.overhead + contractor.profit)
                   - (carrier.overhead + carrier.profit), 2)
    tax_gap = round(contractor.sales_tax - carrier.sales_tax, 2)

    predicted = round(carrier.grand_rcv + missing_base + matched_delta
                      - carrier_only_base + op_gap + tax_gap, 2)
    residual = round(contractor.grand_rcv - predicted, 2)

    return {
        "carrier_rcv": carrier.grand_rcv,
        "missing_base": missing_base,
        "matched_delta": matched_delta,
        "carrier_only_base": carrier_only_base,
        "op_gap": op_gap,
        "tax_gap": tax_gap,
        "predicted_contractor_rcv": predicted,
        "actual_contractor_rcv": contractor.grand_rcv,
        "residual": residual,
        "total_gap": round(contractor.grand_rcv - carrier.grand_rcv, 2),
    }


# --------------------------------------------------------------------------- #
# Reconciled mode
# --------------------------------------------------------------------------- #

def reconcile_matched(carrier, contractor, claimant, playbook=None):
    # index carrier items, iterate contractor -> missing = contractor scope the
    # carrier lacks; carrier_only = items the carrier has but the contractor drops.
    matched, missing, carrier_only = match_line_items(carrier.items, contractor.items)

    # Missing line items: contractor scope the carrier omits, grouped by category
    # with the largest-dollar categories first and, within a category, largest RCV
    # first. Dollars are the RCV as printed in the contractor estimate (it.rcv),
    # not a recomputed qty x price.
    cat_total = {}
    for it in missing:
        cat_total[it.category] = cat_total.get(it.category, 0.0) + it.rcv
    sugg = []
    for it in sorted(missing, key=lambda x: (-cat_total[x.category], x.category, -x.rcv)):
        sugg.append(Suggestion(
            status="MISSING", description=it.description, category=it.category,
            quantity=it.quantity, unit=it.unit, carrier_unit_price=0.0,
            contractor_unit_price=it.unit_price, dollars=it.rcv,
            confidence="high",
            note="in contractor scope, absent from carrier"))

    # Shared items: every matched pair with its price and quantity breakdown, all
    # figures pulled from the two estimates. Grouped by category, largest RCV
    # difference first. (ci = contractor item, cr = carrier item.)
    shared = []
    for ci, cr in matched:
        shared.append(SharedItem(
            description=cr.description or ci.description,
            category=cr.category,
            unit=cr.unit or ci.unit,
            carrier_quantity=cr.quantity,
            contractor_quantity=ci.quantity,
            quantity_delta=round(ci.quantity - cr.quantity, 2),
            carrier_unit_price=cr.unit_price,
            contractor_unit_price=ci.unit_price,
            price_delta=round(ci.unit_price - cr.unit_price, 2),
            carrier_rcv=cr.rcv,
            contractor_rcv=ci.rcv,
            rcv_delta=round(ci.rcv - cr.rcv, 2)))
    scat_total = {}
    for s in shared:
        scat_total[s.category] = scat_total.get(s.category, 0.0) + abs(s.rcv_delta)
    shared.sort(key=lambda s: (-scat_total[s.category], s.category, -abs(s.rcv_delta)))

    bridge = rcv_bridge(carrier, contractor, matched, missing, carrier_only)
    # Recoverable = the net RCV the contractor scope supports beyond the carrier
    # (the bridge gap), which already nets out items the carrier alone carries.
    est = round(max(0.0, bridge["total_gap"]), 2)

    r = Recon(
        claimant=claimant, mode="reconciled", carrier_name=carrier.name,
        carrier_grand=carrier.grand_rcv, carrier_conf=carrier.confidence,
        carrier_ocr=carrier.ocr, contractor_name=contractor.name,
        contractor_grand=contractor.grand_rcv, contractor_conf=contractor.confidence,
        carrier_has_op=carrier.has_op, contractor_has_op=contractor.has_op,
        suggestions=sugg, shared=shared, bridge=bridge, est_recoverable=est)

    if carrier.items and not matched:
        r.notes.append("cross-platform pair (carrier and contractor use different "
                       "estimating software); line items do not name-match, so the "
                       "itemized list may repeat scope the carrier already covers. "
                       "Trust the RCV bridge total over the per-item list here.")
    cn = _confidence_note(carrier)
    if cn:
        r.notes.append(cn)
    return r


# --------------------------------------------------------------------------- #
# Estimated (playbook) mode
# --------------------------------------------------------------------------- #

# Trades that apply to almost any exterior claim regardless of what else is in
# scope, so a playbook suggestion in these categories is always in bounds.
_UNIVERSAL_CATS = {"PERMITS/FEES", "CLEANING", "ACCESS/SCAFFOLD", "O&P"}


def reconcile_playbook(carrier, claimant, playbook, min_fraction=0.35):
    carrier_bases = {it.base for it in carrier.items}
    # Scope suggestions to the trades the carrier already worked, so a roof-only
    # claim is not told to add siding and gutters it never involved.
    carrier_cats = {it.category for it in carrier.items} | _UNIVERSAL_CATS
    oprate = playbook["op"]["typical_rate"]

    sugg = []
    for pit in playbook["items"]:
        if pit["claim_fraction"] < min_fraction:
            continue
        if pit["base"] in carrier_bases:
            continue
        if pit["category"] not in carrier_cats:
            continue
        frac = pit["claim_fraction"]
        conf = "high" if frac >= 0.6 else "medium" if frac >= 0.45 else "low"
        sugg.append(Suggestion(
            status="SUGGESTED", description=pit["description"],
            category=pit["category"], quantity=pit["median_qty"], unit=pit["unit"],
            carrier_unit_price=0.0, contractor_unit_price=pit["median_unit_price"],
            dollars=pit["median_rcv"], confidence=conf,
            note=f"contractors add this in {pit['claim_frequency']}/"
                 f"{playbook['n_claims']} claims"))

    # O&P estimate
    op_est = 0.0
    if not carrier.has_op:
        carrier_base = round(sum(base(it) for it in carrier.items), 2)
        op_est = round(oprate * carrier_base, 2)
        sugg.insert(0, Suggestion(
            status="MISSING_OP", description=f"Overhead & Profit ({oprate*100:.0f}%)",
            category="O&P", quantity=1.0, unit="EA", carrier_unit_price=0.0,
            contractor_unit_price=op_est, dollars=op_est, confidence="medium",
            note=f"carrier applied no O&P; {playbook['op']['claims_with_op']}/"
                 f"{playbook['n_claims']} contractor claims apply it"))

    items_est = round(sum(s.dollars for s in sugg if s.status == "SUGGESTED"), 2)
    projected = round(carrier.grand_rcv + items_est + op_est, 2)
    bridge = {
        "carrier_rcv": carrier.grand_rcv,
        "suggested_items": items_est,
        "op_estimate": op_est,
        "projected_supported_rcv": projected,
        "uplift": round(projected - carrier.grand_rcv, 2),
    }
    r = Recon(
        claimant=claimant, mode="estimated", carrier_name=carrier.name,
        carrier_grand=carrier.grand_rcv, carrier_conf=carrier.confidence,
        carrier_ocr=carrier.ocr, carrier_has_op=carrier.has_op,
        suggestions=sugg, bridge=bridge,
        est_recoverable=round(items_est + op_est, 2))
    r.notes.append("no same-claimant contractor file; suggestions are playbook "
                   "estimates from the contractor corpus, not a line-by-line "
                   "reconciliation. Item dollars use playbook median quantities and "
                   "may not match this claim's measurements.")
    cn = _confidence_note(carrier)
    if cn:
        r.notes.append(cn)
    return r
