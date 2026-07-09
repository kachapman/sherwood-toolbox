"""Log a reconciliation to disk instead of rendering it to the screen.

The visual-estimating flow does not display the missing items, shared deltas,
bridge, and hypotheses in the browser; it writes them to a per-run log and paints
the summary onto the carrier PDF. This module owns the log: a timestamped set of
files under one directory, plus a one-line entry on the app logger.

Three formats are written so the found data is recoverable however it is needed:

  * ``<claimant>-<stamp>.md``   the same human-readable report the tool used to
                                show on screen (reused from report.py);
  * ``<claimant>-<stamp>.json`` a structured snapshot for downstream tooling;
  * ``<claimant>-<stamp>.csv``  the line-item diff (reused from report.py).

Raw uploaded PDFs are still deleted after parsing; only this derived record is
kept, so the log directory is the one place reconciliation output persists.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime

from .report import render_markdown, write_csv

log = logging.getLogger("reconciler")


def _safe(name: str) -> str:
    return (name or "reconciliation").replace(" ", "_").replace("/", "-")


def _snapshot(recon, *, markup_stats, sides, warnings) -> dict:
    """A JSON-serializable record of everything the reconciliation found."""
    missing = [asdict(s) for s in recon.suggestions if s.status == "MISSING"]
    snap = {
        "logged_at": datetime.now().isoformat(timespec="seconds"),
        "claimant": recon.claimant,
        "mode": recon.mode,
        "carrier_name": recon.carrier_name,
        "contractor_name": recon.contractor_name,
        "carrier_grand": recon.carrier_grand,
        "contractor_grand": recon.contractor_grand,
        "gap": round(recon.contractor_grand - recon.carrier_grand, 2),
        "est_recoverable": recon.est_recoverable,
        "carrier_has_op": recon.carrier_has_op,
        "contractor_has_op": recon.contractor_has_op,
        "missing_items": missing,
        "missing_total": round(sum(m["dollars"] for m in missing), 2),
        "shared_items": [asdict(s) for s in recon.shared],
        "bridge": recon.bridge,
        "denial_hypotheses": [asdict(h) for h in recon.hypotheses],
        "carrier_statements": recon.carrier_statements,
        "notes": recon.notes,
        "markup": markup_stats or {},
        "sides": sides or {},
        "warnings": [w for w in (warnings or []) if w],
    }
    if recon.mode == "effectiveness":
        snap["effectiveness"] = {
            "og_name": recon.og_name,
            "og_grand": recon.og_grand,
            "ask": recon.ask_dollars,
            "approved_to_date": recon.approved_dollars,
            "outstanding": recon.outstanding_dollars,
            "rate": recon.effectiveness,
            "approved_wins": [asdict(w) for w in recon.approved_wins],
            "approved_added": [asdict(w) for w in recon.approved_added],
            "approved_revised": [asdict(w) for w in recon.approved_revised],
        }
    return snap


def log_reconciliation(recon, out_dir, *, markup_stats=None, sides=None,
                       warnings=None) -> dict:
    """Write the timestamped .md/.json/.csv log for one reconciliation.

    Returns the three paths. Also emits a one-line summary on the ``reconciler``
    logger so a run is traceable in the app's console output.
    """
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now()
    # Millisecond suffix so two runs in the same second do not overwrite a log.
    stamp = now.strftime("%Y%m%d-%H%M%S-") + f"{now.microsecond // 1000:03d}"
    base = f"{_safe(recon.claimant)}-{stamp}"
    md_path = os.path.join(out_dir, base + ".md")
    json_path = os.path.join(out_dir, base + ".json")
    csv_path = os.path.join(out_dir, base + ".csv")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(recon))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_snapshot(recon, markup_stats=markup_stats, sides=sides,
                            warnings=warnings), f, indent=2, default=str)
    write_csv(recon, csv_path)

    n_missing = sum(1 for s in recon.suggestions if s.status == "MISSING")
    m = markup_stats or {}
    log.info("reconciled %s: carrier %.2f vs contractor %.2f (gap %.2f); "
             "%d missing, %d quantity gaps flagged, %d highlighted in place; "
             "logged to %s", recon.claimant, recon.carrier_grand,
             recon.contractor_grand, recon.contractor_grand - recon.carrier_grand,
             n_missing, m.get("flagged", 0), m.get("located", 0), md_path)

    return {"md": md_path, "json": json_path, "csv": csv_path, "base": base}
