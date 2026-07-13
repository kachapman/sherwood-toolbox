"""Reconcile a carrier estimate against the contractor scope and the playbook.

Two modes:

  * reconciled  -> a same-claimant contractor file exists. Line items are matched
                   and the RCV difference between the two files is bridged with an
                   exact identity (see rcv_bridge).
  * estimated   -> no contractor file. The playbook checklist of commonly-added
                   items projects the missing scope and O&P.

Suggestion tiers:
  MISSING      contractor item absent from carrier (reconciled mode, high conf)
  SUGGESTED    playbook item absent from carrier (estimated mode; conf ~ frequency)
  MISSING_OP   carrier applied no Overhead & Profit
  INFO         shared item where the contractor unit price is higher (advisory)
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .extract import infer_themes, is_extension_item
from .match import match_line_items, section_tokens


def base(it) -> float:
    # The line's pre-O&P, pre-tax dollars (quantity x unit_price). The bridge adds
    # op_gap and tax_gap on top, so base must EXCLUDE O&P and tax; it cannot use
    # it.rcv, whose per-line value carries a distributed share of O&P and tax on
    # contractor estimates (summing rcv would double-count them against op_gap /
    # tax_gap). Bid-item rows (asterisk/E markers) print a real per-unit price in
    # practice (e.g. '2 EA @ 3727.00'), so quantity x unit_price is the true line
    # total here, not an inflated re-multiplication.
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
    # Grade-revision pairing: when this missing line revises a carrier line (a renamed
    # replacement), the carrier line it replaces and the net price difference.
    replaces_number: int = 0
    replaces_desc: str = ""
    replaces_rcv: float = 0.0
    net_delta: float = 0.0


@dataclass
class ApprovedRevision:
    """A carrier line the current estimate raised over its original: the same item,
    a higher quantity or price. Counts as an approval because the carrier moved that
    line toward the contractor scope. All figures are as printed."""
    number: int
    description: str
    category: str
    unit: str
    quantity: float           # current-carrier quantity
    rcv: float                # current-carrier RCV
    from_quantity: float      # original-carrier quantity
    from_rcv: float           # original-carrier RCV
    delta: float              # current RCV - original RCV (the dollars approved on this line)
    contractor_quantity: float = 0.0  # matching contractor line, when found
    contractor_rcv: float = 0.0


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
    # The quantity shortfall to flag, netted across every line of this base: the
    # carrier can split a trade over several lines (two 1-EA window wraps) that
    # together meet a contractor line listing the same total, so the per-pair
    # quantity_delta above overstates it. Zero means the carrier already meets or
    # exceeds the contractor on this base; only a positive value is a real gap.
    net_quantity_gap: float = 0.0


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
    approved_wins: list = field(default_factory=list)  # current-carrier LineItems approved (added + revised)
    approved_added: list = field(default_factory=list)  # subset: brand-new current-carrier lines
    approved_revised: list = field(default_factory=list)  # ApprovedRevision: raised existing lines
    # Set when the original-vs-current line match cannot be trusted (a scanned/OCR
    # original whose line table did not parse). The approved_* sets above are then
    # blanked and the caller blocks the run; the grand-total approval math is kept.
    og_line_diff_unreliable: bool = False
    og_line_diff_reason: str = ""
    narrative: list = field(default_factory=list)  # plain-language summary [{text, tone}]
    # Section-total reconciliation: the outstanding per contractor section is the
    # difference of the printed section subtotals, so grade revisions (a renamed
    # replacement) net against the carrier line they replace instead of counting the
    # full RCV. Keyed by contractor section name.
    section_outstanding: dict = field(default_factory=dict)      # net $ per section
    section_contractor_total: dict = field(default_factory=dict)  # printed contractor RCV
    section_carrier_total: dict = field(default_factory=dict)     # mapped carrier RCV
    section_unattributed: float = 0.0  # carrier scope that mapped to no contractor section


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
    """Raise a policy-limit caution whenever a secondary structure (a detached
    building, shed, or garage) has denied or unapproved scope. A dwelling-extension
    / other-structures limit is separate from the main dwelling limit, so scope
    pushed past it does not raise the payout. Grounded on the structure split and,
    when the original estimate is present, the divergent approval rate.

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

    # Fire on any secondary-structure denial: a missing/unapproved item on such a
    # structure, or outstanding dollars there. A separate limit can quietly cap the
    # payout even on a small partial denial, so the caution is worth raising early.
    def _dollars(m):
        v = getattr(m, "dollars", None)
        return (getattr(m, "rcv", 0.0) if v is None else v) or 0.0
    ext_missing_rcv = round(sum(_dollars(m) for m in ext_missing), 2)
    amount = ext_outstanding if ext_outstanding >= 1 else ext_missing_rcv
    # No secondary-structure scope is missing or outstanding: nothing to caution.
    # A sublimit coverage merely *named* in the standard coverage recap (a
    # "BB-Other Structures $0.00" bucket) is not a limit in play, so has_sublimit
    # alone must not raise a "$0 of scope" warning.
    if not ext_missing and amount < 1:
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
                f"The carrier approved {(dwl_rate * 100):.0f}% of the dwelling ask but "
                f"{(ext_rate * 100):.0f}% of the secondary-structure ask "
                f"({_money0(ext_appr)} of {_money0(ext_ask)}); its secondary-structure "
                f"total has not moved from the original estimate. ")

    sub = carrier.sublimit_coverages[0] if has_sublimit else ""
    base = (
        f"{_money0(amount)} of the missing scope is on a secondary structure "
        f"(a detached building, shed, or garage). Check the policy for a separate "
        f"limit on that structure; a dwelling-extension or other-structures limit is "
        f"set at 10% of the Coverage A dwelling limit on standard homeowner forms. If "
        f"that limit applies, scope pushed past it does not raise the payout, so "
        f"confirm the remaining limit before pursuing those items.")
    extra = ""
    if has_sublimit:
        extra = (f" This estimate carries a separate {sub} coverage and holds "
                 f"{_money0(cs['ext_dep'])} of depreciation until the work is done; "
                 f"scope past the limit drops that structure's settlement to actual "
                 f"cash value, lowering the homeowner's net.")
    note = rate_note + base + extra

    label = ("Sublimit reached - confirm" if frozen else
             "Sublimit in play - confirm" if has_sublimit else
             "Check the policy limit")
    return DenialHypothesis(
        theme="COVERAGE_LIMIT", basis="inference", label=label,
        statement=(f"Estimate carries a separate {sub} coverage." if sub else ""),
        item_numbers=[m.number for m in ext_missing],
        item_descriptions=[m.description for m in ext_missing],
        dollars=amount, note=note)


# --------------------------------------------------------------------------- #
# Plain-language summary
# --------------------------------------------------------------------------- #

def build_narrative(recon):
    """Set recon.narrative: two or three plain sentences a reader can take in at a
    glance. Deterministic (no model call); qualitative words are picked from the
    numbers. The statistical tiles stay below it for anyone verifying the math."""
    out = []

    if recon.mode == "effectiveness":
        pct = round(recon.effectiveness * 100)
        n_add = len(recon.approved_added)
        n_rev = len(recon.approved_revised)
        out_count = sum(1 for s in recon.suggestions if s.status == "MISSING")
        out.append({"tone": "normal", "text":
            f"The contractor supplement is {_money0(recon.ask_dollars)} higher than the "
            f"carrier's original estimate. The carrier has approved {_money0(recon.approved_dollars)} "
            f"so far, or {pct}% of it. {_money0(recon.outstanding_dollars)} of scoped work is "
            f"still unapproved."})
        rev_clause = (f" and raised {n_rev} existing line{'s' if n_rev != 1 else ''} "
                      f"toward the contractor" if n_rev else "")
        out.append({"tone": "normal", "text":
            f"The carrier added {n_add} new supplement line{'s' if n_add != 1 else ''}{rev_clause}, "
            f"checked in green on the carrier pages. {out_count} contractor "
            f"line{'s are' if out_count != 1 else ' is'} still missing, painted in blue and each "
            f"keyed to the contractor line that carries it."})
    else:
        gap = round(recon.contractor_grand - recon.carrier_grand, 2)
        miss = [s for s in recon.suggestions if s.status == "MISSING"]
        flagged = sum(1 for s in recon.shared if s.net_quantity_gap > 1e-6)
        out.append({"tone": "normal", "text":
            f"The contractor estimate is {_money0(gap)} higher than the carrier's, "
            f"{_money0(recon.contractor_grand)} against {_money0(recon.carrier_grand)}."})
        line2 = (f"{len(miss)} line items are in the contractor estimate and missing from "
                 f"the carrier's, painted in salmon on the carrier pages and keyed to the "
                 f"contractor line number. Each section is totalled by its net difference, "
                 f"so a revised item nets against the carrier line it replaces.")
        if flagged:
            line2 += (f" The carrier also measured {flagged} shared "
                      f"line{'s' if flagged != 1 else ''} short of the contractor.")
        out.append({"tone": "normal", "text": line2})
    recon.narrative = out


# --------------------------------------------------------------------------- #
# Reconciled mode
# --------------------------------------------------------------------------- #

def map_and_diff_sections(carrier, contractor, matched):
    """Net outstanding per contractor section = its printed subtotal minus the
    carrier subtotal of the section it maps to. This nets out grade revisions (a
    renamed replacement) against the carrier line they replace, which a per-item sum
    cannot do. Carrier sections are mapped to contractor sections by majority vote of
    matched line items, with a token-overlap fallback for all-missing sections that
    have no matched items to vote. Returns (outstanding, contractor_totals,
    carrier_by_section, unattributed_carrier)."""
    kt = contractor.section_totals or {}         # contractor section -> printed RCV
    ct = carrier.section_totals or {}            # carrier section -> printed RCV
    if not kt:
        return {}, {}, {}, 0.0

    votes = defaultdict(Counter)                 # carrier section -> Counter(contractor section)
    for ci, cr in matched:                       # (contractor_item, carrier_item)
        if getattr(cr, "section", "") and getattr(ci, "section", ""):
            votes[cr.section][ci.section] += 1
    k_names = list(kt.keys())

    def map_carrier_sec(cs):
        v = votes.get(cs)
        if v:
            top = v.most_common()
            best_n = top[0][1]
            tied = [name for name, n in top if n == best_n]
            if len(tied) == 1:
                return tied[0]
            # Tie: prefer the contractor section whose name overlaps the carrier's,
            # so a carrier "Left Elevation" maps to contractor "Left Elevation" and
            # not "Back Elevation" (both share "elevation"). Without this the tie
            # breaks on insertion order and a whole elevation's subtotal is misrouted,
            # zeroing one section's net and inflating another's.
            toks = section_tokens(cs)
            return max(tied, key=lambda kn: len(toks & section_tokens(kn)))
        toks = section_tokens(cs)
        best, best_n = None, 0
        for kn in k_names:
            n = len(toks & section_tokens(kn))
            if n > best_n:
                best, best_n = kn, n
        return best

    carrier_for = defaultdict(float)
    unattributed = 0.0
    for cs, val in ct.items():
        s = map_carrier_sec(cs)
        if s is None:
            unattributed = round(unattributed + val, 2)
        else:
            carrier_for[s] = round(carrier_for[s] + val, 2)

    outstanding, carrier_by = {}, {}
    for s, tot in kt.items():
        carrier_by[s] = round(carrier_for.get(s, 0.0), 2)
        outstanding[s] = round(max(0.0, tot - carrier_for.get(s, 0.0)), 2)
    return outstanding, dict(kt), carrier_by, unattributed


def _rev_tokens(s):
    return {t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) >= 4}


def _within(a, b, frac=0.10):
    return a > 0 and b > 0 and abs(a - b) / max(a, b) <= frac


def pair_grade_revisions(carrier, contractor, missing_items, carrier_only):
    """Pair each grade-revised MISSING contractor line to the carrier line it
    replaces, so the report can show the per-item price difference.

    Primary (exact name): the line's superseded "SEE REVISION" original, matched in
    the same section, unit, and quantity-within-10%, whose base exactly names a
    carrier line. Fallback (guarded within-10%): a same-category, same-unit
    carrier-only line within 10% quantity that shares a description word, and only
    when it is the sole candidate; the word/category/unit guards keep it from pairing
    unrelated items by quantity coincidence (a corner post to a tear-off). Returns
    {contractor line number -> (carrier LineItem, net_delta)}."""
    superseded = [it for it in contractor.items if getattr(it, "superseded", False)]
    carr_by_base = {}
    for c in carrier.items:
        carr_by_base.setdefault(c.base, []).append(c)
    used_c, paired = set(), set()
    out = {}

    def take(r, c):
        used_c.add(id(c))
        paired.add(id(r))
        out[r.number] = (c, round(r.rcv - c.rcv, 2))

    # Pass 1: exact name via the superseded original.
    for s in superseded:
        c = next((x for x in carr_by_base.get(s.base, []) if id(x) not in used_c), None)
        if c is None:
            continue
        cands = [r for r in missing_items if id(r) not in paired
                 and r.section == s.section and r.unit == s.unit
                 and _within(r.quantity, s.quantity)]
        if cands:
            take(min(cands, key=lambda r: abs(r.quantity - s.quantity)), c)

    # Pass 2: guarded within-10% fallback.
    for r in missing_items:
        if id(r) in paired:
            continue
        cands = [c for c in carrier_only if id(c) not in used_c and c.base != r.base
                 and c.category == r.category and c.unit == r.unit
                 and _within(c.quantity, r.quantity)
                 and _rev_tokens(r.description) & _rev_tokens(c.description)]
        if len(cands) == 1:
            take(r, cands[0])
    return out


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

    # Grade revisions: a renamed replacement (corrugated -> ribbed) that the carrier
    # carries under the old name. Annotate the price difference on the suggestion.
    revisions = pair_grade_revisions(carrier, contractor, missing, carrier_only)
    for s in sugg:
        if s.number in revisions:
            c, delta = revisions[s.number]
            s.replaces_number, s.replaces_desc = c.number, c.description
            s.replaces_rcv, s.net_delta = c.rcv, delta

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
    # Net the under-measurement per base. The carrier can carry a trade across
    # several lines (two 1-EA window wraps) that together meet a contractor line
    # listing the same total, or carry more of a size the contractor lists once; a
    # per-pair quantity_delta then reads a shortfall that does not exist. Compute the
    # gap from base totals (contractor minus carrier) and hand it to the base's
    # shared lines largest-first, so the flags sum to the real shortfall and none is
    # flagged past it. A base the carrier meets or exceeds gets no flag.
    car_qty, con_qty = {}, {}
    for c in carrier.items:
        car_qty[c.base] = car_qty.get(c.base, 0.0) + c.quantity
    for it in contractor.items:
        con_qty[it.base] = con_qty.get(it.base, 0.0) + it.quantity
    base_of = {c.number: c.base for c in carrier.items}
    by_base = {}
    for s in shared:
        by_base.setdefault(base_of.get(s.carrier_number), []).append(s)
    for b, items in by_base.items():
        remaining = max(0.0, round(con_qty.get(b, 0.0) - car_qty.get(b, 0.0), 2))
        for s in sorted(items, key=lambda x: -x.quantity_delta):
            take = min(max(0.0, s.quantity_delta), remaining) if s.quantity_delta > 0 else 0.0
            s.net_quantity_gap = round(take, 2)
            remaining = round(remaining - take, 2)

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

    # Per-section outstanding from the printed section-subtotal difference (nets out
    # grade revisions). Headline dollars stay on the grand totals above.
    (r.section_outstanding, r.section_contractor_total,
     r.section_carrier_total, r.section_unattributed) = \
        map_and_diff_sections(carrier, contractor, matched)

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

# Trust thresholds for the original-vs-current line diff that drives the green
# "approved" checks. Signal A: the original must parse most of its own grand total
# into line items, or its line list is too incomplete to diff against. Signal B: the
# summed RCV of the "added" lines must stay within a factor (plus a small absolute
# margin, so small claims do not trip) of what the totals can explain, which is the
# net grand-total increase PLUS the scope the carrier removed (a revision can add
# new lines while dropping old ones). Either signal marks the diff unreliable.
OG_MIN_PARSE_RATIO = 0.80
ADDED_SUM_FACTOR = 1.5
ADDED_SUM_MARGIN = 500.0

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

    # Approved items = the supplement scope the carrier put into its current
    # estimate, and the user's definition is "added or revised": a brand-new line,
    # OR an existing line the carrier raised toward the contractor scope. Matching
    # og -> current, the unmatched current lines are the additions; matched pairs
    # whose RCV rose are the revisions. (match returns (current_item, og_item).)
    # No price guard here: this matches the carrier's original to its own current
    # estimate, where the same line can be re-priced by a wide margin between the two
    # (a genuine revision), unlike the cross-software carrier/contractor match.
    matched_oc, added, dropped = match_line_items(og.items, carrier.items,
                                                  price_guard=False)
    r.approved_added = list(added)

    # Index the contractor scope so a raised line can name the contractor line it
    # moved toward (evidence the revision is supplement-driven, not a price bump).
    con_by_base = {}
    for it in contractor.items:
        if not getattr(it, "superseded", False):
            con_by_base.setdefault(it.base, []).append(it)

    revised = []
    for cur, og_it in matched_oc:
        # A genuine revision changes the line's SCOPE: a different quantity or unit
        # price. When both are unchanged, the line is identical scope and any RCV
        # move is the carrier applying sales tax or O&P at the coverage level (which
        # some carriers distribute into per-line RCV, e.g. Quilatan). That is not an
        # approval and must not paint a green "raised" mark, or the per-item markup
        # diverges from the grand-total approval math that is reliable to the cent.
        qty_same = abs(cur.quantity - og_it.quantity) < 0.005
        price_same = abs(cur.unit_price - og_it.unit_price) < 0.005
        if qty_same and price_same:
            continue
        base_delta = round(cur.quantity * cur.unit_price
                           - og_it.quantity * og_it.unit_price, 2)
        if base_delta < 1.0:                  # only lines the carrier raised in scope
            continue
        delta = round(cur.rcv - og_it.rcv, 2)
        cq = cr = 0.0
        cand = con_by_base.get(cur.base) or []
        if cand:                              # closest contractor quantity
            best = min(cand, key=lambda c: abs(c.quantity - cur.quantity))
            cq, cr = best.quantity, best.rcv
        revised.append(ApprovedRevision(
            number=cur.number, description=cur.description, category=cur.category,
            unit=cur.unit, quantity=cur.quantity, rcv=cur.rcv,
            from_quantity=og_it.quantity, from_rcv=og_it.rcv, delta=delta,
            contractor_quantity=cq, contractor_rcv=cr))
    revised.sort(key=lambda x: -x.delta)
    r.approved_revised = revised

    # approved_wins drives the in-place green checks and the headline count: every
    # current-carrier line that is an approval (each added line + each raised line).
    revised_nums = {x.number for x in revised}
    r.approved_wins = list(added) + [it for it in carrier.items
                                     if it.number in revised_nums]

    # Trust guard: the approved_added / approved_wins / approved_revised sets above
    # all come from matching the current carrier against the ORIGINAL carrier. When
    # the original did not parse into a credible line list (a scanned/OCR original
    # whose totals read cleanly while the table body is garbled), that match is
    # meaningless: nearly every current line looks "added", so it must not paint
    # green "approved" checks. Two independent signals flag it; either one blanks the
    # line-diff sets and drives the block in routes.py. The grand-total approval math
    # (approved_dollars, ask_dollars, effectiveness) is unaffected and stays.
    added_sum = round(sum(it.rcv for it in added), 2)
    dropped_sum = round(sum(it.rcv for it in dropped), 2)
    # Gross additions are plausible up to the net grand increase PLUS the scope the
    # carrier removed: a revision can add new lines while dropping old ones, so the
    # net delta alone understates legitimate additions.
    plausible_added = max(r.approved_dollars, 0.0) + dropped_sum
    if og.parse_ratio < OG_MIN_PARSE_RATIO:
        r.og_line_diff_unreliable = True
        r.og_line_diff_reason = (
            f"the original carrier estimate parsed only {_money0(og.rcv_line_sum)} "
            f"of its {_money0(og.grand_rcv)} total (parse_ratio "
            f"{og.parse_ratio:.2f}); its line items cannot be trusted, so the "
            f"per-item approvals could not be identified")
    elif added and added_sum > plausible_added * ADDED_SUM_FACTOR + ADDED_SUM_MARGIN:
        r.og_line_diff_unreliable = True
        r.og_line_diff_reason = (
            f"the added-lines total ({_money0(added_sum)}) exceeds what the grand-total "
            f"increase ({_money0(r.approved_dollars)}) and the {_money0(dropped_sum)} of "
            f"scope the carrier removed can explain; the original-vs-current line match "
            f"is unreliable, so the per-item approvals could not be identified")
    if r.og_line_diff_unreliable:
        r.approved_added = []
        r.approved_wins = []
        r.approved_revised = []

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
