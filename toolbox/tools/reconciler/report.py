"""Render a Recon result to a Markdown report and a CSV line-item diff.

The report has two tables: the missing line items (contractor scope the carrier
omits, grouped by category, largest RCV first) and the shared items (line items
both estimates carry, with the price and quantity breakdown). Overhead & Profit
is shown as a simple applied/not-applied flag, not its own section.
"""

from __future__ import annotations

import csv
import os
from itertools import groupby


def _money(x):
    return f"${x:,.2f}"


def _signed(x):
    return ("+" if x >= 0 else "-") + f"${abs(x):,.2f}"


def _qty(x):
    return f"{x:g}"


def _check(flag):
    return "[x] applied" if flag else "[ ] not applied"


def write_csv(recon, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "category", "description", "unit",
                    "carrier_qty", "contractor_qty", "qty_delta",
                    "carrier_unit_price", "contractor_unit_price", "price_delta",
                    "carrier_rcv", "contractor_rcv", "rcv_delta"])
        for s in recon.suggestions:
            if s.status not in ("MISSING", "SUGGESTED"):
                continue
            w.writerow(["missing", s.category, s.description, s.unit,
                        "0", _qty(s.quantity), _qty(s.quantity),
                        "0.00", f"{s.contractor_unit_price:.2f}",
                        f"{s.contractor_unit_price:.2f}",
                        "0.00", f"{s.dollars:.2f}", f"{s.dollars:.2f}"])
        for s in recon.shared:
            w.writerow(["shared", s.category, s.description, s.unit,
                        _qty(s.carrier_quantity), _qty(s.contractor_quantity),
                        _qty(s.quantity_delta),
                        f"{s.carrier_unit_price:.2f}", f"{s.contractor_unit_price:.2f}",
                        f"{s.price_delta:.2f}",
                        f"{s.carrier_rcv:.2f}", f"{s.contractor_rcv:.2f}",
                        f"{s.rcv_delta:.2f}"])
    return path


def _missing_by_category(recon):
    rows = [s for s in recon.suggestions if s.status in ("MISSING", "SUGGESTED")]
    if not rows:
        return "_No missing line items detected._"
    out = []
    for cat, group in groupby(rows, key=lambda s: s.category):
        group = list(group)
        subtotal = round(sum(s.dollars for s in group), 2)
        out.append(f"### {cat} ({_money(subtotal)})")
        out.append("")
        out.append("| Item | Qty | Unit | RCV (from estimate) |")
        out.append("|---|---:|---|---:|")
        for s in group:
            out.append(f"| {s.description} | {_qty(s.quantity)} | {s.unit} "
                       f"| {_money(s.dollars)} |")
        out.append("")
    return "\n".join(out)


def _shared_table(recon):
    if not recon.shared:
        return ""
    out = ["| Category | Item | Carrier qty | Contr. qty | Delta qty "
           "| Carrier $/u | Contr. $/u | Delta $/u "
           "| Carrier RCV | Contr. RCV | Delta RCV |",
           "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in recon.shared:
        out.append(
            f"| {s.category} | {s.description} "
            f"| {_qty(s.carrier_quantity)} | {_qty(s.contractor_quantity)} "
            f"| {_qty(s.quantity_delta)} "
            f"| {_money(s.carrier_unit_price)} | {_money(s.contractor_unit_price)} "
            f"| {_signed(s.price_delta)} "
            f"| {_money(s.carrier_rcv)} | {_money(s.contractor_rcv)} "
            f"| {_signed(s.rcv_delta)} |")
    return "\n".join(out)


def render_markdown(recon):
    gap = round(recon.contractor_grand - recon.carrier_grand, 2)
    L = [f"# Reconciliation: {recon.claimant}", ""]
    L.append(f"- Carrier estimate: `{recon.carrier_name}` "
             f"(RCV {_money(recon.carrier_grand)})")
    L.append(f"- Contractor estimate: `{recon.contractor_name}` "
             f"(RCV {_money(recon.contractor_grand)})")
    L.append(f"- RCV gap (contractor - carrier): **{_money(gap)}**")
    L.append(f"- Estimated recoverable: **{_money(recon.est_recoverable)}**")
    L.append(f"- Carrier Overhead & Profit: {_check(recon.carrier_has_op)}")
    L.append(f"- Contractor Overhead & Profit: {_check(recon.contractor_has_op)}")
    L.append("")
    for n in recon.notes:
        L.append(f"> Note: {n}")
        L.append("")

    L.append("## Missing line items")
    L.append("_In the contractor scope, absent from the carrier estimate._")
    L.append("")
    L.append(_missing_by_category(recon))
    L.append("")

    shared = _shared_table(recon)
    if shared:
        L.append("## Shared items")
        L.append("_Line items both estimates carry, with price and quantity "
                 "differences._")
        L.append("")
        L.append(shared)
        L.append("")
    return "\n".join(L)


def render_summary(recons):
    L = ["# Reconciliation summary", "",
         "One row per carrier estimate. Recoverable = additional RCV the "
         "contractor scope supports beyond the carrier.", "",
         "| Claimant | Carrier RCV | Contractor RCV | Recoverable | "
         "Carrier O&P | Missing items |",
         "|---|---:|---:|---:|:---:|---:|"]
    total_rec = 0.0
    for r in sorted(recons, key=lambda x: -x.est_recoverable):
        n_missing = sum(1 for s in r.suggestions
                        if s.status in ("MISSING", "SUGGESTED"))
        L.append(f"| {r.claimant} | {_money(r.carrier_grand)} | "
                 f"{_money(r.contractor_grand)} | {_money(r.est_recoverable)} | "
                 f"{'yes' if r.carrier_has_op else 'NO'} | {n_missing} |")
        total_rec += r.est_recoverable
    L.append(f"| **Total** | | | **{_money(total_rec)}** | | |")
    L.append("")
    return "\n".join(L)


def write_report(recon, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    safe = recon.claimant.replace(" ", "_").replace("/", "-")
    md = os.path.join(out_dir, f"{safe}.md")
    csvp = os.path.join(out_dir, f"{safe}.csv")
    with open(md, "w", encoding="utf-8") as f:
        f.write(render_markdown(recon))
    write_csv(recon, csvp)
    return md, csvp
