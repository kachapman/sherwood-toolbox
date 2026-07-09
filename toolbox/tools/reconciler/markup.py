"""Turn a Recon into a marked-up carrier estimate PDF.

The reconciler engine already finds the difference between the two estimates.
This module paints that difference back onto the carrier's own PDF so a reviewer
sees it in place instead of reading it off a table:

  * a prepended **summary page** with the headline numbers and a colour legend;
  * **in-line flags** on the carrier's line items the contractor measured higher,
    each highlighted across the line with a numbered tab in the left margin,
    coloured by how large the quantity gap is in dollars;
  * **painted-in missing scope**: the line items the carrier omits entirely, drawn
    as green insertion rows onto the carrier pages below the section they belong
    to, so the reviewer sees where the missing lines go;
  * appended **detail pages** that decode every flag, list all the missing scope
    (grouped by category), show the RCV build-up, and quote the carrier's own
    coverage statements and the denial hypotheses.

Everything is drawn with PyMuPDF (`fitz`); there is no other dependency. Nothing
here reads the network or the filesystem beyond the one carrier PDF it is handed.

Line items are located by re-clustering the page words into rows and matching the
row whose leading token is the printed line number (see `locate_items`). An
image-only carrier has no text layer to locate against, so in-line flags are
skipped and the appended pages still carry the full picture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import fitz

# === SECTION: palette ===
# Brand tokens from toolbox.css, as RGB in 0..1. The estimate stays black on
# white; markup adds these on top.
INK = (0.11, 0.14, 0.11)         # --ink   #1c241c
MUTED = (0.36, 0.42, 0.35)       # --muted #5d6b5a
GREEN = (0.13, 0.24, 0.14)       # --green-800 #203c23
GREEN_MID = (0.29, 0.49, 0.32)   # --green-500 #4a7c52
LINE = (0.80, 0.84, 0.76)        # --line  #cdd6c2
SAGE = (0.93, 0.95, 0.90)        # --sage-50 #eef1e6
WHITE = (1, 1, 1)

# Report palette (hex from the spec). Missing scope the carrier omits entirely
# (two-file mode) is salmon; outstanding scope still worth pursuing (three-file
# mode) is blue; approved wins are green. These three carry the meaning; the rest
# are neutrals and a warm under-measured scale chosen to stay clear of them.
MISSING = (0.961, 0.592, 0.588)      # #F59796
OUTSTANDING = (0.204, 0.322, 0.718)  # #3452B7
APPROVED = (0.000, 0.565, 0.278)     # #009047


def _tint(rgb, t=0.88):
    """A pale wash of an accent for opaque row backgrounds (blend toward white)."""
    return tuple(round(c + (1 - c) * t, 3) for c in rgb)


def _darken(rgb, k=0.52):
    """A darkened accent, readable as body text on that accent's pale tint."""
    return tuple(round(c * k, 3) for c in rgb)


def _readable_on(rgb):
    """White or near-black text, whichever reads on a solid fill of `rgb`."""
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return WHITE if lum < 0.6 else (0.16, 0.10, 0.10)


class Scheme:
    """A painted-scope block's tones and its header word: a solid header colour, a
    pale row fill, body text, text that reads on the header, and the label the
    header bar states."""

    def __init__(self, accent, header):
        self.accent = accent
        self.tint = _tint(accent)
        self.text = _darken(accent)
        self.head_text = _readable_on(accent)
        self.header = header


MISSING_SCHEME = Scheme(MISSING, "MISSING FROM CARRIER")       # two-file mode
OUTSTANDING_SCHEME = Scheme(OUTSTANDING, "STILL OUTSTANDING")  # three-file mode

# Warning accent for the coverage-sublimit caution.
WARN = (0.54, 0.29, 0.09)
WARN_BG = (0.98, 0.94, 0.86)

# Severity of a quantity shortfall, keyed by its dollar size (contractor unit
# price x the quantity the carrier is short). The band fill is drawn translucent
# so the line item reads through it. Thresholds are set so only a large dollar
# shortfall reads red.
@dataclass(frozen=True)
class Severity:
    label: str
    fill: tuple      # highlight band + flag colour
    floor: float     # dollar impact at or above which this level applies


# Under-measured quantity gaps use a red -> salmon -> amber scale by dollar size.
SEVERITIES = (
    Severity("high", (0.80, 0.16, 0.14), 500.0),       # red:    >= $500
    Severity("mid", (0.961, 0.592, 0.588), 150.0),     # salmon: $150 - $500
    Severity("low", (0.95, 0.66, 0.20), 0.0),          # amber:  < $150
)


def severity_for(dollars: float) -> Severity:
    for s in SEVERITIES:
        if dollars >= s.floor:
            return s
    return SEVERITIES[-1]


# === SECTION: money / number formatting ===
def _money(x) -> str:
    return ("-" if x < 0 else "") + f"${abs(x):,.2f}"


def _signed_money(x) -> str:
    return ("+" if x >= 0 else "-") + f"${abs(x):,.2f}"


def _qty(x) -> str:
    return f"{x:g}"


def _signed_qty(x) -> str:
    return ("+" if x >= 0 else "") + f"{x:g}"


# === SECTION: locating line-item rows on the carrier pages ===
ROW_OVERLAP = 0.5          # min vertical overlap to treat two words as one row
_LEADING_NUM = re.compile(r"^(\d{1,3})\.?$")   # '1.' (Xactimate) or '7' (Symbility)


def _cluster_rows(page):
    """Group a page's words into visual rows by vertical overlap.

    Mirrors extract._page_layout_text's clustering but keeps each row's word
    rectangles so a located row can be drawn on. Returns rows sorted top-to-
    bottom, each a dict with y-span, the ordered words, and the joined text.
    """
    words = page.get_text("words")
    if not words:
        return []
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
    for r in rows:
        r["ws"].sort(key=lambda w: w[0])
        r["x0"] = r["ws"][0][0]
        r["x1"] = r["ws"][-1][2]
        r["text"] = " ".join(w[4] for w in r["ws"])
    return rows


def _row_keyword(description: str) -> str:
    """First distinctive word of a line-item description, lower-cased, for a
    sanity check that a number-matched row is really that item and not a stray
    leading integer. Skips the action prefix and short filler tokens."""
    for tok in re.split(r"[^A-Za-z]+", description.lower()):
        if len(tok) >= 4 and tok not in ("remove", "detach", "reset", "replace"):
            return tok
    for tok in re.split(r"[^A-Za-z]+", description.lower()):
        if len(tok) >= 3:
            return tok
    return ""


def locate_items(doc, wanted):
    """Map each wanted carrier line number to its row rect on the page.

    `wanted` is {line_number: description}. A row matches when its first token is
    that number and the item's keyword appears in the row text (guarding against
    a recap row or page number that merely starts with the same integer). The
    first match wins; line numbers are unique per estimate. Returns
    {line_number: (page_index, fitz.Rect)}.

    Stops once every wanted item is located, so trailing pages (photos, addenda)
    on a long carrier are never word-clustered: line items sit near the front, so
    this skips most of the work on big files.
    """
    found = {}
    if not wanted:
        return found
    for pno in range(len(doc)):
        rows = _cluster_rows(doc.load_page(pno))
        for row in rows:
            m = _LEADING_NUM.match(row["ws"][0][4])
            if not m:
                continue
            num = int(m.group(1))
            if num not in wanted or num in found:
                continue
            kw = _row_keyword(wanted[num])
            if kw and kw not in row["text"].lower():
                continue
            found[num] = (pno, fitz.Rect(row["x0"], row["y0"], row["x1"], row["y1"]))
        if len(found) == len(wanted):
            break
    return found


# === SECTION: in-line flags on the carrier pages ===
FLAG_L = 3.0               # left-margin flag x-range (widened to hold the $ gap)
FLAG_R = 34.0
BAND_INSET = 34.0         # highlight band left/right inset from the page edge


def _flag_money(dollars, max_w, signed=False):
    """A compact RCV-gap label for the narrow left-margin tab: cents when they fit
    (e.g. $839.89), whole dollars for a wide 4-digit gap that would overflow
    (e.g. $1,036), shrinking the font toward 6 pt as a last resort. Returns
    (label, fontsize). With signed=True a positive amount leads with '+' (an
    approved increase, e.g. +$839.89); a negative always leads with '-'."""
    lead = "+" if (signed and dollars >= 0) else ""
    cents = lead + _money(round(dollars, 2))          # +$839.89
    whole = lead + ("-" if dollars < 0 else "") + f"${abs(round(dollars)):,}"  # +$1,036
    for label in (cents, whole):
        for size in (8.0, 7.5, 7.0, 6.5, 6.0):
            if fitz.get_text_length(label, "hebo", size) <= max_w:
                return label, size
    return whole, 6.0


def flag_row(page, rect, gap_dollars, sev: Severity):
    """Highlight a located line item across its width and print its RCV gap in the
    left-margin tab. The band is translucent so the priced line reads through."""
    w = page.rect.width
    band = fitz.Rect(BAND_INSET, rect.y0 - 1.5, w - BAND_INSET, rect.y1 + 1.5)
    page.draw_rect(band, color=None, fill=sev.fill, fill_opacity=0.22)
    # thin left rule at the band edge for definition
    page.draw_line(fitz.Point(BAND_INSET, band.y0), fitz.Point(BAND_INSET, band.y1),
                   color=sev.fill, width=1.4)
    # left-margin tab carrying the RCV-gap dollars, where the gutter is wide enough
    if rect.x0 >= FLAG_R + 1:
        tab = fitz.Rect(FLAG_L, rect.y0 - 1.0, FLAG_R, rect.y1 + 1.0)
        page.draw_rect(tab, color=None, fill=sev.fill, fill_opacity=1.0, radius=0.25)
        label, size = _flag_money(gap_dollars, (FLAG_R - FLAG_L) - 3)
        tw = fitz.get_text_length(label, "hebo", size)
        cx = FLAG_L + (FLAG_R - FLAG_L - tw) / 2
        cy = (rect.y0 + rect.y1) / 2 + size * 0.36
        page.insert_text(fitz.Point(cx, cy), label, fontname="hebo", fontsize=size,
                         color=_readable_on(sev.fill))


def tag_won(page, rect, amount):
    """Mark a carrier line the carrier approved from our supplement: a faint green
    band and, in the left-margin tab, the dollars the current carrier estimate
    added over the original on this line (an added line's full RCV, a raised
    line's increase). Same tab the salmon short-line flag uses, recolored green."""
    w = page.rect.width
    band = fitz.Rect(BAND_INSET, rect.y0 - 1.5, w - BAND_INSET, rect.y1 + 1.5)
    page.draw_rect(band, color=None, fill=APPROVED, fill_opacity=0.16)
    page.draw_line(fitz.Point(BAND_INSET, band.y0), fitz.Point(BAND_INSET, band.y1),
                   color=APPROVED, width=1.4)
    if rect.x0 >= FLAG_R + 2:
        tab = fitz.Rect(FLAG_L, rect.y0 - 1.0, FLAG_R, rect.y1 + 1.0)
        page.draw_rect(tab, color=None, fill=APPROVED, fill_opacity=1.0, radius=0.25)
        label, size = _flag_money(amount, (FLAG_R - FLAG_L) - 3, signed=True)
        tw = fitz.get_text_length(label, "hebo", size)
        cx = FLAG_L + (FLAG_R - FLAG_L - tw) / 2
        cy = (rect.y0 + rect.y1) / 2 + size * 0.36
        page.insert_text(fitz.Point(cx, cy), label, fontname="hebo", fontsize=size,
                         color=_readable_on(APPROVED))


# === SECTION: painting outstanding scope in place on the carrier pages ===
ADD_HEADER_H = 12.0
ADD_ROW_H = 11.0
ADD_BOTTOM_PAD = 40.0     # keep painted rows clear of the page footer


def _right(page, x_right, base, s, font, size, color):
    """Draw a right-aligned single token ending at x_right on baseline `base`."""
    tw = fitz.get_text_length(s, font, size)
    page.insert_text(fitz.Point(x_right - tw, base), s, fontname=font, fontsize=size,
                     color=color)


def _paint_add_row(page, x0, x1, y, num, desc, qty, rcv, sch):
    """One opaque insertion row in the scheme's colours: a coloured left rule, the
    supplement line number, description, quantity, and RCV. Opaque so it reads
    cleanly wherever it lands on the carrier page."""
    page.draw_rect(fitz.Rect(x0, y, x1, y + ADD_ROW_H), color=None, fill=sch.tint,
                   fill_opacity=1.0)
    page.draw_line(fitz.Point(x0, y), fitz.Point(x0, y + ADD_ROW_H), color=sch.accent, width=2)
    base = y + 8.2
    rcv_w, qty_w, num_w = 66.0, 58.0, 26.0
    num_x = x0 + 6
    desc_x = num_x + num_w
    desc_right = x1 - rcv_w - qty_w - 8
    page.insert_text(fitz.Point(num_x, base), f"#{num}" if num else "",
                     fontname="hebo", fontsize=8, color=sch.accent)
    page.insert_text(fitz.Point(desc_x, base), _fit(desc, "helv", 8, desc_right - desc_x),
                     fontname="helv", fontsize=8, color=sch.text)
    _right(page, x1 - rcv_w - 4, base, qty, "helv", 8, sch.text)
    _right(page, x1 - 4, base, rcv, "hebo", 8, sch.text)


def paint_block(page, label, items, start_y, sch, net=None):
    """Paint one section's items onto the page in the scheme's colours, starting at
    `start_y` (below the anchor line). `net` is the section's net outstanding (the
    section-subtotal difference); when given it heads the block instead of the raw
    item sum, so a grade revision does not read as full new scope. Returns
    (bottom_y, rows_painted); rows that will not fit are summarised in a "+N more"
    line pointing to the back-of-document list."""
    x0, x1 = BAND_INSET, page.rect.width - BAND_INSET
    max_y = page.rect.height - ADD_BOTTOM_PAD
    head_amt = f"{_money(net)} net" if net is not None else _money(
        round(sum(s.dollars for s in items), 2))
    y = start_y

    # No room even for a one-line marker without hitting the footer: skip drawing;
    # the items are still in the back-of-document list.
    if y + ADD_HEADER_H > max_y:
        return y, 0

    # Room for a marker but not a full row: leave a one-line in-context marker.
    if y + ADD_HEADER_H + ADD_ROW_H > max_y:
        page.draw_rect(fitz.Rect(x0, y, x1, y + ADD_HEADER_H), color=None, fill=sch.accent,
                       fill_opacity=1.0)
        page.insert_text(fitz.Point(x0 + 6, y + 8.7),
                         f"{sch.header} - {label}: {head_amt}, {len(items)} items, "
                         f"see the back", fontname="hebo", fontsize=7.5, color=sch.head_text)
        return y + ADD_HEADER_H, 0

    page.draw_rect(fitz.Rect(x0, y, x1, y + ADD_HEADER_H), color=None, fill=sch.accent,
                   fill_opacity=1.0)
    page.insert_text(fitz.Point(x0 + 6, y + 8.7), f"{sch.header} - {label}   ({head_amt})",
                     fontname="hebo", fontsize=7.5, color=sch.head_text)
    y += ADD_HEADER_H

    fit = int((max_y - y) // ADD_ROW_H)
    show = items if len(items) <= fit else items[:max(fit - 1, 1)]
    for s in show:
        _paint_add_row(page, x0, x1, y, s.number, s.description,
                       f"{_qty(s.quantity)} {s.unit}".strip(), _money(s.dollars), sch)
        y += ADD_ROW_H
    remaining = len(items) - len(show)
    if remaining > 0:
        rem_dollars = round(sum(s.dollars for s in items[len(show):]), 2)
        page.draw_rect(fitz.Rect(x0, y, x1, y + ADD_ROW_H), color=None, fill=sch.tint,
                       fill_opacity=1.0)
        page.draw_line(fitz.Point(x0, y), fitz.Point(x0, y + ADD_ROW_H), color=sch.accent, width=2)
        page.insert_text(fitz.Point(x0 + 8, y + 8.2),
                         f"+ {remaining} more in {label} ({_money(rem_dollars)}) - "
                         f"full list at the back", fontname="helv", fontsize=8, color=sch.text)
        y += ADD_ROW_H
    return y, len(show)


def _sec_tokens(name):
    """Alphabetic tokens of a section name, lower-cased ('Roof1' -> {'roof'})."""
    return {t for t in re.split(r"[^A-Za-z]+", (name or "").lower()) if len(t) >= 3}


def _anchor_for_section(sec, carrier_secs, fallback):
    """Anchor a contractor section to the carrier section whose name overlaps it
    most (front elevation -> front elevation; roof -> dwelling/barn roof). Falls
    back to the bottom of the carrier's line items when nothing matches."""
    toks = _sec_tokens(sec)
    best, best_score = None, 0
    for csec, anchor in carrier_secs.items():
        score = len(toks & _sec_tokens(csec))
        if score > best_score:
            best, best_score = anchor, score
    return best if best is not None else fallback


def paint_outstanding_by_section(doc, missing, located_all, sec_of, sch, section_net=None):
    """Paint outstanding items onto the carrier pages in the scheme's colours,
    grouped by their supplement section and anchored below the matching carrier
    section. `section_net` maps a section name to its net outstanding, which heads
    the block. Blocks on one page stack rather than overlap. Returns the number of
    items painted as full rows."""
    if not missing or not located_all:
        return 0
    section_net = section_net or {}

    carrier_secs = {}
    for num, (pno, rect) in located_all.items():
        s = sec_of.get(num, "")
        cur = carrier_secs.get(s)
        if cur is None or (pno, rect.y1) > (cur[0], cur[1].y1):
            carrier_secs[s] = (pno, rect)
    fallback = max(located_all.values(), key=lambda pr: (pr[0], pr[1].y1))

    groups, order = {}, []
    for s in missing:
        sec = s.section or "Other"
        if sec not in groups:
            groups[sec] = []
            order.append(sec)
        groups[sec].append(s)

    # Resolve each section's anchor, then paint top-to-bottom within each page. The
    # per-page cursor only stacks correctly in reading order: painting in dollar
    # order lets a block anchored low on a page (e.g. Left Elevation at the page
    # foot) advance the cursor past the page bottom, so a block anchored higher on
    # the same page (Back, Right) then finds no room and silently drops.
    placements = []
    for sec in order:
        pno, rect = _anchor_for_section(sec, carrier_secs, fallback)
        placements.append((pno, rect.y1, sec, rect))
    placements.sort(key=lambda p: (p[0], p[1]))

    page_cursor = {}
    painted = 0
    for pno, _y, sec, rect in placements:
        page = doc.load_page(pno)
        start_y = max(rect.y1 + 2.5, page_cursor.get(pno, 0.0))
        bottom, n = paint_block(page, sec, groups[sec], start_y, sch, section_net.get(sec))
        page_cursor[pno] = bottom + 3
        painted += n
    return painted


# === SECTION: page canvas for the summary and detail pages ===
PAGE_W, PAGE_H = 612.0, 792.0
MARGIN = 54.0


class Canvas:
    """A running-cursor writer over appended letter pages. Text is laid out top
    to bottom; `space` breaks to a new page when the current one is full.

    Single lines are drawn with `insert_text` at a computed baseline, never with
    `insert_textbox`: a textbox silently renders nothing when its one line is a
    hair too tall for the box, which is easy to trip into with tight table rows.
    Only genuinely wrapped paragraphs (`text`, `quote`) use a textbox, with the
    full remaining page height so nothing clips.
    """

    def __init__(self, doc, at_front=False, single_page=False):
        # single_page: never break to a new page. The prepended summary must stay
        # exactly one page, or the mark_up_carrier page math (original page ->
        # final page = index + 2) would be off and an overflow page would land at
        # the very end instead of after the summary.
        self.doc = doc
        self.single_page = single_page
        self.page = doc.new_page(0 if at_front else -1, width=PAGE_W, height=PAGE_H)
        self.y = MARGIN
        self.pages = 1

    def _new_page(self):
        self.page = self.doc.new_page(-1, width=PAGE_W, height=PAGE_H)
        self.y = MARGIN
        self.pages += 1

    def space(self, h):
        if not self.single_page and self.y + h > PAGE_H - MARGIN:
            self._new_page()

    def _line(self, x, s, size, font="helv", color=INK, align=0, box_w=None):
        """Draw one line; baseline sits `size` below the current top. `align` is
        0 left, 1 centre, 2 right within `box_w` (from x)."""
        if align and box_w is not None:
            tw = fitz.get_text_length(s, font, size)
            x = x + box_w - tw if align == 2 else x + (box_w - tw) / 2
        self.page.insert_text(fitz.Point(x, self.y + size), s, fontname=font,
                              fontsize=size, color=color)

    def text(self, s, size=10, font="helv", color=INK, x=MARGIN, gap=4, width=None):
        """One paragraph, wrapped and placed line by line. Drawing each line on its
        own baseline (not a single insert_textbox) keeps the advanced height equal
        to what was drawn, so a following block never overlaps the last line."""
        width = width or (PAGE_W - 2 * MARGIN)
        lines = self._wrap(s, font, size, width) or [""]
        line_h = size + 2
        h = len(lines) * line_h
        self.space(h)
        y = self.y + size
        for ln in lines:
            self.page.insert_text(fitz.Point(x, y), ln, fontname=font, fontsize=size,
                                  color=color)
            y += line_h
        self.y += h + gap

    @staticmethod
    def _wrapped_lines(s, font, size, width):
        n = 0
        for para in s.split("\n"):
            words, line = para.split(" "), ""
            if not words:
                n += 1
                continue
            count = 1
            for wd in words:
                trial = (line + " " + wd).strip()
                if fitz.get_text_length(trial, font, size) > width and line:
                    count += 1
                    line = wd
                else:
                    line = trial
            n += count
        return n

    @staticmethod
    def _wrap(s, font, size, width):
        """The wrapped lines themselves (what `_wrapped_lines` counts)."""
        out = []
        for para in s.split("\n"):
            line = ""
            for wd in para.split(" "):
                trial = (line + " " + wd).strip()
                if fitz.get_text_length(trial, font, size) > width and line:
                    out.append(line)
                    line = wd
                else:
                    line = trial
            out.append(line)
        return out

    def rule(self, color=LINE, gap=8):
        self.space(gap + 2)
        self.page.draw_line(fitz.Point(MARGIN, self.y), fitz.Point(PAGE_W - MARGIN, self.y),
                            color=color, width=0.8)
        self.y += gap

    def heading(self, s, size=15):
        self.space(size + 12)
        self._line(MARGIN, s, size, font="hebo", color=GREEN)
        self.y += size + 8

    def subheading(self, s, color=GREEN):
        self.space(20)
        self._line(MARGIN, s, 10.5, font="hebo", color=color)
        self.y += 17

    def row(self, cells, widths, *, font="helv", size=9.5, color=INK, aligns=None,
            head=False, fill=None):
        """One table row. `cells` and `widths` are parallel; `widths` sum to the
        content width. `aligns` is per-column (0 left, 1 centre, 2 right)."""
        h = size + 7
        self.space(h)
        aligns = aligns or [0] * len(cells)
        if fill:
            self.page.draw_rect(fitz.Rect(MARGIN, self.y, PAGE_W - MARGIN, self.y + h),
                                color=None, fill=fill, fill_opacity=1.0)
        top = self.y
        x = MARGIN
        fnt = "hebo" if head else font
        pad = 4
        for cell, wdt, al in zip(cells, widths, aligns):
            s = _fit(str(cell), fnt, size, wdt - 2 * pad)
            self.y = top + 1
            self._line(x + pad, s, size, font=fnt, color=color, align=al,
                       box_w=wdt - 2 * pad)
            x += wdt
        self.y = top + h

    def quote(self, s):
        """An indented, rule-bordered verbatim quote block. Each wrapped line is
        placed on its own baseline (insert_text), so a short quote never clips the
        way a tight insert_textbox rect does."""
        inner = PAGE_W - 2 * MARGIN - 30
        lines = self._wrap(s, "helv", 9, inner)
        h = len(lines) * 12 + 10
        self.space(h)
        top = self.y
        self.page.draw_rect(fitz.Rect(MARGIN, top, PAGE_W - MARGIN, top + h),
                            color=None, fill=SAGE, fill_opacity=1.0)
        self.page.draw_line(fitz.Point(MARGIN, top), fitz.Point(MARGIN, top + h),
                            color=GREEN_MID, width=2.2)
        y = top + 12
        for ln in lines:
            self.page.insert_text(fitz.Point(MARGIN + 12, y), ln, fontname="helv",
                                  fontsize=9, color=INK)
            y += 12
        self.y = top + h + 6


def _fit(s, font, size, width):
    """Ellipsize a cell string to fit a column width (ASCII '...' so it renders
    in the Base-14 fonts, which lack a real ellipsis glyph)."""
    if fitz.get_text_length(s, font, size) <= width:
        return s
    while s and fitz.get_text_length(s + "...", font, size) > width:
        s = s[:-1]
    return s.rstrip() + "..."


# === SECTION: summary page (prepended) ===
def _summary_page(doc, recon, flagged, missing, located_count, painted_count, won_count):
    c = Canvas(doc, at_front=True, single_page=True)
    if recon.mode == "effectiveness":
        _summary_effectiveness(c, recon, flagged, missing, located_count,
                               painted_count, won_count)
    else:
        _summary_recoverable(c, recon, flagged, missing, located_count, painted_count)
    _summary_footer(c, recon)


def _headline_box(c, label, value, sub):
    box_h = 52
    c.space(box_h + 6)
    top = c.y
    c.page.draw_rect(fitz.Rect(MARGIN, top, PAGE_W - MARGIN, top + box_h),
                     color=None, fill=SAGE, fill_opacity=1.0)
    c.page.draw_line(fitz.Point(MARGIN, top), fitz.Point(MARGIN, top + box_h),
                     color=GREEN, width=3)
    c.page.insert_text(fitz.Point(MARGIN + 14, top + 17), label, fontname="hebo",
                       fontsize=8.5, color=MUTED)
    c.page.insert_text(fitz.Point(MARGIN + 14, top + 42), value, fontname="hebo",
                       fontsize=22, color=GREEN)
    if sub:
        vw = fitz.get_text_length(value, "hebo", 22)
        c.page.insert_text(fitz.Point(MARGIN + 14 + vw + 12, top + 40), sub,
                           fontname="helv", fontsize=10, color=MUTED)
    c.y = top + box_h + 12


def _totals3(c, labels, values):
    third = (PAGE_W - 2 * MARGIN) / 3
    c.row(labels, [third] * 3, head=True, size=9, color=MUTED)
    c.row(values, [third] * 3, font="hebo", size=12, color=GREEN)


def _narrative_block(c, recon):
    """Lead the summary with the plain-language narrative: normal sentences in
    readable body text, the caution sentence set off in an amber callout."""
    for s in recon.narrative:
        if s.get("tone") == "caution":
            _caution_para(c, s["text"])
        else:
            c.text(s["text"], size=10.5, color=INK, gap=8)
    c.y += 2


def _caution_para(c, text):
    inner = PAGE_W - 2 * MARGIN - 24
    lines = c._wrapped_lines(text, "helv", 9.5, inner)
    box_h = 18 + lines * 12 + 8
    c.space(box_h + 6)
    top = c.y
    c.page.draw_rect(fitz.Rect(MARGIN, top, PAGE_W - MARGIN, top + box_h),
                     color=None, fill=WARN_BG, fill_opacity=1.0)
    c.page.draw_line(fitz.Point(MARGIN, top), fitz.Point(MARGIN, top + box_h),
                     color=WARN, width=3)
    c.page.insert_text(fitz.Point(MARGIN + 12, top + 13), "HEADS UP", fontname="hebo",
                       fontsize=8, color=WARN)
    c.y = top + 18
    c.text(text, size=9.5, x=MARGIN + 12, width=inner, color=INK, gap=0)
    c.y = top + box_h + 8


def _effectiveness_headline(c, recon):
    """One sage panel carrying the APPROVAL EFFECTIVENESS label, the big percentage,
    and the money-summary sentence (the first, non-caution, narrative line)."""
    pct = f"{recon.effectiveness * 100:.0f}%"
    body = next((s["text"] for s in recon.narrative if s.get("tone") != "caution"), "")
    inner = PAGE_W - 2 * MARGIN - 28
    lines = c._wrapped_lines(body, "helv", 10.5, inner) if body else 0
    box_h = 50 + lines * 13 + 12
    c.space(box_h + 6)
    top = c.y
    c.page.draw_rect(fitz.Rect(MARGIN, top, PAGE_W - MARGIN, top + box_h),
                     color=None, fill=SAGE, fill_opacity=1.0)
    c.page.draw_line(fitz.Point(MARGIN, top), fitz.Point(MARGIN, top + box_h),
                     color=GREEN, width=3)
    c.page.insert_text(fitz.Point(MARGIN + 14, top + 17), "APPROVAL EFFECTIVENESS",
                       fontname="hebo", fontsize=8.5, color=MUTED)
    c.page.insert_text(fitz.Point(MARGIN + 14, top + 42), pct, fontname="hebo",
                       fontsize=22, color=GREEN)
    if body:
        c.y = top + 50
        c.text(body, size=10.5, x=MARGIN + 14, width=inner, color=INK, gap=0)
    c.y = top + box_h + 10


def _summary_effectiveness(c, recon, flagged, missing, located_count, painted_count,
                           won_count):
    c.heading(f"Reconciliation report - {recon.claimant}", size=17)
    _effectiveness_headline(c, recon)
    caution = next((s["text"] for s in recon.narrative if s.get("tone") == "caution"), None)
    if caution:
        _caution_para(c, caution)
    c.y += 4

    _totals3(c, ["Approved to date (original to current)", "Still unapproved",
                 "Contractor over original"],
             [_signed_money(recon.approved_dollars), _money(recon.outstanding_dollars),
              _money(recon.ask_dollars)])
    c.y += 6
    _totals3(c, ["Original carrier RCV", "Current carrier RCV", "Contractor RCV"],
             [_money(recon.og_grand), _money(recon.carrier_grand),
              _money(recon.contractor_grand)])
    c.text(f"Original: {recon.og_name}", size=8, color=MUTED, gap=1)
    c.text(f"Current carrier: {recon.carrier_name}", size=8, color=MUTED, gap=1)
    c.text(f"Contractor: {recon.contractor_name}", size=8, color=MUTED, gap=10)

    c.rule()
    c.subheading("What the markup shows")
    n_add = len(recon.approved_added)
    n_rev = len(recon.approved_revised)
    rev_clause = (f", plus {n_rev} existing line{'s' if n_rev != 1 else ''} it "
                  f"raised toward the contractor" if n_rev else "")
    c.text(f"-  {n_add} supplement line{'s' if n_add != 1 else ''} the carrier added "
           f"since its original{rev_clause}: {won_count} marked in green in place on "
           f"the carrier pages, each showing the dollars it added over the original.",
           size=10, gap=6)
    c.text(f"-  {len(missing)} items are still unapproved: {painted_count} painted in "
           f"blue on the carrier pages by section, keyed to the contractor line "
           f'number. Full list under "Outstanding scope" at the back.', size=10, gap=6)
    _flagged_line(c, flagged, located_count)
    _legend(c, effectiveness=True)


def _summary_recoverable(c, recon, flagged, missing, located_count, painted_count):
    c.heading(f"Reconciliation summary - {recon.claimant}", size=17)
    _narrative_block(c, recon)
    _headline_box(c, "ESTIMATED RECOVERABLE", _money(recon.est_recoverable), "")
    _totals3(c, ["Carrier RCV", "Contractor RCV", "RCV gap"],
             [_money(recon.carrier_grand), _money(recon.contractor_grand),
              _signed_money(round(recon.contractor_grand - recon.carrier_grand, 2))])
    c.text(f"Carrier: {recon.carrier_name}", size=8, color=MUTED, gap=1)
    c.text(f"Contractor: {recon.contractor_name}", size=8, color=MUTED, gap=8)

    # The reliable total is the grand-total gap (the headline), not the sum of the
    # per-section diffs, which can drift by carrier scope in unmatched sections and
    # by tax/O&P not carried into the leaf subtotals.
    net_missing = round(max(0.0, recon.contractor_grand - recon.carrier_grand), 2)
    op = ("Carrier Overhead & Profit: " +
          ("applied" if recon.carrier_has_op else "NOT applied") +
          f".   Contractor: {'applied' if recon.contractor_has_op else 'not applied'}.")
    c.text(op, size=9.5, gap=10)
    c.rule()
    c.subheading("What the markup shows")
    c.text(f"-  {len(missing)} contractor line items are missing from this carrier "
           f"estimate, {_money(net_missing)} net of scope the carrier already carries "
           f"in those sections: {painted_count} painted in salmon on the carrier pages "
           f'by section. Full list under "Missing scope" at the back.', size=10, gap=6)
    _flagged_line(c, flagged, located_count)
    _legend(c, effectiveness=False)


def _flagged_line(c, flagged, located_count):
    n = len(flagged)
    if n:
        c.text(f"-  The carrier measured {n} shared line{'s' if n != 1 else ''} short "
               f"of the contractor; {located_count} are highlighted on the carrier "
               f"pages, each showing its RCV gap in the margin.", size=10, gap=6)
    else:
        c.text("-  The carrier's quantities match the contractor on every shared line.",
               size=10, gap=6)
    if flagged and located_count < len(flagged):
        c.text("   Lines the reader did not place on the page (an image-only scan or "
               "an unmatched layout) are not marked in place but are listed at the "
               "back.", size=9, color=MUTED, gap=10)
    else:
        c.y += 4


def _legend(c, effectiveness):
    c.subheading("Legend")
    if effectiveness:
        _legend_check(c, "Approved: contractor scope now in the carrier estimate; the "
                         "green amount is the increase over the original")
        _legend_row(c, OUTSTANDING, "Outstanding: contractor scope the carrier has not approved",
                    opacity=1.0)
    else:
        _legend_row(c, MISSING, "Missing: contractor scope the carrier estimate omits",
                    opacity=1.0)
    _legend_row(c, SEVERITIES[0].fill, "Carrier short by $500 or more on a shared line")
    _legend_row(c, SEVERITIES[1].fill, "Carrier short by $150 to $500 on a shared line")
    _legend_row(c, SEVERITIES[2].fill, "Carrier short by under $150 on a shared line")
    if effectiveness:
        c.text("Each highlighted line shows a dollar amount in the left margin: an "
               "approved line's increase over the original, or a short line's RCV gap. "
               "The coloured blocks carry the contractor line number.", size=8.5,
               color=MUTED, gap=6)
    else:
        c.text("Each highlighted line shows its RCV gap in the left margin; the coloured "
               "blocks carry the contractor line number.", size=8.5, color=MUTED, gap=6)


def _summary_footer(c, recon):
    for n in recon.notes:
        c.text(f"Note: {n}", size=8.5, color=MUTED, gap=4)
    c.rule()
    c.text("An aid to review, not a guarantee of coverage. Figures are read from "
           "the PDFs as printed. Sherwood Estimates (c) 2026.", size=8, color=MUTED)


def _legend_row(c, fill, label, opacity=0.5):
    c.space(16)
    top = c.y
    sw = fitz.Rect(MARGIN, top + 1, MARGIN + 22, top + 12)
    c.page.draw_rect(sw, color=None, fill=fill, fill_opacity=opacity)
    c.page.draw_rect(sw, color=fill, width=0.8)
    c.page.insert_text(fitz.Point(MARGIN + 30, top + 10.5), label, fontname="helv",
                       fontsize=9.5, color=INK)
    c.y = top + 16


def _legend_check(c, label):
    """Legend row whose green swatch shows a '+$' mark, matching the signed dollar
    increase painted in the left margin of each approved carrier line."""
    c.space(16)
    top = c.y
    sw = fitz.Rect(MARGIN, top + 1, MARGIN + 22, top + 12)
    c.page.draw_rect(sw, color=None, fill=APPROVED, fill_opacity=1.0)
    tag = "+$"
    tw = fitz.get_text_length(tag, "hebo", 7.5)
    c.page.insert_text(fitz.Point(MARGIN + (22 - tw) / 2, top + 9.3), tag,
                       fontname="hebo", fontsize=7.5, color=_readable_on(APPROVED))
    c.page.insert_text(fitz.Point(MARGIN + 30, top + 10.5), label, fontname="helv",
                       fontsize=9.5, color=INK)
    c.y = top + 16


# === SECTION: detail pages (appended) ===
_STATEMENT_LABELS = {
    "MATCHING": "Matching exclusion",
    "DEPRECIATION_ACV": "Depreciation / actual cash value",
    "ORDINANCE_CODE": "Ordinance or law / code",
    "POLICY_EXCLUSION": "Policy exclusions",
}
_THEME_TITLES = {"MATCHING": "Matching", "CODE": "Code / ordinance",
                 "UNEXPLAINED": "No stated reason",
                 "COVERAGE_LIMIT": "Coverage sublimit"}


def _detail_pages(doc, recon, flagged, missing, page_of):
    c = Canvas(doc)   # first appended page
    eff = recon.mode == "effectiveness"

    # --- Approved wins (effectiveness mode) ---
    if eff:
        _approved_section(c, recon)
        c.rule(gap=12)

    # --- Quantity differences (decodes the in-line flags) ---
    c.heading("Quantity differences")
    c.text("Line items both estimates carry where the carrier measured short of the "
           "contractor. The RCV gap is that shortfall in dollars; it is printed in the "
           "left margin of the highlighted line on the carrier page shown in the last "
           "column.", size=9, color=MUTED, gap=8)
    if flagged:
        cols = [180, 52, 52, 52, 78, 42]
        heads = ["Item", "Carrier", "Contr.", "Diff qty", "RCV gap", "Page"]
        aligns = [0, 2, 2, 2, 2, 2]
        c.row(heads, cols, head=True, size=8.5, color=GREEN, fill=SAGE, aligns=aligns)
        for f in flagged:
            loc = page_of.get(f.carrier_number)
            pref = f"p.{loc}" if loc else "-"
            unit = f.unit or ""
            c.row([f.description,
                   f"{_qty(f.carrier_quantity)} {unit}".strip(),
                   f"{_qty(f.contractor_quantity)} {unit}".strip(),
                   _signed_qty(f.quantity_delta),
                   _signed_money(round(f.quantity_delta * f.contractor_unit_price, 2)),
                   pref], cols, size=8.5, aligns=aligns)
    else:
        c.text("None. The carrier's quantities match the contractor on every shared "
               "line.", size=9.5, color=MUTED)

    _grade_revisions_section(c, recon)

    # --- Outstanding / missing scope, grouped by section (matches the painting) ---
    c.rule(gap=12)
    c.heading("Outstanding scope" if eff else "Missing scope")
    c.text(("Supplement scope the carrier has not put in its current estimate, "
            "painted in blue on the carrier pages. " if eff else
            "Contractor scope the carrier estimate omits, painted in salmon on the "
            "carrier pages. ") +
           "Grouped by the section that carries it, largest RCV first. The # is the "
           "contractor line number; RCV is the value the contractor printed.",
           size=9, color=MUTED, gap=8)
    if missing:
        cols = [34, 250, 66, 40, 78]
        aligns = [1, 0, 2, 0, 2]
        order, groups = [], {}
        for s in missing:
            sec = s.section or "Other"
            if sec not in groups:
                groups[sec] = []
                order.append(sec)
            groups[sec].append(s)
        for sec in order:
            if sec in recon.section_outstanding:
                head = f"{sec}   -   {_money(recon.section_outstanding[sec])} net"
            else:
                head = f"{sec}   -   {_money(round(sum(x.dollars for x in groups[sec]), 2))}"
            c.subheading(head)
            c.row(["#", "Item", "Qty", "Unit", "RCV"], cols, head=True, size=8.5,
                  color=GREEN, fill=SAGE, aligns=aligns)
            for s in groups[sec]:
                c.row([str(s.number or ""), s.description, _qty(s.quantity), s.unit,
                       _money(s.dollars)], cols, size=8.5, aligns=aligns)
        # The section nets reconcile to the grand gap on a clean pair; when carrier
        # scope sits in sections with no contractor match, or tax/O&P is outside the
        # leaf subtotals, they drift. Name that so the section figures still tie to
        # the headline.
        sec_sum = round(sum(recon.section_outstanding.values()), 2)
        gap = round(max(0.0, recon.contractor_grand - recon.carrier_grand), 2)
        if recon.section_outstanding and abs(sec_sum - gap) >= 50:
            extra = ""
            if recon.section_unattributed >= 50:
                extra = (f" including {_money(recon.section_unattributed)} of carrier "
                         f"scope in sections with no contractor match")
            c.text(f"Section nets total {_money(sec_sum)}; the reconciled figure is "
                   f"{_money(gap)} after carrier scope the contractor did not rebuild "
                   f"and tax/O&P outside the section subtotals{extra}.",
                   size=8.5, color=MUTED, gap=6)
    else:
        c.text("None. The carrier estimate carries every contractor line item.",
               size=9.5, color=MUTED)

    _bridge_section(c, recon)
    _hypotheses_section(c, recon)
    _statements_section(c, recon)
    return c.pages


def _approved_section(c, recon):
    """Supplement items the carrier approved since the original estimate: brand-new
    lines it added, and existing lines it raised toward the contractor scope. Both
    are marked in green on the carrier pages, each with the dollars it added over
    the original shown in the left margin."""
    added = recon.approved_added
    revised = recon.approved_revised
    c.heading("Approved items")
    c.text(f"Contractor scope the carrier put into its current estimate, "
           f"{_money(recon.approved_dollars)} approved over the original, marked in "
           f"green on the carrier pages with the per-line increase in the left margin. "
           f"\"Added\" is a new line; \"raised\" is an "
           f"existing line the carrier increased toward the contractor.",
           size=9, color=MUTED, gap=8)
    if not added and not revised:
        c.text("None. The carrier's current estimate matches its original line for "
               "line.", size=9.5, color=MUTED)
        return

    if added:
        c.subheading(f"Added lines ({len(added)})", color=APPROVED)
        cols = [34, 300, 56, 40, 78]
        aligns = [1, 0, 2, 0, 2]
        c.row(["#", "Item", "Qty", "Unit", "RCV"], cols, head=True, size=8.5,
              color=APPROVED, fill=SAGE, aligns=aligns)
        for w in sorted(added, key=lambda x: -x.rcv):
            c.row([str(w.number or ""), w.description, _qty(w.quantity), w.unit,
                   _money(w.rcv)], cols, size=8.5, aligns=aligns)

    if revised:
        c.subheading(f"Raised lines ({len(revised)})", color=APPROVED)
        c.text("Existing carrier lines the current estimate increased. The net is the "
               "gain over the original, not the full line RCV.", size=8.5,
               color=MUTED, gap=6)
        cols = [26, 168, 96, 96, 58]
        aligns = [1, 0, 2, 2, 2]
        c.row(["#", "Item", "Was", "Now", "Net"], cols, head=True, size=8.5,
              color=APPROVED, fill=SAGE, aligns=aligns)
        for w in revised:
            c.row([str(w.number or ""), w.description,
                   f"{_qty(w.from_quantity)}{w.unit} {_money(w.from_rcv)}",
                   f"{_qty(w.quantity)}{w.unit} {_money(w.rcv)}",
                   _signed_money(w.delta)], cols, size=8, aligns=aligns)


def _grade_revisions_section(c, recon):
    """Contractor lines that replace a carrier line under a different name (a grade
    change, e.g. corrugated -> ribbed). The carrier carries the old item, so the net
    is the price difference, not the full RCV."""
    revs = [s for s in recon.suggestions if getattr(s, "replaces_number", 0)]
    if not revs:
        return
    c.rule(gap=12)
    c.heading("Grade revisions")
    c.text("Contractor lines that replace a carrier line under a different name. The "
           "carrier already carries the old item, so the net is the price difference, "
           "not the full RCV.", size=9, color=MUTED, gap=8)
    cols = [150, 62, 140, 60, 56]
    aligns = [0, 2, 0, 2, 2]
    c.row(["Contractor item", "RCV", "Replaces (carrier)", "RCV", "Net"], cols,
          head=True, size=8.5, color=GREEN, fill=SAGE, aligns=aligns)
    for s in sorted(revs, key=lambda s: -s.net_delta):
        c.row([f"#{s.number} {s.description}", _money(s.dollars),
               f"#{s.replaces_number} {s.replaces_desc}", _money(s.replaces_rcv),
               _signed_money(s.net_delta)], cols, size=8, aligns=aligns)


def _bridge_section(c, recon):
    b = recon.bridge
    if not b:
        return
    c.rule(gap=12)
    c.heading("RCV reconciliation")
    c.text("How the carrier's RCV reconciles to the contractor's, line by line. A "
           "residual near zero means every dollar of the gap is accounted for.",
           size=9, color=MUTED, gap=8)
    labels = [
        ("Carrier RCV", b.get("carrier_rcv")),
        ("+ Missing line items", b.get("missing_base")),
        ("+ Quantity / price delta on shared items", b.get("matched_delta")),
        ("- Items only the carrier carries", b.get("carrier_only_base")),
        ("+ Overhead & Profit gap", b.get("op_gap")),
        ("+ Sales tax gap", b.get("tax_gap")),
        ("= Predicted contractor RCV", b.get("predicted_contractor_rcv")),
        ("Actual contractor RCV", b.get("actual_contractor_rcv")),
        ("Residual (unexplained)", b.get("residual")),
    ]
    w = [PAGE_W - 2 * MARGIN - 110, 110]
    for lab, val in labels:
        if val is None:
            continue
        emph = lab.startswith(("=", "Actual"))
        c.row([lab, _money(val)], w, size=9.5, aligns=[0, 2],
              font="hebo" if emph else "helv",
              color=GREEN if emph else INK)


def _hypotheses_section(c, recon):
    if not recon.hypotheses:
        return
    c.rule(gap=12)
    c.heading("Why the carrier omitted these")
    c.text("Each cluster of missing items and the reason it is out. A green badge "
           "marks a reason the carrier's own estimate states; an amber badge is our "
           "read, for the carrier to confirm.", size=9, color=MUTED, gap=8)
    for h in recon.hypotheses:
        title = _THEME_TITLES.get(h.theme, h.theme)
        head = title if title == h.label else f"{title} - {h.label}"
        c.subheading(f"{head}   ({_money(h.dollars)})",
                     color=GREEN if h.basis == "quoted" else (0.42, 0.35, 0.11))
        c.text(h.note, size=9.5, gap=4)
        if h.statement:
            c.quote(h.statement)
        nums = ", ".join(f"#{n}" for n in h.item_numbers)
        c.text(f"Contractor line items: {nums}", size=8.5, color=MUTED, gap=8)


def _statements_section(c, recon):
    if not recon.carrier_statements:
        return
    c.rule(gap=12)
    c.heading("Carrier coverage statements")
    c.text("The carrier's own coverage language, quoted word for word from its "
           "estimate.", size=9, color=MUTED, gap=8)
    by_kind = {}
    for s in recon.carrier_statements:
        by_kind.setdefault(s["kind"], []).append(s["text"])
    for kind, texts in by_kind.items():
        c.subheading(_STATEMENT_LABELS.get(kind, kind))
        for t in texts[:5]:
            c.quote(t)
        if len(texts) > 5:
            c.text(f"(+{len(texts) - 5} more)", size=8.5, color=MUTED, gap=6)


# === SECTION: entry point ===
def mark_up_carrier(carrier, recon, out_path: str) -> dict:
    """Write a marked-up copy of the carrier PDF to `out_path`.

    `carrier` is the parsed Estimate (its `.path` is opened and its `.items` give
    the category and position of every carrier line, so missing scope can be
    painted into the right section). Returns a stats dict for logging.
    """
    flagged = sorted(
        (s for s in recon.shared if s.quantity_delta > 1e-6),
        key=lambda s: -(s.quantity_delta * s.contractor_unit_price))
    missing = [s for s in recon.suggestions if s.status == "MISSING"]

    doc = fitz.open(carrier.path)
    orig_pages = len(doc)

    # Locate every carrier line item once: used to highlight the under-measured
    # lines, to anchor the painted-in outstanding scope by section, and to check
    # off the approved wins.
    located_all = locate_items(doc, {it.number: it.description for it in carrier.items})
    sec_of = {it.number: it.section for it in carrier.items}

    # Highlight each located, under-measured line in place, coloured by its shortfall
    # and labelled with the RCV gap in the margin.
    located_flagged = {}
    for f in flagged:
        loc = located_all.get(f.carrier_number)
        if not loc:
            continue
        located_flagged[f.carrier_number] = loc
        gap = round(f.quantity_delta * f.contractor_unit_price, 2)
        sev = severity_for(gap)
        flag_row(doc.load_page(loc[0]), loc[1], gap, sev)

    # Tag approved wins with the dollars they added over the original: an added
    # line's full RCV, a raised line's increase (delta). approved_wins carries the
    # full current RCV for raised lines, so source the delta from approved_revised.
    won_amount = {it.number: it.rcv for it in getattr(recon, "approved_added", [])}
    won_amount.update({rev.number: rev.delta for rev in getattr(recon, "approved_revised", [])})
    won_count = 0
    for w in getattr(recon, "approved_wins", []):
        loc = located_all.get(w.number)
        amount = won_amount.get(w.number)
        if loc and amount is not None:
            tag_won(doc.load_page(loc[0]), loc[1], amount)
            won_count += 1

    # Paint the missing/outstanding scope onto the carrier pages, in its own
    # section. Salmon when there is no original estimate (scope the carrier omits),
    # blue when there is (scope still to pursue).
    sch = OUTSTANDING_SCHEME if recon.mode == "effectiveness" else MISSING_SCHEME
    painted = paint_outstanding_by_section(doc, missing, located_all, sec_of, sch,
                                           recon.section_outstanding)

    # A located item's final 1-based page = its original index, + 1 for the single
    # summary page prepended below, + 1 to make it 1-based. Appending the detail
    # pages does not move the original pages, so this holds.
    page_of = {num: pno + 2 for num, (pno, _r) in located_flagged.items()}
    detail_pages = _detail_pages(doc, recon, flagged, missing, page_of)
    _summary_page(doc, recon, flagged, missing, len(located_flagged), painted, won_count)

    doc.save(out_path, garbage=4, deflate=True)
    doc.close()

    return {
        "flagged": len(flagged),
        "located": len(located_flagged),
        "missing": len(missing),
        "missing_painted": painted,
        "approved_wins": len(getattr(recon, "approved_wins", [])),
        "won_tagged": won_count,
        "missing_dollars": round(max(0.0, recon.contractor_grand - recon.carrier_grand), 2),
        "missing_section_net": round(sum(recon.section_outstanding.values()), 2),
        "missing_gross": round(sum(s.dollars for s in missing), 2),
        "orig_pages": orig_pages,
        "added_pages": 1 + detail_pages,
    }
