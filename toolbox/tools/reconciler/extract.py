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


def grand_rcv(text: str, line_sum: float) -> float:
    """The estimate's grand Replacement Cost Value (includes tax and O&P).

    Carriers print this total in one of three shapes, tried most-authoritative
    first. Verified across the sample corpus to land on the recap total to the
    cent (Gritzman 32,813.71, Esposito 36,445.82, Diaz 12,618.27, ...):

      1. A grand 'TOTAL $x' recap row (Allstate 'Loss Recap Summary').
      2. Per-coverage 'Replacement Cost Value $x' summary lines, summed over the
         distinct values (page-break echoes repeat a coverage's total verbatim;
         two distinct coverages matching to the cent is vanishingly rare).
      3. The 'Line Item Totals:' row, where the RCV column is the value V with a
         following depreciation D and actual-cash-value A such that V - D = A.

    Falls back to the parsed line-item RCV sum when none of the above is present.
    """
    m = RCV_TOTAL_ROW.search(text)
    if m:
        return _fnum(m.group(1))

    rcv_vals = [_fnum(x) for x in RCV_LINE.findall(text)]
    if rcv_vals:
        return round(sum(set(rcv_vals)), 2)

    best = None
    for row in LINE_ITEM_TOTALS_ROW.findall(text):
        nums = [_fnum(x) for x in _MONEY_TOK.findall(row)]
        r = _rcv_from_row(nums)
        if r is not None and (best is None or r > best):
            best = r
        if best is None and nums:
            best = max(nums)
    if best is not None:
        return round(best, 2)

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


def _extract_text(path: str) -> str:
    """Native text layer via PyMuPDF, row-reconstructed to mimic poppler's
    `pdftotext -layout`. Replaces the poppler shell-out with no dependency."""
    try:
        with fitz.open(path) as doc:
            return "\n".join(_page_layout_text(page) for page in doc)
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


def is_extension_item(section: str, description: str) -> bool:
    """True when a line item belongs to a secondary structure a dwelling-extension
    / other-structures sublimit covers, rather than the main dwelling. The structure
    name (barn, shed, detached garage) is matched in either the section or the
    description; metal-building materials count only in the description."""
    sec, desc = section or "", description or ""
    return bool(EXT_SECTION.search(sec) or EXT_SECTION.search(desc)
                or EXT_DESC.search(desc))


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
    has_op, overhead, profit = detect_op(text)
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
        net_claim=max(_amts(NET_CLAIM, text), default=0.0),
        line_item_total=max(_amts(LINE_ITEM_TOTAL, text), default=0.0),
        sales_tax=max(_amts(TAX_LINE, text), default=0.0),
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
