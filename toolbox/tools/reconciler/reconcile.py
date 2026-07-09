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

from .extract import infer_themes, is_extension_item
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
    number: int = 0        # line-item number as printed in the source estimate
    section: str = ""      # source-estimate section the item belongs to


@dataclass
class SharedItem:
    """A line item both estimates carry, with the price and quantity breakdown.
    All figures are pulled from the two estimates as printed."""
    description: str
    category: str
    carrier_number: int            # line number as printed in the carrier estimate
    contractor_number: int         # line number as printed in the contractor estimate
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
    carrier_statements: list = field(default_factory=list)
    hypotheses: list = field(default_factory=list)
    # Three-way approval-effectiveness fields (populated in effectiveness mode).
    og_name: str = ""
    og_grand: float = 0.0
    ask_dollars: float = 0.0          # supplement over the original carrier
    approved_dollars: float = 0.0     # current carrier over the original (won to date)
    outstanding_dollars: float = 0.0  # supplement still not in the current carrier
    effectiveness: float = 0.0        # approved / ask, by grand-total dollars
    approved_wins: list = field(default_factory=list)  # current-carrier LineItems new vs OG
    narrative: list = field(default_factory=list)  # plain-language summary [{text, tone}]


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
# Denial hypotheses
# --------------------------------------------------------------------------- #

@dataclass
class DenialHypothesis:
    """A possible reason a cluster of missing items was left out. `basis` is
    'quoted' only when the carrier estimate states a matching exclusion; every
    other row is 'inference' and is labeled for the reviewer to verify. Never an
    asserted carrier reason without a quote to back it."""
    theme: str                 # MATCHING | CODE | UNEXPLAINED
    basis: str                 # 'quoted' | 'inference'
    label: str                 # display label for the basis
    statement: str             # verbatim carrier quote backing it, or ""
    item_numbers: list         # contractor line numbers
    item_descriptions: list
    dollars: float
    note: str


# Which carrier-statement kind would explain a given missing-item theme.
_THEME_STATEMENT = {"MATCHING": "MATCHING", "CODE": "ORDINANCE_CODE"}


def derive_hypotheses(carrier_statements, missing):
    """Map missing-item themes to a quoted exclusion, or to a labeled inference.

    Data-driven so it cannot fabricate: a theme's hypothesis is emitted only when
    items of that theme are actually missing, so a reason is never asserted for
    scope the carrier included. Items in no theme fall into one 'no stated reason'
    bucket rather than getting an invented explanation.
    """
    kinds = {s["kind"] for s in carrier_statements}
    quote_for = {}
    for s in carrier_statements:
        quote_for.setdefault(s["kind"], s["text"])

    buckets = {"MATCHING": [], "CODE": []}
    themed = set()
    for it in missing:
        for th in infer_themes(it.description):
            if th in buckets:
                buckets[th].append(it)
                themed.add(id(it))

    out = []
    for theme, items in buckets.items():
        if not items:
            continue
        quoted = _THEME_STATEMENT[theme] in kinds
        if theme == "MATCHING":
            note = ("The carrier excludes these siding, soffit, and fascia items for "
                    "matching; its estimate quotes the exclusion below." if quoted else
                    "These are siding, soffit, and fascia items a matching dispute "
                    "drops. The carrier's estimate states no matching exclusion. Ask "
                    "the carrier why each is out.")
        else:  # CODE
            note = ("The carrier's ordinance-or-law language covers these code items; "
                    "it is quoted below." if quoted else
                    "These are code-driven items: ice-and-water shield, drip edge, "
                    "and decking. The carrier cites no code or ordinance coverage. "
                    "Confirm code coverage applies.")
        out.append(DenialHypothesis(
            theme=theme, basis="quoted" if quoted else "inference",
            label="Quoted exclusion" if quoted else "Inference - verify",
            statement=quote_for.get(_THEME_STATEMENT[theme], "") if quoted else "",
            item_numbers=[i.number for i in items],
            item_descriptions=[i.description for i in items],
            dollars=round(sum(i.rcv for i in items), 2), note=note))

    rest = [it for it in missing if id(it) not in themed]
    if rest:
        out.append(DenialHypothesis(
            theme="UNEXPLAINED", basis="inference", label="No stated reason",
            statement="",
            item_numbers=[i.number for i in rest],
            item_descriptions=[i.description for i in rest],
            dollars=round(sum(i.rcv for i in rest), 2),
            note="The carrier's estimate states no exclusion that reaches these "
                 "items. Ask the carrier for the reason each is out."))
    out.sort(key=lambda h: (h.basis != "quoted", -h.dollars))
    return out


# --------------------------------------------------------------------------- #
# Coverage-sublimit hypothesis (a reason more approvals may not help)
# --------------------------------------------------------------------------- #

def _structure_split(items):
    """Sum RCV and depreciation over the main dwelling vs any secondary structure
    (barn, shed, detached garage...) a dwelling-extension sublimit would cap."""
    dwl_rcv = ext_rcv = dwl_dep = ext_dep = 0.0
    for it in items:
        if is_extension_item(it.section, it.description):
            ext_rcv += it.rcv
            ext_dep += it.deprec
        else:
            dwl_rcv += it.rcv
            dwl_dep += it.deprec
    return {"dwl_rcv": round(dwl_rcv, 2), "ext_rcv": round(ext_rcv, 2),
            "dwl_dep": round(dwl_dep, 2), "ext_dep": round(ext_dep, 2)}


def _money0(x):
    return f"${x:,.0f}"


def coverage_limit_hypothesis(carrier, contractor, missing, og=None):
    """Predict when a dwelling-extension / other-structures sublimit may cap the
    payout, so pushing for more approvals on the secondary structure does not help
    (and can hurt) the homeowner. Mathematically grounded on the structure split
    and, when the original estimate is present, the divergent approval rate.

    Returns a DenialHypothesis or None. Never asserts the limit (it lives on the
    declarations, not the estimate); it is always a labelled inference to verify.
    """
    ext_missing = [m for m in missing
                   if is_extension_item(getattr(m, "section", ""), m.description)]
    cs = _structure_split(carrier.items)
    xs = _structure_split(contractor.items)
    # Outstanding on the secondary structure from the structure RCV split (the
    # grand-total-style figure), not the noisier per-line sum: contractor scope on
    # that structure less what the carrier already carries there.
    ext_outstanding = round(max(0.0, xs["ext_rcv"] - cs["ext_rcv"]), 2)
    has_sublimit = bool(carrier.sublimit_coverages)
    has_ext = cs["ext_rcv"] > 0 or xs["ext_rcv"] > 0
    if not has_ext and not has_sublimit:
        return None

    # Divergent approval rate on the secondary structure (needs the original).
    frozen = False
    rate_note = ""
    if og is not None:
        os_ = _structure_split(og.items)
        ext_ask = xs["ext_rcv"] - os_["ext_rcv"]
        ext_appr = cs["ext_rcv"] - os_["ext_rcv"]
        dwl_ask = xs["dwl_rcv"] - os_["dwl_rcv"]
        dwl_appr = cs["dwl_rcv"] - os_["dwl_rcv"]
        ext_rate = ext_appr / ext_ask if ext_ask > 50 else None
        dwl_rate = dwl_appr / dwl_ask if dwl_ask > 50 else None
        if ext_rate is not None and ext_rate < 0.25 and \
                (dwl_rate is None or dwl_rate - ext_rate >= 0.20):
            frozen = True
            rate_note = (
                f"The carrier approved "
                f"{(dwl_rate * 100):.0f}% of your dwelling ask but "
                f"{(ext_rate * 100):.0f}% of your secondary-structure ask "
                f"({_money0(ext_appr)} of {_money0(ext_ask)}); its secondary-structure "
                f"total has not moved from the original estimate. ")

    # Gate: only raise this when there is real exposure or a clear frozen signal.
    if not frozen and ext_outstanding < 1500:
        return None

    sub = carrier.sublimit_coverages[0] if has_sublimit else ""
    cap_phrase = (f"the {sub} coverage" if sub else
                  "a dwelling-extension or other-structures sublimit")
    note = (
        rate_note +
        f"That structure sits under {cap_phrase}, a separate limit set at 10% of the "
        f"Coverage A dwelling limit on standard homeowner forms, and carries "
        f"{_money0(cs['ext_dep'])} of depreciation held until the work is done. "
        f"{_money0(ext_outstanding)} of the outstanding scope is on it. Past that "
        f"limit, added scope does not raise the payout, the depreciation above it is "
        f"unrecoverable, and the settlement on the structure drops to ACV. Confirm "
        f"the remaining limit before pursuing this scope.")

    label = ("Sublimit reached - confirm" if frozen else "Sublimit in play - confirm")
    return DenialHypothesis(
        theme="COVERAGE_LIMIT", basis="inference", label=label,
        statement=(f"Estimate carries a separate {sub} coverage." if sub else ""),
        item_numbers=[m.number for m in ext_missing],
        item_descriptions=[m.description for m in ext_missing],
        dollars=ext_outstanding, note=note)


# --------------------------------------------------------------------------- #
# Plain-language summary
# --------------------------------------------------------------------------- #

def build_narrative(recon):
    """Set recon.narrative: two or three plain sentences a reader can take in at a
    glance, with the coverage-sublimit warning called out. Deterministic (no model
    call); qualitative words are picked from the numbers. The statistical tiles
    stay below it for anyone verifying the math."""
    out = []
    clh = next((h for h in recon.hypotheses if h.theme == "COVERAGE_LIMIT"), None)

    if recon.mode == "effectiveness":
        pct = round(recon.effectiveness * 100)
        won = len(recon.approved_wins)
        out_count = sum(1 for s in recon.suggestions if s.status == "MISSING")
        out.append({"tone": "normal", "text":
            f"The contractor supplement adds {_money0(recon.ask_dollars)} of scope to the "
            f"carrier's original estimate. The carrier has picked up {_money0(recon.approved_dollars)}, "
            f"{pct}% of it. {_money0(recon.outstanding_dollars)} of scoped work is still out."})
        out.append({"tone": "normal", "text":
            f"{won} supplement items are now in the carrier estimate, checked in green. "
            f"{out_count} are missing and painted in blue on the carrier pages, each keyed "
            f"to the contractor line that carries it."})
        if clh:
            out.append({"tone": "caution", "text":
                f"One caution before pushing the rest. {_money0(clh.dollars)} of the outstanding "
                f"scope is on a secondary structure the carrier caps under a separate limit that "
                f"is already spent. Approvals there do not raise the payout; they drop that "
                f"structure to ACV and cut the homeowner's net. Confirm the limit first."})
    else:
        gap = round(recon.contractor_grand - recon.carrier_grand, 2)
        miss = [s for s in recon.suggestions if s.status == "MISSING"]
        miss_d = round(sum(s.dollars for s in miss), 2)
        flagged = sum(1 for s in recon.shared if s.quantity_delta > 1e-6)
        out.append({"tone": "normal", "text":
            f"The contractor scopes {_money0(recon.contractor_grand)} of work. The carrier "
            f"estimate stops at {_money0(recon.carrier_grand)}, short {_money0(gap)}."})
        line2 = (f"{len(miss)} line items worth {_money0(miss_d)} are in the contractor estimate "
                 f"and absent from the carrier's, painted in salmon on the carrier pages and "
                 f"keyed to the contractor line number.")
        if flagged:
            line2 += (f" The carrier also measured {flagged} shared "
                      f"line{'s' if flagged != 1 else ''} short of the contractor.")
        out.append({"tone": "normal", "text": line2})
        if clh:
            out.append({"tone": "caution", "text":
                f"One caution. {_money0(clh.dollars)} of the missing scope is on a secondary "
                f"structure the carrier caps under a separate limit. Past that limit the added "
                f"scope does not pay. Confirm the limit before pursuing it."})
    recon.narrative = out


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
            confidence="high", number=it.number, section=it.section,
            note="in contractor scope, absent from carrier"))

    # Shared items: every matched pair with its price and quantity breakdown, all
    # figures pulled from the two estimates. Grouped by category, largest RCV
    # difference first. (ci = contractor item, cr = carrier item.)
    shared = []
    for ci, cr in matched:
        shared.append(SharedItem(
            description=cr.description or ci.description,
            category=cr.category,
            carrier_number=cr.number,
            contractor_number=ci.number,
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

    hypotheses = derive_hypotheses(carrier.statements, missing)
    # Lead with the coverage-sublimit caution when present (two-file signal only).
    clh = coverage_limit_hypothesis(carrier, contractor, sugg, og=None)
    if clh:
        hypotheses.insert(0, clh)

    r = Recon(
        claimant=claimant, mode="reconciled", carrier_name=carrier.name,
        carrier_grand=carrier.grand_rcv, carrier_conf=carrier.confidence,
        carrier_ocr=carrier.ocr, contractor_name=contractor.name,
        contractor_grand=contractor.grand_rcv, contractor_conf=contractor.confidence,
        carrier_has_op=carrier.has_op, contractor_has_op=contractor.has_op,
        suggestions=sugg, shared=shared, bridge=bridge, est_recoverable=est,
        carrier_statements=carrier.statements, hypotheses=hypotheses)

    if carrier.items and not matched:
        r.notes.append("cross-platform pair (carrier and contractor use different "
                       "estimating software); line items do not name-match, so the "
                       "itemized list may repeat scope the carrier already covers. "
                       "Trust the RCV bridge total over the per-item list here.")
    cn = _confidence_note(carrier)
    if cn:
        r.notes.append(cn)
    build_narrative(r)
    return r


# --------------------------------------------------------------------------- #
# Effectiveness mode (three-way: original carrier, current carrier, contractor)
# --------------------------------------------------------------------------- #

def reconcile_effectiveness(og, carrier, contractor, claimant, playbook=None):
    """Measure how much of the contractor's supplement the carrier has approved.

    Roles:
      og         - the original carrier estimate; the baseline the supplement was
                   built on.
      carrier    - the current carrier estimate, after the supplement.
      contractor - the contractor supplement (the original plus the items we added).

    The current-carrier-vs-contractor reconciliation still supplies the outstanding
    scope (the MISSING suggestions), the under-measured shared items, the RCV
    bridge, and the hypotheses. This adds the grand-total approval math and the
    list of approved wins (current-carrier line items new since the original).

    Grand totals drive the headline because they are reliable to the cent; line
    matching drives only which items to paint.
    """
    r = reconcile_matched(carrier, contractor, claimant, playbook)
    r.mode = "effectiveness"
    r.og_name = og.name
    r.og_grand = og.grand_rcv
    r.ask_dollars = round(contractor.grand_rcv - og.grand_rcv, 2)
    r.approved_dollars = round(carrier.grand_rcv - og.grand_rcv, 2)
    r.outstanding_dollars = round(contractor.grand_rcv - carrier.grand_rcv, 2)
    r.effectiveness = (round(r.approved_dollars / r.ask_dollars, 4)
                       if r.ask_dollars > 0 else 0.0)

    # Approved wins: current-carrier line items not present in the original.
    _, approved_wins, _ = match_line_items(og.items, carrier.items)
    r.approved_wins = approved_wins

    # Recompute the sublimit hypothesis with the original estimate so the divergent
    # approval-rate signal (a frozen secondary structure) can be measured.
    r.hypotheses = [h for h in r.hypotheses if h.theme != "COVERAGE_LIMIT"]
    outstanding = [s for s in r.suggestions if s.status == "MISSING"]
    clh = coverage_limit_hypothesis(carrier, contractor, outstanding, og=og)
    if clh:
        r.hypotheses.insert(0, clh)

    r.notes.insert(0, "effectiveness is measured from grand totals (reliable to "
                      "the cent); the per-item lists use line matching and may not "
                      "sum to those totals exactly.")
    build_narrative(r)   # rebuild with the effectiveness numbers and sublimit signal
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
    build_narrative(r)
    return r
