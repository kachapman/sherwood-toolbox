"""PDF -> structured estimate.

Carrier estimates and contractor files come from several platforms with
different line layouts:

  * Xactimate single-line   (contractor files; some carriers)
        N. <desc>  <qty> <UNIT>  <price> ... <(deprec)> <acv>
  * Xactimate multi-line     (narrow-column carriers: desc on one line,
        numeric columns wrapped onto the following 1-4 lines)
  * Symbility / Liberty Mutual
        N <desc>  <qty> $<price> <UNIT>  ... <RC> <deprec> <acv>
  * Image-only scans -> Tesseract OCR (flagged low confidence)

A layout-independent invariant holds on every priced line across all formats:

        RCV = ACV + Depreciation

where ACV is the last money token on the line/record and Depreciation is the
parenthesized money token. Unit price is the first money token after the
quantity. This avoids fragile positional column indexing.

Text extraction uses PyMuPDF (`fitz`) for both the native text layer and OCR, so
the tool carries no poppler dependency. Tesseract is optional: when it is absent
an image-only PDF yields no text and the caller reports a degrade message.
"""

from __future__ import annotations

import os
import re
import shutil
import statistics
from dataclasses import dataclass, field, asdict

import fitz

# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

UNITS = {
    "EA", "LF", "SF", "SY", "SQ", "CF", "CY", "BF", "GL", "GAL", "HR", "DA",
    "WK", "MO", "RM", "PR", "RL", "BX", "TON", "MI", "MSF", "MBF", "SP", "LB",
    "RO", "PC", "SET", "KIT", "CS",
}

ACTION_PREFIXES = [
    "R&R", "R & R", "D&R", "D & R", "Remove & Replace", "Detach & Reset",
    "Detach and Reset", "Remove", "Replace", "Install Only", "Install",
    "Detach", "Reset", "Tear off", "Tearoff", "Tear Out",
]
ACTION_PREFIXES.sort(key=len, reverse=True)

_WS = re.compile(r"\s+")


def normalize_desc(desc: str) -> str:
    d = re.sub(r"\*+", "", desc.strip())
    d = _WS.sub(" ", d).strip(" -.,")
    return d.lower()


def split_action(desc: str):
    d = desc.strip()
    for pref in ACTION_PREFIXES:
        if d.lower().startswith(pref.lower()):
            rest = d[len(pref):].lstrip(" -")
            if rest:
                return pref.upper().replace(" ", ""), rest
    return "", d


def base_key(desc: str) -> str:
    _, base = split_action(desc)
    return normalize_desc(base)


CATEGORY_KEYWORDS = [
    ("ROOFING", ["shingle", "ridge vent", "hip / ridge", "hip/ridge", "roofing felt",
                 "drip edge", "ice & water", "ice and water", "i&w", "starter", "rake",
                 "flashing - pipe", "pipe jack", "roof", "modified bitumen",
                 "valley metal", "step flashing", "counterflashing", "felt", "itel"]),
    ("SIDING", ["siding", "house wrap", "housewrap", "soffit", "fascia", "j-block",
                "j block", "corner post", "shutter", "wrap (air"]),
    ("GUTTERS", ["gutter", "downspout"]),
    ("PAINTING", ["paint", "prime", "stain", "seal/prime", "texture", "sand wood",
                  "caulk", "finish"]),
    ("ELECTRICAL", ["outlet", "switch", "light fixture", "spot light", "j-box",
                    "disconnect box", "low voltage", "receptacle", "meter",
                    "electrical", "satellite"]),
    ("PLUMBING", ["faucet", "hose bibb", "plumbing", "water heater", "spigot"]),
    ("HVAC", ["hvac", "heat, vent", "air cond", "furnace", "condenser", "a/c",
              "dryer vent", "rain cap", "exhaust"]),
    ("WINDOWS/DOORS", ["window", "door", "screen", "glazing", "storm door"]),
    ("CLEANING", ["clean", "pressure", "final cleaning", "debris", "haul"]),
    ("PERMITS/FEES", ["permit", "dumpster", "temporary toilet"]),
    ("ACCESS/SCAFFOLD", ["ladder", "scaffold", "jacks and plank", "lift", "staging"]),
    ("LABOR/GENERAL", ["labor minimum", "per hour", "installer", "roofer",
                       "general laborer", "supervisor"]),
]


def infer_category(desc: str) -> str:
    d = desc.lower()
    for cat, keys in CATEGORY_KEYWORDS:
        if any(k in d for k in keys):
            return cat
    return "OTHER"


# Themes tie a missing line item to a likely denial reason. An item can carry
# more than one theme. MATCHING items are the ones a "matching" exclusion tends
# to cut; CODE items are the ones an ordinance/code position tends to cut.
THEME_KEYWORDS = [
    ("MATCHING", ["siding", "house wrap", "housewrap", "soffit", "fascia",
                  "brick", "stone veneer", "veneer", "corner post", "shutter",
                  "wrap (air", "match"]),
    ("CODE", ["ice & water", "ice and water", "i&w", "drip edge", "sheathing",
              "decking", "plywood", "osb", "valley metal", "step flashing",
              "underlayment", "synthetic"]),
]


def infer_themes(desc: str) -> list:
    d = desc.lower()
    return [theme for theme, keys in THEME_KEYWORDS if any(k in d for k in keys)]


# --------------------------------------------------------------------------- #
# Token helpers
# --------------------------------------------------------------------------- #

# Money token, but NOT a percentage (e.g. '26.67%') and NOT an age/life ('8/30').
MONEY = re.compile(r"\(-?\$?[\d,]+\.\d{2}\)|-?\$?[\d,]+\.\d{2}(?!\s*%)")
QTY_UNIT = re.compile(r"([\d,]+\.\d{2})\s+([A-Za-z]{1,4})\b")
# Depreciation is set off by parentheses '(x)' or angle brackets '<x>' depending
# on the platform (Allstate uses parens, Smart Communications uses angle).
DEPREC_MARK = re.compile(r"[\(<]\$?([\d,]+\.\d{2})[\)>]")
# A revised line: the contractor leaves the original in place with its price cells
# replaced by the literal text "SEE REVISION" and adds the corrected line later. In
# layout text this lands at the end of the item row, so match it as a substring.
SEE_REVISION = re.compile(r"SEE\s+REVISION", re.I)

# A single "data column" token: money, quantity, age/life, percentage, unit, or
# one of the fixed condition words. Used to recognise wrapped numeric lines.
_DATA_TOKEN = re.compile(
    r"^(?:[\(<\[]?\$?-?[\d,]+\.\d{2}[\)>\]]?"      # money (any bracket)
    r"|\d+/\d+"                                     # age/life 15/30
    r"|-?\d+(?:\.\d+)?%?"                           # int / percent
    r"|\[%\]|%|<|>|\[|\])$"
)
_DATA_WORDS = {"AVG", "AVG.", "YRS", "YR", "NA", "AVE", "AVE."}

NOTE_PREFIXES = (
    "auto calculated", "options:", "bundle rounding", "component", "this line",
    "the above", "felt calculation", "includes", "quantities were", "see ",
    "- see", "depending upon", "market prices", "(msw", "eave", "valley",
    "note", "coverage", "estimate:", "reinspection", "roofplan", "roof area",
    "eaves:", "supplement", "labor minimums applied", "* ",
)


def _num(tok: str) -> float:
    t = tok.strip()
    neg = t.startswith("(")
    t = t.replace("$", "").replace(",", "").replace("(", "").replace(")", "")
    v = float(t) if t else 0.0
    return -v if neg else v


def _is_note(line: str) -> bool:
    s = line.strip().lower()
    if not s:
        return False
    return any(s.startswith(p) for p in NOTE_PREFIXES)


def _is_data_cont(line: str) -> bool:
    """A wrapped numeric-column line: every token is a data column or a unit/word."""
    s = line.strip()
    if not s or _is_note(line):
        return False
    # A numeric record line may carry condition/depreciation column glyphs the
    # per-token scan does not enumerate ('100% [M]' on a fully-depreciated line) or
    # lead with a Xactimate variable label. A 'qty UNIT ... money' signature marks
    # it as data unambiguously; without this accept the whole item is dropped, and a
    # line the original omits but the revision keeps reads as a false addition.
    qm = QTY_UNIT.search(s)
    if qm and qm.group(2).upper() in UNITS and MONEY.search(s[qm.end():]):
        return True
    toks = s.split()
    if not any(ch.isdigit() for ch in s):
        return False
    for t in toks:
        core = t.strip("*")                    # '*'/'*E' mark bid items and pricing
        if core == "" or core in ("E", "+"):
            continue
        if _DATA_TOKEN.match(core) or core.upper() in UNITS or core.upper() in _DATA_WORDS:
            continue
        # tolerate OCR noise / stray column glyphs: a numeric-ish token with few
        # letters (e.g. 'S655.84', '1,204,35') is still a data column, not prose.
        if any(c.isdigit() for c in core) and sum(c.islower() for c in core) <= 2 and len(core) <= 12:
            continue
        return False
    return True


def _is_desc_cont(line: str) -> bool:
    """A wrapped description fragment: starts lowercase, carries no money."""
    s = line.strip()
    if not s or len(s) > 55 or not s[0].islower():
        return False
    if MONEY.search(s) or _is_note(line):
        return False
    return True


def _is_superseded_desc_cont(line: str) -> bool:
    """A wrapped description fragment on a SEE REVISION row, where the continuation
    may start uppercase (e.g. "Agricultural", "Agricultural - galv"). Kept strict:
    a short, mostly-alphabetic fragment carrying no money, so the superseded line's
    base key stays complete enough to exact-match the carrier item it revises."""
    s = line.strip()
    if not s or len(s) > 40 or MONEY.search(s) or _is_note(line):
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9 ./&-]*$", s))


# --------------------------------------------------------------------------- #
# Line item
# --------------------------------------------------------------------------- #

@dataclass
class LineItem:
    number: int
    description: str
    norm_desc: str
    base: str
    action: str
    quantity: float
    unit: str
    unit_price: float
    rcv: float
    deprec: float
    acv: float
    category: str
    section: str = ""      # estimate section (e.g. "Front Elevation"), from Totals
    superseded: bool = False  # a "SEE REVISION" original, kept as a revision record (rcv=0)


# A section ends with a 'Totals: <name>' line (clean across Xactimate and
# Symbility, and present when section headers are noisy). An item's section is
# the first Totals line that follows it.
TOTALS_LINE = re.compile(r"^\s*Totals:\s*(.+?)(?:\s{2,}.*)?$")


def _section_marks(lines):
    """Ordered (line_index, section_name) for every 'Totals:' delimiter."""
    marks = []
    for i, ln in enumerate(lines):
        m = TOTALS_LINE.match(ln)
        if m:
            marks.append((i, m.group(1).strip()))
    return marks


def _section_for(idx, marks):
    for i, name in marks:
        if i > idx:
            return name
    return ""


def _finish_item(number, desc_parts, data_text, superseded=False):
    """Build a LineItem from a description and its numeric record, or None. A
    superseded ("SEE REVISION") row keeps its description and quantity but carries no
    price, so it is recorded with rcv=0 as a revision marker instead of being dropped."""
    qm = QTY_UNIT.search(data_text)
    if not qm:
        return None
    unit = qm.group(2).upper()
    if unit not in UNITS:
        return None
    after = data_text[qm.end():]
    monies = MONEY.findall(after)
    if not monies:
        if superseded or SEE_REVISION.search(data_text):
            desc = _WS.sub(" ", " ".join(p for p in desc_parts if p).strip())
            return LineItem(
                number=number, description=desc, norm_desc=normalize_desc(desc),
                base=base_key(desc), action=split_action(desc)[0],
                quantity=_num(qm.group(1)), unit=unit, unit_price=0.0, rcv=0.0,
                deprec=0.0, acv=0.0, category=infer_category(desc), superseded=True)
        return None
    vals = [_num(t) for t in monies]
    acv = vals[-1]
    pm = DEPREC_MARK.findall(data_text)
    deprec = _num(pm[-1]) if pm else 0.0
    rcv = round(acv + deprec, 2)
    unit_price = vals[0]
    desc = _WS.sub(" ", " ".join(p for p in desc_parts if p).strip())
    return LineItem(
        number=number,
        description=desc,
        norm_desc=normalize_desc(desc),
        base=base_key(desc),
        action=split_action(desc)[0],
        quantity=_num(qm.group(1)),
        unit=unit,
        unit_price=unit_price,
        rcv=rcv,
        deprec=round(deprec, 2),
        acv=round(acv, 2),
        category=infer_category(desc),
    )


HEADER_XACT = re.compile(r"^\s*\*?\s*(\d{1,3})\.\s+(\S.*?)\s*$")
HEADER_SYMB = re.compile(r"^\s*(\d{1,3})\s+([A-Za-z].*?)\s+[\d,]+\.\d{2}")


def _parse_xactimate(lines):
    """Unified single-line + multi-line Xactimate parser."""
    # header line indices
    idxs = [k for k, ln in enumerate(lines) if HEADER_XACT.match(ln)]
    marks = _section_marks(lines)
    items = []
    for a, start in enumerate(idxs):
        end = idxs[a + 1] if a + 1 < len(idxs) else len(lines)
        m = HEADER_XACT.match(lines[start])
        number = int(m.group(1))
        head_rest = m.group(2)

        # description begins on the header line, up to the qty/unit if present
        qm = QTY_UNIT.search(head_rest)
        desc_parts = [head_rest[:qm.start()] if qm else head_rest]
        record = [head_rest]
        # A revised original carries "SEE REVISION" in its price cells (usually on the
        # item row itself in layout text). Flagging it now lets the loop pick up an
        # uppercase description continuation (e.g. "Agricultural") that follows.
        superseded = bool(SEE_REVISION.search(head_rest))

        j = start + 1
        while j < end:
            ln = lines[j]
            if _is_note(ln):
                break
            if not ln.strip():
                if len(record) > 1:
                    break
                j += 1
                continue
            if SEE_REVISION.search(ln):
                # "SEE REVISION" on its own line (reading-order fallback): mark the
                # item and keep reading for a wrapped description fragment.
                superseded = True
                record.append(ln.strip())
            elif _is_desc_cont(ln) or (superseded and _is_superseded_desc_cont(ln)):
                desc_parts.append(ln.strip())
                record.append(ln.strip())
            elif _is_data_cont(ln):
                record.append(ln.strip())
            else:
                break
            j += 1

        item = _finish_item(number, desc_parts, " ".join(record), superseded=superseded)
        if item:
            item.section = _section_for(start, marks)
            items.append(item)
    return items


def _parse_symbility(lines):
    """Liberty Mutual / Symbility: 'N desc qty $price UNIT ... RC dep ACV'."""
    items = []
    marks = _section_marks(lines)
    n = len(lines)
    for i in range(n):
        m = HEADER_SYMB.match(lines[i])
        if not m:
            continue
        # collect this line + wrapped desc continuation lines
        record = [lines[i].strip()]
        desc_head = m.group(2)
        j = i + 1
        while j < n and _is_desc_cont(lines[j]):
            record.append(lines[j].strip())
            j += 1
        text = " ".join(record)
        # qty then $price then UNIT
        qm = re.search(r"([\d,]+\.\d{2})(?:\s+\([\d,]+\.\d{2}\))?\s+\$?([\d,]+\.\d{2})\s+([A-Za-z]{1,4})\b",
                       text)
        if not qm or qm.group(3).upper() not in UNITS:
            continue
        after = text[qm.end():]
        monies = MONEY.findall(after)
        if not monies:
            continue
        vals = [_num(t) for t in monies]
        acv = vals[-1]
        pm = DEPREC_MARK.findall(after)
        deprec = _num(pm[-1]) if pm else 0.0
        # Symbility shows explicit Depreciation as 2nd-to-last money col
        if not pm and len(vals) >= 3:
            deprec = vals[-2]
        rcv = round(acv + deprec, 2)
        desc = _WS.sub(" ", desc_head.strip())
        it = LineItem(
            number=int(m.group(1)), description=desc, norm_desc=normalize_desc(desc),
            base=base_key(desc), action=split_action(desc)[0],
            quantity=_num(qm.group(1)), unit=qm.group(3).upper(),
            unit_price=_num(qm.group(2)), rcv=rcv, deprec=round(deprec, 2),
            acv=round(acv, 2), category=infer_category(desc))
        it.section = _section_for(i, marks)
        items.append(it)
    return items


def detect_format(text: str) -> str:
    if "Total O&P" in text or re.search(r"^\s*\d+\s+\S.*\s\$[\d,]+\.\d{2}\s+[A-Z]{2}\b",
                                         text, re.M):
        return "symbility"
    return "xactimate"


def parse_items(text: str):
    lines = text.splitlines()
    if detect_format(text) == "symbility":
        items = _parse_symbility(lines)
        if items:
            return items, "symbility"
    return _parse_xactimate(lines), "xactimate"


# --------------------------------------------------------------------------- #
# Totals / O&P / recap
# --------------------------------------------------------------------------- #

# Grand RCV lives in one of three places depending on the carrier's platform;
# see grand_rcv() for the prioritized cascade. RCV_LINE is tight on purpose: only
# spaces / a colon / a '$' may sit between the phrase and the amount, so the
# legend page ("Replacement Cost Value (RCV) - The estimated cost of...") that
# some carriers print does not leak a stray number into the total.
RCV_LINE = re.compile(r"Replacement Cost Value\s*:?\s*\$?\s*([\d,]+\.\d{2})", re.I)
# Allstate-style "Loss Recap Summary": a grand 'TOTAL $x' row (all-caps TOTAL
# followed immediately by a $-amount, never 'TOTAL ROOFING $x' category rows).
RCV_TOTAL_ROW = re.compile(r"^\s*TOTAL\s+\$([\d,]+\.\d{2})", re.M)
LINE_ITEM_TOTALS_ROW = re.compile(r"Line Item Total[s]?:[^\n]*")
NET_CLAIM = re.compile(r"Net Claim[^\d\$]*\$?\s*([\d,]+\.\d{2})", re.I)
LINE_ITEM_TOTAL = re.compile(r"Line Item Total[s]?[^\d\$]*\$?\s*([\d,]+\.\d{2})", re.I)
TAX_LINE = re.compile(r"Sales Tax[^\d\$]*\$?\s*([\d,]+\.\d{2})", re.I)
OVERHEAD_AMT = re.compile(r"^\s*Overhead\b[^\n]*?([\d,]+\.\d{2})\s*$", re.M)
PROFIT_AMT = re.compile(r"^\s*Profit\b[^\n]*?([\d,]+\.\d{2})\s*$", re.M)

_MONEY_TOK = re.compile(r"[\d,]+\.\d{2}")


def _amts(rx, text):
    return [float(x.replace(",", "")) for x in rx.findall(text)]


def _fnum(s):
    return float(s.replace(",", ""))


def _rcv_from_row(nums):
    """The RCV column of a totals/recap row: the value V with a following
    depreciation D and actual-cash-value A such that V - D = A. Returns the largest
    such V, or None when the pattern is absent (money-column count varies by carrier:
    3, 4, or 5 columns, so a fixed index is wrong)."""
    best = None
    for i in range(len(nums) - 2):
        V, D, A = nums[i], nums[i + 1], nums[i + 2]
        if V > 0 and abs((V - D) - A) < 0.02 and (best is None or V > best):
            best = V
    return best


def _section_totals(lines):
    """Printed RCV subtotal per leaf section, from the plural 'Totals: <name>' lines
    (the same delimiter used for section names; singular 'Total:' rollups are
    excluded, so nothing is double-counted). Duplicate leaf names (e.g. an empty
    'Front Elevation' under one structure and a real one under another) are summed."""
    out = {}
    for ln in lines:
        m = TOTALS_LINE.match(ln)
        if not m:
            continue
        nums = [_fnum(x) for x in _MONEY_TOK.findall(ln)]
        rcv = _rcv_from_row(nums)
        if rcv is None:
            rcv = max(nums) if nums else 0.0
        out[m.group(1).strip()] = round(out.get(m.group(1).strip(), 0.0) + rcv, 2)
    return out


# Revised / supplement estimates append a change-summary *tail* that reprints TOTAL
# and 'Replacement Cost Value $x' lines for a net change: a 'Supplement ACV' /
# 'Supplement Details' / 'Net Change For Supplement' summary (a 'TOTAL $271.15') and
# a 'Payment Recap' that folds prior payments back in (a 'TOTAL $12,279.23'). The
# tail is cut before any total is read, so its delta figures cannot outrank the
# grand line. This is a document-tail cut: nothing after the first marker is a
# grand figure, so it is safe to apply to the scalar reads as well.
_SUPPLEMENT_MARKERS = re.compile(
    r"Supplement ACV|Supplement Details|Net Change For Supplement|"
    r"SUBTOTAL:\s*(?:ADDED|CHANGED)|Payment Recap", re.I)

# A 'Paid When Incurred' coverage block reprints an already-included item's RCV
# (Robinson's '$933.62'), which the per-coverage RCV summation would otherwise add
# as if it were a new coverage. Its header is a section line ending in the phrase,
# never the 'Total Paid When Incurred  933.62' summary line (which ends in a number)
# nor the 'Replacement Cost Value  Paid When Incurred ...' column header. This block
# can sit mid-estimate, before the grand tax/O&P recap, so it is cut ONLY for the
# grand-RCV summation, not for the scalar reads.
_PWI_HEADER = re.compile(r"^[^\n]*\bPaid When Incurred[ \t]*$", re.I | re.M)


def _strip_supplement(text: str) -> str:
    """Text with the supplement / change-summary tail removed (everything from the
    first such marker on). Returns the text unchanged when no marker is present, so
    ordinary and multi-coverage estimates are unaffected."""
    m = _SUPPLEMENT_MARKERS.search(text)
    return text[:m.start()] if m else text


# A coverage summary block prints 'Line Item Total <x>' ... 'Replacement Cost
# Value $<rcv>' once per coverage. Anchoring the RCV read to that block (rather than
# a bare phrase) keeps legend sentences and per-line echoes out, and lets a
# multi-coverage grand be summed as the carrier itself totals it.
_LINE_ITEM_TOTAL_ANCHOR = re.compile(r"Line Item Total\b", re.I)
_PWI_MARK = re.compile(r"Paid When Incurred", re.I)


def _rcv_triples(text: str):
    """Every value V on a line that participates in an RCV = ACV + Depreciation
    triple: three consecutive money magnitudes (V, D, A) with V - D == A and V the
    largest. The layout-independent signature of a totals/recap RCV column, true of
    Allstate, USAA, State Farm and Symbility recap rows alike."""
    out = []
    for ln in text.splitlines():
        mags = [abs(_num(m.group(0))) for m in MONEY.finditer(ln)]
        for i in range(len(mags) - 2):
            V, D, A = mags[i], mags[i + 1], mags[i + 2]
            if V > 100 and D >= 0 and A >= 0 and V >= D and abs((V - D) - A) < 0.02:
                out.append(round(V, 2))
    return out


def _coverage_blocks(text: str):
    """Per-coverage RCV summary values as (value, is_paid_when_incurred). A value is
    counted only when a 'Line Item Total' line sits just above it (a real coverage
    summary, not a legend), and is flagged PWI when a 'Total Paid When Incurred' line
    sits just below (a held-back bucket the carrier excludes from the recoverable
    grand). Near-duplicate values within a few lines are page-break echoes, counted
    once."""
    lines = text.splitlines()
    blocks, last = [], {}
    for i, ln in enumerate(lines):
        m = RCV_LINE.search(ln)
        if not m:
            continue
        if not any(_LINE_ITEM_TOTAL_ANCHOR.search(lines[j])
                   for j in range(max(0, i - 8), i)):
            continue
        val = _fnum(m.group(1))
        if val in last and i - last[val] <= 4:      # page-break echo of same block
            last[val] = i
            continue
        last[val] = i
        pwi = any(_PWI_MARK.search(lines[j]) for j in range(i + 1, min(i + 4, len(lines))))
        blocks.append((round(val, 2), pwi))
    return blocks


def grand_rcv(text: str, line_sum: float) -> float:
    """The estimate's grand Replacement Cost Value (includes tax and O&P).

    Verified across the sample corpus to land on the recap total to the cent
    (Gritzman 29,114.57, Esposito 36,445.82, Diaz 12,618.27, ...). Sources, tried
    most-authoritative first:

      1. A grand 'TOTAL $x' recap row (Allstate 'Loss Recap Summary'), taken only
         when it is at least the parsed line-item RCV sum. The grand adds tax and
         O&P on top of the line items, so it never falls below their sum; the floor
         rejects a supplement's small net-change 'TOTAL $271.15' row.
      2. The larger of the per-coverage RCV sum (excluding Paid-When-Incurred
         buckets) and the largest RCV = ACV + Depreciation recap triple. The
         coverage sum totals a multi-coverage estimate the way the carrier does and
         carries coverage-level tax (Allstate); the triple is the printed grand
         where per-line RCV already includes O&P and tax (USAA/State Farm) and a
         cross-check that a missed coverage does not undercount. This replaces the
         old sum-of-distinct-'Replacement Cost Value' logic, which a blanket
         Paid-When-Incurred cut truncated to the first coverage (Souser revised
         read 42,387 instead of 49,464).
      3. The 'Line Item Totals:' row (identity V - D = A), for carriers that print
         no labelled 'Replacement Cost Value' line.

    Falls back to the parsed line-item RCV sum when none of the above is present.
    """
    body = _strip_supplement(text)

    # 1. Allstate 'Loss Recap Summary' grand TOTAL row.
    for m in RCV_TOTAL_ROW.finditer(body):
        v = _fnum(m.group(1))
        if v >= line_sum - 0.02:
            return round(v, 2)

    # 2. Coverage sum (PWI excluded) cross-checked with the largest recap triple.
    blocks = _coverage_blocks(body)
    cov_excl = round(sum(v for v, p in blocks if not p), 2)
    if cov_excl > 0:
        triples = _rcv_triples(body)
        triple = round(max(triples), 2) if triples else 0.0
        return max(cov_excl, triple)

    # 3. The 'Line Item Totals:' row identity, else the largest recap triple.
    best = None
    for row in LINE_ITEM_TOTALS_ROW.findall(body):
        nums = [_fnum(x) for x in _MONEY_TOK.findall(row)]
        r = _rcv_from_row(nums)
        if r is not None and (best is None or r > best):
            best = r
        if best is None and nums:
            best = max(nums)
    if best is not None:
        return round(best, 2)

    triples = _rcv_triples(body)
    if triples:
        return round(max(triples), 2)
    return line_sum


def detect_op(text: str):
    oh = _amts(OVERHEAD_AMT, text)
    pr = _amts(PROFIT_AMT, text)
    overhead = max(oh) if oh else 0.0
    profit = max(pr) if pr else 0.0
    return (overhead > 0 or profit > 0), overhead, profit


def parse_recap(text: str):
    recap = {}
    in_recap = False
    row = re.compile(r"^\s*([A-Z][A-Z &/,\-\.]{2,40}?)\s+([\d,]+\.\d{2})\s+\d")
    for ln in text.splitlines():
        if "Recap by Category" in ln:
            in_recap = True
            continue
        if in_recap:
            if ln.strip().startswith("Grand Total") or ln.strip() == "Total":
                in_recap = False
                continue
            m = row.match(ln)
            if m and m.group(1).strip().upper() not in ("O&P ITEMS", "TOTAL"):
                recap[m.group(1).strip()] = float(m.group(2).replace(",", ""))
    return recap


# --------------------------------------------------------------------------- #
# Carrier coverage statements (verbatim rationale the estimate prints)
# --------------------------------------------------------------------------- #

# Each pattern is deliberately narrow: a coverage limitation only, not routine
# boilerplate. Kinds: MATCHING (the matching exclusion), DEPRECIATION_ACV (roof
# settled at actual cash value / a depreciation schedule), ORDINANCE_CODE
# (ordinance-or-law / code-upgrade language), POLICY_EXCLUSION (a Section-N
# exclusions block). These are quoted, never paraphrased.
STATEMENT_PATTERNS = [
    ("MATCHING", re.compile(
        r"matching.*(exclusion|excluded|does not cover|undamaged|not covered|"
        r"not damaged)|(exclusion|excluded|undamaged).*matching", re.I)),
    ("DEPRECIATION_ACV", re.compile(
        r"actual cash value only|non-?recoverable depreciation|"
        r"loss settlement selection form|roof schedule", re.I)),
    ("ORDINANCE_CODE", re.compile(
        r"ordinance or law|\bordinance\b|code upgrade|building code|"
        r"bring.{0,12}up to code", re.I)),
    ("POLICY_EXCLUSION", re.compile(
        r"coverage exclusions|we do not insure for loss|"
        r"the following exclusions apply", re.I)),
]


def _is_prose(line: str) -> bool:
    """A narrative sentence, not a line-item row, header, or numeric column."""
    s = line.strip()
    if not s or MONEY.search(s):
        return False
    if HEADER_XACT.match(line) or HEADER_SYMB.match(line):
        return False
    return sum(c.isalpha() for c in s) >= 12


def extract_statements(text: str) -> list:
    """Quotes of the coverage limitations the estimate states, each tagged with a
    kind. Captures the matching prose line plus continuation lines so a sentence
    reads whole, then skips past the consumed lines so a repetitive paragraph
    yields one clean quote rather than several overlapping fragments. Deduped.
    Returns [{'kind': str, 'text': str}]."""
    lines = text.splitlines()
    n = len(lines)
    out, seen = [], set()
    i = 0
    while i < n:
        ln = lines[i]
        if not _is_prose(ln):
            i += 1
            continue
        hit = next((kind for kind, rx in STATEMENT_PATTERNS if rx.search(ln)), None)
        if not hit:
            i += 1
            continue
        parts = [ln.strip()]
        j = i + 1
        while (j < n and j <= i + 3 and _is_prose(lines[j])
               and not parts[-1].rstrip().endswith((".", ":", ")"))):
            parts.append(lines[j].strip())
            j += 1
        quote = re.sub(r"\s{2,}", " ", " ".join(parts)).strip()
        key = (hit, quote[:80].lower())
        if key not in seen:
            seen.add(key)
            out.append({"kind": hit, "text": quote})
        i = j          # skip consumed lines; no overlapping re-capture
    return out


# --------------------------------------------------------------------------- #
# Text extraction (native + OCR), both via PyMuPDF
# --------------------------------------------------------------------------- #

ROW_OVERLAP = 0.5      # min vertical overlap to treat two words as one row


def _page_layout_text(page) -> str:
    """Reconstruct pdftotext-`-layout`-style text from a page's words.

    PyMuPDF's plain `get_text("text")` emits reading order, which drops each
    summary amount onto its own line (splitting an 'Overhead' label from its
    value) and scrambles Symbility's column grid. The parser was tuned against
    poppler's row-aligned output, so we rebuild that: cluster words into rows by
    vertical overlap, then lay each row out on a character grid using the page's
    median glyph width. Adjacent words stay single-spaced (so phrases like
    'Replacement Cost Value' match intact); real column gaps expand, exactly as
    `pdftotext -layout` does. Verified to reproduce the CLI figures to the cent.
    """
    words = page.get_text("words")
    if not words:
        return ""
    widths = [(w[2] - w[0]) / len(w[4]) for w in words if w[4].strip()]
    cw = max(statistics.median(widths), 3.0) if widths else 6.0

    words.sort(key=lambda w: (round(w[1], 1), w[0]))
    rows = []
    for w in words:
        y0, y1 = w[1], w[3]
        best, best_ov = None, 0.0
        for row in rows:
            ov = min(y1, row["y1"]) - max(y0, row["y0"])
            h = min(y1 - y0, row["y1"] - row["y0"])
            frac = ov / h if h > 0 else 0.0
            if frac > best_ov:
                best, best_ov = row, frac
        if best is not None and best_ov >= ROW_OVERLAP:
            best["ws"].append(w)
            best["y0"] = min(best["y0"], y0)
            best["y1"] = max(best["y1"], y1)
        else:
            rows.append({"y0": y0, "y1": y1, "ws": [w]})

    rows.sort(key=lambda r: r["y0"])
    lines = []
    for row in rows:
        ws = sorted(row["ws"], key=lambda w: w[0])
        line = ""
        prev_x1 = None
        for w in ws:
            x0, x1, word = w[0], w[2], w[4]
            if prev_x1 is None:
                line = " " * int(round(x0 / cw)) + word
            else:
                spaces = max(1, int(round((x0 - prev_x1) / cw)))
                line += " " * spaces + word
            prev_x1 = x1
        lines.append(line)
    return "\n".join(lines)


# Pages that are printed inside a carrier estimate but are not part of its scope,
# and must never be parsed for line items or totals. The Allstate "National
# Catastrophe Team" (and similar) estimates append a two-page "Your guide to
# reading your adjuster summary" against a fictitious insured (John Smith, 1234 Oak
# Street, Anytown) with sample line items (a refrigerator, a coffee table, a
# Samsung TV, a Sony DVD player). Parsing that page invents scope that is not in the
# claim and misreads the sample's own totals as the estimate's. Detected by the
# guide header, or by two independent canned-placeholder hits, so a real page is
# never dropped.
_SAMPLE_HEADER = re.compile(r"guide\s+to\s+reading\s+your", re.I)
_SAMPLE_PLACEHOLDER = re.compile(
    r"john\s+smith|1234\s+oak\s+street|any\s*town,?\s*any\s*state|"
    r"1234567890|coffeetable|gie16gshss", re.I)


def _is_boilerplate_page(page_text: str) -> bool:
    """True for a sample/legend/guide page that prints placeholder scope. Whitespace
    is collapsed first because the layout grid letter-spaces the guide's title."""
    flat = _WS.sub(" ", page_text or "")
    if _SAMPLE_HEADER.search(flat):
        return True
    return len({m.group(0).lower() for m in _SAMPLE_PLACEHOLDER.finditer(flat)}) >= 2


# A page worth keeping in a stripped training copy: it carries line items, a totals
# / recap / coverage-summary row, or the carrier's coverage language. Everything
# else in an estimate PDF is a photo sheet, a sketch/diagram, a blank, or the sample
# guide page, none of which the parser reads.
_KEEP_KEYWORDS = ("Totals:", "Total:", "Line Item Total", "Recap by",
                  "Replacement Cost Value", "Net Claim", "Summary for",
                  "Grand Total", "Coverage")


def _page_image_fraction(page) -> float:
    """Fraction of the page area covered by embedded raster images (a photo sheet
    runs high; a priced page is near zero)."""
    try:
        blocks = page.get_text("rawdict").get("blocks", [])
    except Exception:
        return 0.0
    area = 0.0
    for b in blocks:
        if b.get("type") == 1 and b.get("bbox"):
            x0, y0, x1, y1 = b["bbox"]
            area += max(0.0, (x1 - x0)) * max(0.0, (y1 - y0))
    parea = page.rect.width * page.rect.height
    return area / parea if parea else 0.0


def classify_page(page):
    """Classify one PDF page as ('keep', kind) or ('strip', kind).

    Estimate content is kept first, so a priced page that also carries a logo or a
    dense sketch is never mistaken for a photo/diagram sheet. Only pages with no
    line items and no summary text are eligible to strip: the sample guide page,
    photo sheets (a large embedded image), vector sketches (a dense drawing with no
    priced rows), and blanks.
    """
    raw = page.get_text("text")
    lay = _page_layout_text(page)
    n_items = sum(1 for ln in lay.splitlines()
                  if HEADER_XACT.match(ln) or HEADER_SYMB.match(ln))
    if not _is_boilerplate_page(raw) and not _is_boilerplate_page(lay):
        if n_items >= 1:
            return "keep", "items"
        if any(k in raw for k in _KEEP_KEYWORDS) or extract_statements(lay):
            return "keep", "totals"
    if _is_boilerplate_page(raw) or _is_boilerplate_page(lay):
        return "strip", "sample"
    if _page_image_fraction(page) >= 0.15:
        return "strip", "photo"
    try:
        n_draw = len(page.get_drawings())
    except Exception:
        n_draw = 0
    if n_draw >= 120:
        return "strip", "sketch"
    if len(_WS.sub("", raw)) < 15:
        return "strip", "blank"
    return "keep", "text"


def estimate_page_indexes(path: str):
    """0-based indexes of the pages worth keeping in a stripped copy of `path`,
    with a per-kind tally. Returns (keep_indexes, counts)."""
    keep, counts = [], {}
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            action, kind = classify_page(page)
            counts[kind] = counts.get(kind, 0) + 1
            if action == "keep":
                keep.append(i)
    return keep, counts


def _extract_text(path: str) -> str:
    """Native text layer via PyMuPDF, row-reconstructed to mimic poppler's
    `pdftotext -layout`. Replaces the poppler shell-out with no dependency. Sample
    "guide to reading" pages with placeholder scope are dropped before parsing."""
    try:
        with fitz.open(path) as doc:
            pages = []
            for page in doc:
                lay = _page_layout_text(page)
                if _is_boilerplate_page(page.get_text("text")) or \
                        _is_boilerplate_page(lay):
                    continue
                pages.append(lay)
            return "\n".join(pages)
    except Exception:
        return ""


def _tessdata_dir():
    """Locate the Tesseract language-data directory, or None. PyMuPDF's OCR
    needs this path; it is not always exported as TESSDATA_PREFIX."""
    if shutil.which("tesseract") is None:
        return None
    try:
        td = fitz.get_tessdata()
    except Exception:
        td = None
    return td or os.environ.get("TESSDATA_PREFIX") or None


# OCR of an image-only PDF is by far the heaviest path (full-page rasterisation
# at DPI, then Tesseract): ~2.5 s and tens of MB per page at 300 DPI. On shared
# server hardware behind a proxy timeout that can dominate a request, so these
# env knobs bound it. Defaults preserve the local desktop behaviour.
#   TOOLBOX_RECONCILER_OCR=0            disable OCR (image-only PDFs then degrade
#                                       to the "re-export as a text PDF" message)
#   TOOLBOX_RECONCILER_OCR_DPI=150      lower render DPI (quarter the pixels, work,
#                                       and memory of 300; still legible for OCR)
#   TOOLBOX_RECONCILER_OCR_MAX_PAGES=8  cap the pages OCR'd per file
def _env_int(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default


def _ocr_enabled() -> bool:
    return (os.environ.get("TOOLBOX_RECONCILER_OCR", "1").strip().lower()
            not in ("0", "false", "no", "off"))


def _tesseract_available() -> bool:
    """True when OCR is enabled and Tesseract with its language data is reachable.
    Tesseract is an optional dependency; absent it, image-only PDFs yield empty
    text."""
    return _ocr_enabled() and _tessdata_dir() is not None


def _ocr(path: str) -> str:
    """OCR an image-only PDF with PyMuPDF's built-in Tesseract bridge, bounded by
    the env knobs above. Returns empty when OCR is disabled/unavailable or fails."""
    if not _ocr_enabled():
        return ""
    td = _tessdata_dir()
    if not td:
        return ""
    dpi = _env_int("TOOLBOX_RECONCILER_OCR_DPI", 300)
    max_pages = _env_int("TOOLBOX_RECONCILER_OCR_MAX_PAGES", 0)   # 0 = all pages
    parts = []
    try:
        with fitz.open(path) as doc:
            for i, page in enumerate(doc):
                if max_pages and i >= max_pages:
                    break
                tp = page.get_textpage_ocr(full=True, dpi=dpi, tessdata=td)
                parts.append(page.get_text(textpage=tp))
    except Exception:
        return ""
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Secondary structures and coverage sublimits
# --------------------------------------------------------------------------- #

# A dwelling-extension / other-structures sublimit covers structures apart from
# the main dwelling (a barn, shed, detached garage, pole building...) under a
# separate, smaller limit. Classify a line item to that structure by its section
# name, or by materials that appear only on such a building.
EXT_SECTION = re.compile(
    r"barn|shed|garage|out\s*building|pole|machine shed|silo|coop|detached|"
    r"carport|stable|arena|grain|corn crib|\bshop\b", re.I)
EXT_DESC = re.compile(
    r"metal roof|ribbed|wall/roof panel|r-?panel|corrugated|purlin|closure strip|"
    r"metal building|pole barn", re.I)
# "garage door", "garage floor", "garage door opener", "(garage) door" name a
# dwelling component, not a detached garage; an attached garage is Coverage A, so
# these must not read as secondary-structure scope. \W+ spans the parenthesis and
# space in "Overhead (garage) door opener".
_DWELLING_COMPONENT = re.compile(r"garage\W+(?:door|floor|opener|slab)", re.I)


def is_extension_item(section: str, description: str) -> bool:
    """True when a line item belongs to a secondary structure a dwelling-extension
    / other-structures sublimit covers, rather than the main dwelling. The structure
    name (barn, shed, detached garage) is matched in either the section or the
    description; metal-building materials count only in the description. A "garage
    door / floor" description is a dwelling component and does not count."""
    sec, desc = section or "", description or ""
    if EXT_SECTION.search(sec) or EXT_DESC.search(desc):
        return True
    m = EXT_SECTION.search(desc)
    if not m:
        return False
    # A structure word in the description names the structure unless it is a
    # dwelling component like "garage door" (attached garage = Coverage A).
    if m.group(0).lower() == "garage" and _DWELLING_COMPONENT.search(desc):
        return False
    return True


# A separate, smaller coverage the estimate carves out: State Farm's "Dwelling
# Extension", an ISO "Other Structures" / "Coverage B". Its presence means part of
# the loss is capped by a limit distinct from the main dwelling limit.
SUBLIMIT_COVERAGE = re.compile(r"(Dwelling Extension|Other Structures|Coverage\s+B\b)", re.I)


def detect_sublimit_coverages(text: str) -> list:
    """Distinct sublimit-coverage names the estimate prints (deduped, canonical)."""
    seen, out = set(), []
    for m in SUBLIMIT_COVERAGE.finditer(text):
        s = re.sub(r"\s+", " ", m.group(1).strip())
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s.title() if s.isupper() or s.islower() else s)
    return out[:3]


@dataclass
class Estimate:
    path: str
    name: str
    role: str
    ocr: bool
    fmt: str = "xactimate"
    items: list = field(default_factory=list)
    grand_rcv: float = 0.0
    rcv_line_sum: float = 0.0
    net_claim: float = 0.0
    line_item_total: float = 0.0
    sales_tax: float = 0.0
    has_op: bool = False
    overhead: float = 0.0
    profit: float = 0.0
    recap: dict = field(default_factory=dict)
    parse_ratio: float = 1.0       # parsed line RCV / grand RCV
    confidence: str = "high"       # 'high' | 'medium' | 'low'
    image_only: bool = False       # native text layer was empty (a scan)
    statements: list = field(default_factory=list)  # quoted coverage limitations
    sublimit_coverages: list = field(default_factory=list)  # dwelling extension / other structures
    section_totals: dict = field(default_factory=dict)  # leaf section name -> printed RCV subtotal

    def to_dict(self):
        d = asdict(self)
        d["items"] = [asdict(it) for it in self.items]
        return d


def extract_estimate(path: str, role: str) -> Estimate:
    text = _extract_text(path)
    ocr = False
    image_only = False
    if len(re.sub(r"\s+", "", text)) < 40:
        # No usable native text layer: an image-only scan. OCR is mothballed for
        # now (too heavy for the current shared server hardware); the file is
        # flagged image_only and the caller warns the user it cannot be processed.
        # Re-enable by uncommenting the OCR call below once the hardware improves;
        # the _ocr() logic and its env knobs are kept intact.
        image_only = True
        # ocr_text = _ocr(path)
        # if ocr_text.strip():
        #     text = ocr_text
        #     ocr = True

    items, fmt = parse_items(text)
    # Scalar grand figures (O&P, tax, net claim, line-item total) are read from the
    # main body with any supplement / change-summary blocks stripped, so a delta or
    # already-included subset figure cannot outrank the grand line.
    body = _strip_supplement(text)
    has_op, overhead, profit = detect_op(body)
    line_sum = round(sum(i.rcv for i in items), 2)
    grand = grand_rcv(text, line_sum)

    ratio = round(line_sum / grand, 3) if grand else 0.0
    if ocr or ratio < 0.85 or ratio > 1.15:
        conf = "low"
    elif ratio < 0.95:
        conf = "medium"
    else:
        conf = "high"

    return Estimate(
        path=path, name=os.path.basename(path), role=role, ocr=ocr, fmt=fmt,
        items=items,
        grand_rcv=grand,
        rcv_line_sum=line_sum,
        net_claim=max(_amts(NET_CLAIM, body), default=0.0),
        line_item_total=max(_amts(LINE_ITEM_TOTAL, body), default=0.0),
        sales_tax=max(_amts(TAX_LINE, body), default=0.0),
        has_op=has_op, overhead=overhead, profit=profit,
        recap=parse_recap(text),
        parse_ratio=ratio,
        confidence=conf,
        image_only=image_only,
        statements=extract_statements(text),
        sublimit_coverages=detect_sublimit_coverages(text),
        section_totals=_section_totals(text.splitlines()),
    )


if __name__ == "__main__":
    import sys
    e = extract_estimate(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "carrier")
    print(f"{e.name}  role={e.role} fmt={e.fmt} ocr={e.ocr} items={len(e.items)}")
    print(f"  grand_rcv={e.grand_rcv:,.2f}  rcv_line_sum={e.rcv_line_sum:,.2f}  "
          f"line_item_total={e.line_item_total:,.2f}  tax={e.sales_tax:,.2f}")
    print(f"  has_op={e.has_op}  overhead={e.overhead:,.2f}  profit={e.profit:,.2f}")
    for it in e.items[:10]:
        print(f"    {it.number:>3}. [{it.category:<14}] {it.description[:40]:<40} "
              f"{it.quantity:>8.2f} {it.unit:<3} up={it.unit_price:>8.2f} "
              f"rcv={it.rcv:>9.2f} acv={it.acv:>9.2f}")
