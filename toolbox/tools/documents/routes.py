"""HTTP layer for the Documents tool. Collects invoice/certificate inputs and
runs the headless restoration_common generators. The PDF layouts live in
restoration_common (InvoicePDFGenerator, COCPDFGenerator); this file maps the
web form to their inputs and streams the result back.

doc_type selects which document to produce ("invoice" or "coc").
"""
import io
import json
import os
import shutil
import tempfile
import zipfile
from datetime import date

from flask import Blueprint, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from restoration_common import (InvoicePDFGenerator, COCPDFGenerator,
                                 get_company_by_id, load_companies, find_logo,
                                 get_signature_path)

from ...core.crm import fetch_job_info

bp = Blueprint("documents", __name__, template_folder="templates")

ITEL_AMOUNT = 199.80
NTS_AMOUNT = 150.00


@bp.route("/")
def index():
    return render_template("documents.html", companies=load_companies())


@bp.route("/crm-fetch", methods=["POST"])
def crm_fetch():
    return jsonify(fetch_job_info(request.form.get("url", "")))


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
    """Line items are additions on top of the base charge (which the invoice
    generator draws separately). ITEL/NTS toggles plus any custom rows."""
    items = []
    if form.get("include_itel"):
        items.append(("ITEL Report", ITEL_AMOUNT))
    if form.get("include_nts"):
        items.append(("NTS Report", NTS_AMOUNT))
    # Custom rows arrive as a JSON array of {description, amount}.
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

        # Signature: custom upload wins, else the company's saved signature.
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
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(inv_path, inv_name)
                zf.write(coc_path, coc_name)
            buf.seek(0)
            zip_name = f"Documents_{job_info['customer_name']}_{job_info['job_number']}.zip"
            return send_file(buf, mimetype="application/zip",
                             as_attachment=True, download_name=zip_name)

        out_path = os.path.join(temp_dir, "document.pdf")
        if doc_type == "coc":
            download_name = _make_coc(out_path, company, job_info, logo_path, sig_path, sig_name)
        else:
            download_name = _make_invoice(out_path, company, job_info, line_items,
                                          logo_path, sig_path, sig_name)

        if not os.path.exists(out_path):
            return jsonify({"error": "Could not generate the document."}), 500
        with open(out_path, "rb") as fh:
            data = io.BytesIO(fh.read())
        return send_file(data, mimetype="application/pdf",
                         as_attachment=True, download_name=download_name)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
