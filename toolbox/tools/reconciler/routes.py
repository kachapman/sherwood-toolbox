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
import time
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from ...config import Config
from . import crm, logbook, markup, match, playbook as playbook_mod
from .extract import extract_estimate
from .reconcile import OG_MIN_PARSE_RATIO, reconcile_effectiveness, reconcile_matched

bp = Blueprint(
    "reconciler",
    __name__,
    template_folder="templates",
    static_folder="static",
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


def _sweep_stale_markups(max_age=1800):
    """Delete markup PDFs in the upload dir older than max_age seconds. The markup
    now survives its download so it can also be posted to the CRM, so this bounds
    accumulation instead of the old delete-on-serve. Never fatal (a read-only dir
    must not fail a run)."""
    try:
        now = time.time()
        for p in Path(_upload_dir()).glob("*-carrier-markup.pdf"):
            try:
                if now - p.stat().st_mtime > max_age:
                    p.unlink()
            except OSError:
                pass
    except Exception as e:
        print(f"Reconciler markup sweep skipped: {e}")


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


def _resolve_slot(file_key, id_key, name_key):
    """A slot is filled by an uploaded file or, failing that, a CRM file the user
    picked (downloaded here by its numeric id). The CRM file keeps its real title
    so the surname / carrier detection still works. Returns a local path or None."""
    fs = request.files.get(file_key)
    if fs and fs.filename:
        return _save_upload(fs)
    file_id = (request.form.get(id_key) or "").strip()
    if not file_id:
        return None
    title = (request.form.get(name_key) or "").strip() or f"crm_{file_id}.pdf"
    name = secure_filename(title)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    dest = os.path.join(_upload_dir(), name)
    crm.download_file(file_id, dest)
    return dest


def _claimant_from(contractor_name, carrier_name):
    """A safe display/base name for the report files, from the contractor
    surname (contractor files are named SURNAME-Initial_...), else the carrier."""
    s = match.surname(contractor_name, "contractor")
    if s == "unknown":
        s = match.surname(carrier_name, "carrier")
    base = secure_filename(s.title()) or "reconciliation"
    return base


# Signature line on any reconciliation error posted to the CRM, so a note on the
# job reads as the bot's own message. Exact wording is fixed; it sits on its own
# line below a blank line (see crm_error_note).
ERROR_MESSENGER_SIGNATURE = "-- Reconciliation Bot Error Messenger"


def _file_error(msg, status=422):
    """A JSON error for a provided file the tool could not process. Flagged
    `crm_postable` so the browser can offer to log the message on the CRM job."""
    return jsonify({"error": msg, "crm_postable": True}), status


def _image_only_error(og, carrier, contractor):
    """A blocking message when any provided file has no readable text layer. OCR
    is mothballed, so a scanned / image-only PDF cannot be processed; the user
    needs a text-based (digitally exported) PDF."""
    labels = []
    if carrier is not None and carrier.image_only:
        labels.append("current carrier estimate")
    if contractor is not None and contractor.image_only:
        labels.append("contractor supplement")
    if og is not None and og.image_only:
        labels.append("original carrier estimate")
    if not labels:
        return None
    which = labels[0] if len(labels) == 1 else \
        ", ".join(labels[:-1]) + " and " + labels[-1]
    return (f"No readable text found in the {which}. The reconciler needs "
            f"text-based (digitally exported) PDFs; a scanned or image-only PDF "
            f"cannot be read. Re-export or print the estimate to a PDF from the "
            f"estimating software, then try again.")


def _degraded_original_error(og):
    """A blocking message when the original carrier estimate has a text layer but
    its line-item table did not parse (a scanned/OCR original whose totals read
    cleanly while the body is garbled). Its line items cannot seed the
    original-vs-current approval diff, so the three-way run is refused rather than
    painting false green 'approved' checks on scope that was already in the
    original. Only fires in effectiveness mode (an original was supplied)."""
    if og is None or og.parse_ratio >= OG_MIN_PARSE_RATIO:
        return None
    return (f"The original carrier estimate could not be read into line items: "
            f"only ${og.rcv_line_sum:,.0f} of its ${og.grand_rcv:,.0f} total parsed "
            f"(it appears to be a scanned or OCR PDF).\n"
            f"Re-export the original as a digital (non-scanned) PDF from the "
            f"estimating software, then try again.")


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


def _money(x):
    """$1,234.56 style, matching the on-screen figures."""
    v = float(x or 0)
    return ("-$" if v < 0 else "$") + f"{abs(v):,.2f}"


def _crm_note(recon):
    """The activity-feed note posted with the marked-up estimate: the base lines
    plus a bold + underlined one-line summary of the numbers. CRM history renders
    HTML, so <b>/<u>/<br> are used. Effectiveness mode mirrors the Approval
    Effectiveness tiles (increase ratio, new RCV, total increase to date); the
    two-file mode summarizes the RCV gap instead."""
    base = ("Reconciliation bot finished it's terrible purpose:<br><br>"
            "the marked up Carrier Estimate is Attached to the file.")
    if recon.mode == "effectiveness":
        pct = round((recon.effectiveness or 0) * 100)
        math = (f"Bot math: Increase ratio: {pct}%. "
                f"New RCV {_money(recon.carrier_grand)} "
                f"(Total increase to date: {_money(recon.approved_dollars)}).")
    else:
        gap = recon.contractor_grand - recon.carrier_grand
        math = (f"Bot math: Carrier RCV {_money(recon.carrier_grand)}. "
                f"Contractor RCV {_money(recon.contractor_grand)}. "
                f"Recoverable gap {_money(gap)}.")
    return f"{base}<br><br><b><u>{math}</u></b>"


# === SECTION: routes ===
@bp.route("/")
def index():
    return render_template("reconciler.html")


# === SECTION: CRM fetch (OnlyOffice) ===
@bp.route("/crm/search", methods=["POST"])
def crm_search():
    """Deals whose title matches the query, for the fetch panel's picker."""
    query = (request.form.get("query") or "").strip()
    if len(query) < 2:
        return jsonify({"ok": False, "error": "Type at least two characters."})
    try:
        return jsonify({"ok": True, "deals": crm.search_deals(query)})
    except crm.CrmError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"CRM search failed: {e}"})


@bp.route("/crm/files", methods=["POST"])
def crm_files():
    """A deal's PDF documents, ranked with the three slots pre-guessed."""
    deal_id = (request.form.get("deal_id") or "").strip()
    if not deal_id.isdigit():
        return jsonify({"ok": False, "error": "Pick a deal first."})
    try:
        result = crm.deal_files(deal_id)
        return jsonify({"ok": True, **result})
    except crm.CrmError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not list the deal's files: {e}"})


@bp.route("/crm/upload", methods=["POST"])
def crm_upload():
    """Attach an already-generated markup PDF to a CRM deal. The browser holds the
    deal id and the file name from the run, so it posts them here; the file only
    leaves this machine to land on the deal it belongs to, then is deleted."""
    deal_id = (request.form.get("deal_id") or "").strip()
    if not deal_id.isdigit():
        return jsonify({"ok": False, "error": "Enter a valid CRM deal: a numeric id or a deal URL."})
    name = secure_filename(request.form.get("name") or "")
    if not name.lower().endswith(".pdf"):
        return jsonify({"ok": False, "error": "No marked-up PDF to post."})
    path = os.path.join(_upload_dir(), name)
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "The marked-up PDF has expired; run the "
                                              "reconciliation again, then post."})
    # The note (with the bot-math summary) is built server-side in run() and sent
    # back with the post; fall back to the plain default if it is missing.
    note = (request.form.get("note") or "").strip() or crm.ATTACH_NOTE
    try:
        result = crm.upload_file(deal_id, path, title=name, note=note)
        cleanup_file(path)          # posted to the CRM; keep no local copy
        return jsonify({"ok": True, "file_id": result.get("file_id")})
    except crm.CrmError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not post to the CRM: {e}"})


@bp.route("/crm/error-note", methods=["POST"])
def crm_error_note():
    """Post a reconciliation error message to a CRM deal as a plain note (no file),
    signed by the bot. The browser sends the deal id and the exact error text the
    run returned; the ERROR_MESSENGER_SUFFIX is appended here so the signature is
    consistent and server-controlled. Only the numeric deal id crosses the wire."""
    deal_id = (request.form.get("deal_id") or "").strip()
    if not deal_id.isdigit():
        return jsonify({"ok": False, "error": "Enter a valid CRM deal: a numeric id or a deal URL."})
    message = (request.form.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "No error message to post."})
    # CRM history renders HTML: carry the message's own line breaks (\n -> <br>) and
    # drop the signature onto its own line below a blank line.
    body = message.replace("\r\n", "\n").replace("\n", "<br>")
    content = f"{body}<br><br>{ERROR_MESSENGER_SIGNATURE}"
    try:
        crm.post_note(deal_id, content)
        return jsonify({"ok": True, "posted": content})
    except crm.CrmError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not post to the CRM: {e}"})


@bp.route("/run", methods=["POST"])
def run():
    _sweep_stale_markups()
    carrier_path = contractor_path = og_path = None
    try:
        carrier_path = _resolve_slot("carrier", "carrier_file_id", "carrier_file_name")
        contractor_path = _resolve_slot("contractor", "contractor_file_id",
                                        "contractor_file_name")
        og_path = _resolve_slot("og", "og_file_id", "og_file_name")   # optional
        if not carrier_path or not contractor_path:
            return jsonify({"error": "Provide a current carrier estimate and a "
                                     "contractor supplement (upload or from the "
                                     "CRM)."}), 400

        carrier = extract_estimate(carrier_path, "carrier")
        contractor = extract_estimate(contractor_path, "contractor")
        og = extract_estimate(og_path, "og") if og_path else None

        # The contractor and original PDFs are parsed and no longer needed; the
        # current carrier PDF is kept until it has been marked up.
        cleanup_file(contractor_path)
        cleanup_file(og_path)
        contractor_path = og_path = None

        # No readable text layer in a provided file: OCR is mothballed, so warn
        # the user plainly instead of returning a meaningless reconciliation.
        img_err = _image_only_error(og, carrier, contractor)
        if img_err:
            return _file_error(img_err)

        # Original present but its line table did not parse (scanned/OCR): its items
        # cannot seed the approval diff, so refuse rather than paint false checks.
        deg_err = _degraded_original_error(og)
        if deg_err:
            return _file_error(deg_err)

        if not carrier.items and carrier.grand_rcv == 0 and \
                not contractor.items and contractor.grand_rcv == 0:
            return _file_error("Could not read line items or totals from "
                               "either PDF. They may be an unsupported "
                               "format or not estimate documents.")

        claimant = _claimant_from(contractor.name, carrier.name)
        if og is not None:
            recon = reconcile_effectiveness(og, carrier, contractor, claimant, PLAYBOOK)
        else:
            recon = reconcile_matched(carrier, contractor, claimant, PLAYBOOK)

        # Late guard: the original parsed past the ratio floor, but the added-lines
        # total is still grossly inconsistent with the grand-total approval delta
        # (description drift or duplicate-line consumption). Refuse before painting.
        if getattr(recon, "og_line_diff_unreliable", False):
            return _file_error("The original carrier estimate could not be "
                               "matched reliably against the current one: "
                               + recon.og_line_diff_reason
                               + ". Provide a digital (non-scanned) original PDF, or "
                               "check that the two carrier files are the same claim.")

        # Paint the difference onto the carrier estimate: the primary deliverable.
        markup_name = f"{claimant}-carrier-markup.pdf"
        markup_path = os.path.join(_upload_dir(), markup_name)
        
        if not os.path.exists(carrier_path):
            print(f"[reconciler] ERROR: Carrier file missing at {carrier_path}")
            print(f"[reconciler] Carrier object path: {carrier.path}")
            return _file_error("Carrier PDF file was deleted unexpectedly before processing. Please re-upload and try again.")
        
        print(f"[reconciler] Processing carrier: {carrier_path}")
        stats = markup.mark_up_carrier(carrier, recon, markup_path)

        # Carrier PDF has served its purpose; keep no raw upload.
        cleanup_file(carrier_path)
        carrier_path = None

        swap_hint = _swap_hint(carrier, contractor)

        # Log the found data instead of returning it for on-screen tables. Never
        # fatal: on a container the log dir may be read-only, and a missing log
        # must not fail the reconciliation the user is waiting on.
        try:
            log_paths = logbook.log_reconciliation(
                recon, _log_dir(), markup_stats=stats,
                sides={"carrier": _side(carrier), "contractor": _side(contractor)},
                warnings=[swap_hint])
        except Exception as log_err:
            print(f"Reconciler log write failed (continuing): {log_err}")
            log_paths = {}

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
            "swap_hint": swap_hint,
            "markup_download": url_for("reconciler.download_file", name=markup_name),
            "log_path": log_paths.get("md", ""),
            "crm_note": _crm_note(recon),
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
                "approved_added": len(recon.approved_added),
                "approved_revised": len(recon.approved_revised),
                "won_tagged": stats.get("won_tagged", 0),
            }
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cleanup_file(carrier_path)
        cleanup_file(contractor_path)
        cleanup_file(og_path)


@bp.route("/preview/<name>")
def preview_file(name):
    """Serve a markup PDF inline (no Content-Disposition: attachment) so the
    browser can render it in an iframe preview."""
    safe = secure_filename(name)
    print(f"[reconciler] preview: requested={name}, safe={safe}")
    if not safe or not safe.lower().endswith(".pdf"):
        return "File not found", 404
    filepath = os.path.join(_upload_dir(), safe)
    exists = os.path.exists(filepath)
    print(f"[reconciler] preview: filepath={filepath}, exists={exists}")
    if exists:
        return send_file(filepath, mimetype="application/pdf")
    return "File not found", 404


@bp.route("/download/<name>")
def download_file(name):
    """Serve a generated file from the upload dir. The marked-up carrier PDF is
    kept after serving so it can also be posted to the CRM (the stale sweep in
    run() bounds how long it lingers); any other served file is removed once."""
    safe = secure_filename(name)
    if not safe or not safe.lower().endswith((".pdf", ".md", ".csv")):
        return "File not found", 404
    filepath = os.path.join(_upload_dir(), safe)
    if os.path.exists(filepath):
        response = send_file(filepath, as_attachment=True)
        if not safe.lower().endswith(".pdf"):
            cleanup_file(filepath)
        return response
    return "File not found", 404
