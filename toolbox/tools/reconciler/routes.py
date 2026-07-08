"""HTTP layer for the Estimate Reconciler. Holds the blueprint, wires the upload
directory from toolbox config, and calls the pure engine (extract -> reconcile ->
report). Edit routes here; edit comparison behavior in reconcile.py / match.py;
edit PDF text extraction in extract.py.

Modeled on estimate_enhancer/routes.py: uploads land in Config.UPLOAD_DIR, the
generated .md/.csv are served once and deleted, and nothing is stored permanently.
"""
import os
from dataclasses import asdict
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from ...config import Config
from . import match, playbook as playbook_mod
from .extract import extract_estimate
from .reconcile import reconcile_matched
from .report import write_report

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
    carrier_path = contractor_path = None
    try:
        carrier_path = _save_upload(request.files.get("carrier"))
        contractor_path = _save_upload(request.files.get("contractor"))
        if not carrier_path or not contractor_path:
            return jsonify({"error": "Upload both a carrier estimate and a "
                                     "contractor estimate."}), 400

        carrier = extract_estimate(carrier_path, "carrier")
        contractor = extract_estimate(contractor_path, "contractor")

        # Source PDFs are no longer needed once parsed; keep no permanent storage.
        cleanup_file(carrier_path)
        cleanup_file(contractor_path)
        carrier_path = contractor_path = None

        if not carrier.items and carrier.grand_rcv == 0 and \
                not contractor.items and contractor.grand_rcv == 0:
            return jsonify({"error": "Could not read line items or totals from "
                                     "either PDF. They may be image-only scans "
                                     "without OCR, or an unsupported format."}), 422

        claimant = _claimant_from(contractor.name, carrier.name)
        recon = reconcile_matched(carrier, contractor, claimant, PLAYBOOK)

        md_path, csv_path = write_report(recon, _upload_dir())

        missing = [{
            "number": s.number,       # line number in the contractor estimate
            "category": s.category,
            "description": s.description,
            "quantity": s.quantity,
            "unit": s.unit,
            "rcv": s.dollars,          # RCV as printed in the contractor estimate
        } for s in recon.suggestions if s.status == "MISSING"]

        return jsonify({
            "claimant": recon.claimant,
            "gap": round(recon.contractor_grand - recon.carrier_grand, 2),
            "est_recoverable": recon.est_recoverable,
            "missing": missing,
            "shared": [asdict(s) for s in recon.shared],
            "carrier_statements": recon.carrier_statements,
            "denial_hypotheses": [asdict(h) for h in recon.hypotheses],
            "notes": recon.notes,
            "carrier": _side(carrier),
            "contractor": _side(contractor),
            "scanned_warning": _scan_warning(carrier, contractor),
            "swap_hint": _swap_hint(carrier, contractor),
            "downloads": {
                "md": url_for("reconciler.download_file",
                              name=os.path.basename(md_path)),
                "csv": url_for("reconciler.download_file",
                               name=os.path.basename(csv_path)),
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cleanup_file(carrier_path)
        cleanup_file(contractor_path)


@bp.route("/download/<name>")
def download_file(name):
    """Serve a generated .md/.csv report once, then delete it."""
    safe = secure_filename(name)
    if not safe or not safe.lower().endswith((".md", ".csv")):
        return "File not found", 404
    filepath = os.path.join(_upload_dir(), safe)
    if os.path.exists(filepath):
        response = send_file(filepath, as_attachment=True)
        cleanup_file(filepath)
        return response
    return "File not found", 404
