"""HTTP layer for the Estimate Reconciler (visual-estimating flow). Holds the
blueprint, wires the upload directory from toolbox config, and calls the pure
engine (extract -> reconcile -> mark up + log). Edit routes here; edit comparison
behavior in reconcile.py / match.py; edit PDF text extraction in extract.py; edit
the carrier markup in markup.py; edit what is logged in logbook.py.

Unlike the original report flow, the found data is not returned for on-screen
tables: it is written to a persistent per-run log (logbook), and the difference is
painted onto the carrier PDF (markup). The response carries only the headline
figures, the counts, and the download link for that marked-up PDF. Raw uploads are
still deleted after parsing; only the derived log persists.
"""
import os
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from ...config import Config
from . import logbook, markup, match, playbook as playbook_mod
from .extract import extract_estimate
from .reconcile import reconcile_effectiveness, reconcile_matched

bp = Blueprint(
    "reconciler",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="static",
)

# The playbook powers the secondary "commonly added" projection; it is bundled
# beside this package as data. Absent or unreadable, reconciliation still runs.
_PLAYBOOK_PATH = Path(__file__).resolve().parent / "playbook.json"
try:
    PLAYBOOK = playbook_mod.load_playbook(str(_PLAYBOOK_PATH))
except Exception:
    PLAYBOOK = None


# === SECTION: helpers ===
def _upload_dir():
    d = Path(Config.UPLOAD_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _log_dir():
    """Where the persistent reconciliation logs live. Separate from the transient
    upload dir so the marked-up PDF can be served once and deleted while the log
    stays."""
    d = Path(Config.DATA_DIR) / "reconciler-logs"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def cleanup_file(filepath):
    """Delete a file if it exists (no permanent storage)."""
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError as e:
            print(f"Error deleting {filepath}: {e}")


def _save_upload(file_storage):
    """Persist one upload under UPLOAD_DIR, returning its path (or None)."""
    if not file_storage or not file_storage.filename:
        return None
    name = secure_filename(file_storage.filename)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    path = os.path.join(_upload_dir(), name)
    file_storage.save(path)
    return path


def _claimant_from(contractor_name, carrier_name):
    """A safe display/base name for the report files, from the contractor
    surname (contractor files are named SURNAME-Initial_...), else the carrier."""
    s = match.surname(contractor_name, "contractor")
    if s == "unknown":
        s = match.surname(carrier_name, "carrier")
    base = secure_filename(s.title()) or "reconciliation"
    return base


def _scan_warning(carrier, contractor):
    """One caveat covering any image-only input, or None."""
    parts = []
    for est, label in ((carrier, "carrier"), (contractor, "contractor")):
        if not est.image_only:
            continue
        if est.ocr:
            parts.append(
                f"The {label} estimate is an image-only scan; its figures were "
                f"recovered by OCR and are approximate. Re-export it as a text PDF "
                f"for an exact reconciliation.")
        else:
            parts.append(
                f"The {label} estimate is an image-only scan and Tesseract OCR is "
                f"not installed, so no line items could be read from it. Install "
                f"Tesseract or provide a text-based PDF.")
    return " ".join(parts) if parts else None


def _swap_hint(carrier, contractor):
    """If the file placed in the contractor slot carries no O&P or recap but the
    carrier one does, the slots were probably swapped. The labeled slots stay the
    source of truth; this is only a hint."""
    contractor_bare = not contractor.has_op and not contractor.recap
    carrier_rich = carrier.has_op or bool(carrier.recap)
    if contractor_bare and carrier_rich:
        return ("The contractor estimate shows no Overhead & Profit or category "
                "recap, but the carrier one does. If the two files were placed in "
                "the wrong slots, swap them and run again.")
    return None


def _side(est):
    return {
        "name": est.name,
        "grand_rcv": est.grand_rcv,
        "confidence": est.confidence,
        "ocr": est.ocr,
        "image_only": est.image_only,
        "has_op": est.has_op,
        "fmt": est.fmt,
        "items": len(est.items),
    }


# === SECTION: routes ===
@bp.route("/")
def index():
    return render_template("reconciler.html")


@bp.route("/run", methods=["POST"])
def run():
    carrier_path = contractor_path = og_path = None
    try:
        carrier_path = _save_upload(request.files.get("carrier"))
        contractor_path = _save_upload(request.files.get("contractor"))
        og_path = _save_upload(request.files.get("og"))   # optional original carrier
        if not carrier_path or not contractor_path:
            return jsonify({"error": "Upload both a carrier estimate and a "
                                     "contractor estimate."}), 400

        carrier = extract_estimate(carrier_path, "carrier")
        contractor = extract_estimate(contractor_path, "contractor")
        og = extract_estimate(og_path, "og") if og_path else None

        # The contractor and original PDFs are parsed and no longer needed; the
        # current carrier PDF is kept until it has been marked up.
        cleanup_file(contractor_path)
        cleanup_file(og_path)
        contractor_path = og_path = None

        if not carrier.items and carrier.grand_rcv == 0 and \
                not contractor.items and contractor.grand_rcv == 0:
            return jsonify({"error": "Could not read line items or totals from "
                                     "either PDF. They may be image-only scans "
                                     "without OCR, or an unsupported format."}), 422

        claimant = _claimant_from(contractor.name, carrier.name)
        if og is not None:
            recon = reconcile_effectiveness(og, carrier, contractor, claimant, PLAYBOOK)
        else:
            recon = reconcile_matched(carrier, contractor, claimant, PLAYBOOK)

        # Paint the difference onto the carrier estimate: the primary deliverable.
        markup_name = f"{claimant}-carrier-markup.pdf"
        markup_path = os.path.join(_upload_dir(), markup_name)
        stats = markup.mark_up_carrier(carrier, recon, markup_path)

        # Carrier PDF has served its purpose; keep no raw upload.
        cleanup_file(carrier_path)
        carrier_path = None

        scanned_warning = _scan_warning(carrier, contractor)
        swap_hint = _swap_hint(carrier, contractor)

        # Log the found data instead of returning it for on-screen tables.
        log_paths = logbook.log_reconciliation(
            recon, _log_dir(), markup_stats=stats,
            sides={"carrier": _side(carrier), "contractor": _side(contractor)},
            warnings=[scanned_warning, swap_hint])

        n_missing = sum(1 for s in recon.suggestions if s.status == "MISSING")
        payload = {
            "claimant": recon.claimant,
            "mode": recon.mode,
            "narrative": recon.narrative,
            "gap": round(recon.contractor_grand - recon.carrier_grand, 2),
            "est_recoverable": recon.est_recoverable,
            "carrier": _side(carrier),
            "contractor": _side(contractor),
            "counts": {
                "missing": n_missing,
                "missing_dollars": stats.get("missing_dollars", 0.0),
                "missing_painted": stats.get("missing_painted", 0),
                "flagged": stats.get("flagged", 0),
                "located": stats.get("located", 0),
                "added_pages": stats.get("added_pages", 0),
            },
            "notes": recon.notes,
            "scanned_warning": scanned_warning,
            "swap_hint": swap_hint,
            "markup_download": url_for("reconciler.download_file", name=markup_name),
            "log_path": log_paths["md"],
        }
        if recon.mode == "effectiveness":
            payload["effectiveness"] = {
                "og_name": recon.og_name,
                "og_grand": recon.og_grand,
                "carrier_grand": recon.carrier_grand,
                "contractor_grand": recon.contractor_grand,
                "ask": recon.ask_dollars,
                "approved": recon.approved_dollars,
                "outstanding": recon.outstanding_dollars,
                "rate": recon.effectiveness,
                "approved_wins": stats.get("approved_wins", 0),
                "won_tagged": stats.get("won_tagged", 0),
            }
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cleanup_file(carrier_path)
        cleanup_file(contractor_path)
        cleanup_file(og_path)


@bp.route("/download/<name>")
def download_file(name):
    """Serve a generated file from the upload dir once, then delete it. The
    marked-up carrier PDF is the deliverable; the .md/.csv paths remain valid for
    any caller that still requests them."""
    safe = secure_filename(name)
    if not safe or not safe.lower().endswith((".pdf", ".md", ".csv")):
        return "File not found", 404
    filepath = os.path.join(_upload_dir(), safe)
    if os.path.exists(filepath):
        response = send_file(filepath, as_attachment=True)
        cleanup_file(filepath)
        return response
    return "File not found", 404
