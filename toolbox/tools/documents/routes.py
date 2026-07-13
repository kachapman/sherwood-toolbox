"""HTTP layer for the Documents tool. Collects invoice/certificate inputs and
runs the headless restoration_common generators. The PDF layouts live in
restoration_common (InvoicePDFGenerator, COCPDFGenerator); this file maps the
web form to their inputs and saves the result for download.

doc_type selects which document to produce ("invoice", "coc", or "both").
"""
import io
import json
import os
import shutil
import tempfile
import time
import zipfile
from datetime import date
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from restoration_common import (InvoicePDFGenerator, COCPDFGenerator,
                                 get_company_by_id, load_companies, find_logo,
                                 get_signature_path)

from ...config import Config
from ...core.crm import fetch_job_info
from ...core import crm_search

bp = Blueprint("documents", __name__, template_folder="templates")

ITEL_AMOUNT = 199.80
NTS_AMOUNT = 150.00


def _upload_dir():
    d = Path(Config.UPLOAD_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _cleanup_file(filepath):
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError:
            pass


def _sweep_stale(max_age=1800):
    try:
        now = time.time()
        for p in Path(_upload_dir()).glob("docs_*.pdf"):
            try:
                if now - p.stat().st_mtime > max_age:
                    p.unlink()
            except OSError:
                pass
        for p in Path(_upload_dir()).glob("docs_*.zip"):
            try:
                if now - p.stat().st_mtime > max_age:
                    p.unlink()
            except OSError:
                pass
    except Exception:
        pass


@bp.route("/")
def index():
    return render_template("documents.html", companies=load_companies())


@bp.route("/crm-fetch", methods=["POST"])
def crm_fetch():
    return jsonify(fetch_job_info(request.form.get("url", "")))


@bp.route("/crm-search", methods=["POST"])
def crm_search_route():
    query = (request.form.get("query") or "").strip()
    if len(query) < 2:
        return jsonify({"ok": False, "error": "Type at least two characters."})
    try:
        return jsonify({"ok": True, "deals": crm_search.search_deals(query)})
    except crm_search.CrmError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"CRM search failed: {e}"})


@bp.route("/crm-files", methods=["POST"])
def crm_files_route():
    deal_id = (request.form.get("deal_id") or "").strip()
    if not deal_id.isdigit():
        return jsonify({"ok": False, "error": "Pick a deal first."})
    try:
        result = crm_search.deal_files(deal_id)
        return jsonify({"ok": True, **result})
    except crm_search.CrmError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not list the deal's files: {e}"})



def _money(value):
    try:
        return float(str(value).replace(",", "").replace("$", "").strip() or 0)
    except ValueError:
        return 0.0


def _build_job_info(form):
    job_number = form.get("job_number", "").strip()
    return {
        "customer_name": form.get("customer_name", "").strip(),
        "street": form.get("street", "").strip(),
        "city_state_zip": form.get("city_state_zip", "").strip(),
        "job_number": job_number,
        "insurance_claim": form.get("insurance_claim", "").strip(),
        "sales_rep": form.get("sales_rep", "").strip(),
        "note": form.get("insurance_claim", "").strip(),
        "invoice_number": form.get("invoice_number", "").strip() or job_number,
        "invoice_date": form.get("invoice_date", "").strip() or date.today().strftime("%m/%d/%Y"),
        "terms": form.get("terms", "").strip() or "Due on receipt",
        "invoice_notes": form.get("invoice_notes", "").strip(),
        "base_charge": {
            "description": form.get("base_description", "").strip() or "Base Charge",
            "amount": _money(form.get("base_amount")),
        },
    }


def _build_line_items(form):
    items = []
    if form.get("include_itel"):
        items.append(("ITEL Report", ITEL_AMOUNT))
    if form.get("include_nts"):
        items.append(("NTS Report", NTS_AMOUNT))
    try:
        for row in json.loads(form.get("line_items_json", "[]") or "[]"):
            desc = str(row.get("description", "")).strip()
            amount = _money(row.get("amount"))
            if desc or amount:
                items.append((desc, amount))
    except (ValueError, AttributeError):
        pass
    return items


def _make_invoice(out_path, company, job_info, line_items, logo_path, sig_path, sig_name):
    InvoicePDFGenerator(out_path, company, job_info, line_items, logo_path=logo_path,
                        signature_path=sig_path, signature_name=sig_name).generate()
    return f"Invoice_{job_info['customer_name']}_{job_info['invoice_number']}.pdf"


def _make_coc(out_path, company, job_info, logo_path, sig_path, sig_name):
    COCPDFGenerator(out_path, company, job_info, logo_path=logo_path,
                    signature_path=sig_path, signature_name=sig_name).generate()
    return f"Certificate_of_Completion_{job_info['customer_name']}.pdf"


@bp.route("/generate", methods=["POST"])
def generate():
    _sweep_stale()
    form = request.form
    doc_type = form.get("doc_type", "invoice")
    company = get_company_by_id(form.get("company_id", "")) or {}
    if not company:
        return jsonify({"error": "Select a company."}), 400

    job_info = _build_job_info(form)
    if not job_info["customer_name"] or not job_info["job_number"]:
        return jsonify({"error": "Customer name and job number are required."}), 400

    temp_dir = tempfile.mkdtemp(prefix="toolbox_docs_")
    try:
        logo_path = find_logo(temp_dir, company)

        sig_path = None
        sig_name = form.get("signature_name", "").strip() or job_info["sales_rep"]
        if form.get("include_signature"):
            custom = request.files.get("signature_file")
            if form.get("use_custom_signature") and custom and custom.filename:
                sig_path = os.path.join(temp_dir, secure_filename(custom.filename))
                custom.save(sig_path)
            else:
                sig_path = get_signature_path(form.get("company_id", ""))

        line_items = _build_line_items(form)

        if doc_type == "both":
            inv_path = os.path.join(temp_dir, "invoice.pdf")
            coc_path = os.path.join(temp_dir, "certificate.pdf")
            inv_name = _make_invoice(inv_path, company, job_info, line_items,
                                     logo_path, sig_path, sig_name)
            coc_name = _make_coc(coc_path, company, job_info, logo_path, sig_path, sig_name)
            if not (os.path.exists(inv_path) and os.path.exists(coc_path)):
                return jsonify({"error": "Could not generate the documents."}), 500
            # Save ZIP to UPLOAD_DIR
            zip_name = f"Documents_{job_info['customer_name']}_{job_info['job_number']}.zip"
            safe_zip = secure_filename(zip_name)
            zip_dest = os.path.join(_upload_dir(), safe_zip)
            with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(inv_path, inv_name)
                zf.write(coc_path, coc_name)
            return jsonify({
                "ok": True,
                "filename": safe_zip,
                "download": url_for("documents.download_file", name=safe_zip),
            })

        out_path = os.path.join(temp_dir, "document.pdf")
        if doc_type == "coc":
            download_name = _make_coc(out_path, company, job_info, logo_path, sig_path, sig_name)
        else:
            download_name = _make_invoice(out_path, company, job_info, line_items,
                                          logo_path, sig_path, sig_name)

        if not os.path.exists(out_path):
            return jsonify({"error": "Could not generate the document."}), 500

        safe_name = secure_filename(download_name)
        dest = os.path.join(_upload_dir(), safe_name)
        shutil.copy2(out_path, dest)

        return jsonify({
            "ok": True,
            "filename": safe_name,
            "download": url_for("documents.download_file", name=safe_name),
        })
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@bp.route("/download/<name>")
def download_file(name):
    safe = secure_filename(name)
    if not safe:
        return "File not found", 404
    if not safe.lower().endswith((".pdf", ".zip")):
        return "File not found", 404
    filepath = os.path.join(_upload_dir(), safe)
    if os.path.exists(filepath):
        mime = "application/zip" if safe.lower().endswith(".zip") else "application/pdf"
        return send_file(filepath, mimetype=mime, as_attachment=True)
    return "File not found", 404
