"""Ice and Water Shield calculator: a static, client-side tool. The Python side
serves the page and a PDF export endpoint; all math runs in static/js/calculator.js.
Edit the coverage math there, not here."""
import base64
import io
import os
import shutil
import tempfile
import time
from pathlib import Path

import fitz
from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from ...config import Config
from ...core import crm_search
from ...core import crm as crm_core
from . import pdf_extractor

bp = Blueprint(
    "iws",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="static",
)


def _upload_dir():
    d = Path(Config.UPLOAD_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _sweep_stale(max_age=1800):
    try:
        now = time.time()
        for p in Path(_upload_dir()).glob("iws_*.pdf"):
            try:
                if now - p.stat().st_mtime > max_age:
                    p.unlink()
            except OSError:
                pass
    except Exception:
        pass


@bp.route("/")
def index():
    return render_template("iws.html")


@bp.route("/crm-search", methods=["POST"])
def crm_search_route():
    query = (request.get_json(silent=True) or {}).get("query", "").strip()
    if not query:
        return jsonify({"ok": False, "error": "Empty query"}), 400
    try:
        deals = crm_search.search_deals(query)
        return jsonify({"ok": True, "deals": deals})
    except crm_search.CrmError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"CRM search failed: {e}"})


@bp.route("/crm-files", methods=["POST"])
def crm_files_route():
    deal_id = str((request.get_json(silent=True) or {}).get("deal_id", "")).strip()
    if not deal_id.isdigit():
        return jsonify({"ok": False, "error": "Missing deal_id"}), 400
    try:
        result = crm_search.deal_files(deal_id)
        return jsonify({"ok": True, **result, "deal_id": deal_id})
    except crm_search.CrmError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not list the deal's files: {e}"})


@bp.route("/crm-fetch", methods=["POST"])
def crm_fetch_route():
    deal_id = str((request.get_json(silent=True) or {}).get("deal_id", "")).strip()
    if not deal_id:
        return jsonify({"ok": False, "error": "Missing deal_id"}), 400
    base_url = crm_search.CRM_BASE_URL.rstrip("/")
    crm_url = f"{base_url}/Products/CRM/Deals.aspx?id={deal_id}"
    return jsonify(crm_core.fetch_job_info(crm_url))


@bp.route("/extract-measurements", methods=["POST"])
def extract_measurements():
    file_id = (request.get_json(silent=True) or {}).get("file_id")
    if not file_id:
        return jsonify({"ok": False, "error": "Missing file_id"}), 400
    
    try:
        temp_dir = tempfile.mkdtemp()
        pdf_path = os.path.join(temp_dir, "measurement.pdf")
        
        try:
            crm_search.download_file(file_id, pdf_path)
            measurements = pdf_extractor.extract_measurements_from_pdf(pdf_path)
            return jsonify({"ok": True, **measurements})
        finally:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
    except pdf_extractor.ExtractionError as e:
        return jsonify({"ok": False, "error": f"Extraction failed: {str(e)}"}), 400
    except crm_search.CrmError as e:
        return jsonify({"ok": False, "error": f"Failed to download file: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error: {str(e)}"}), 500


@bp.route("/extract-upload", methods=["POST"])
def extract_upload():
    """Extract measurements from a PDF uploaded from the user's computer."""
    f = request.files.get("pdf")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "No PDF file uploaded"}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"ok": False, "error": "Please upload a PDF file"}), 400

    temp_dir = tempfile.mkdtemp()
    pdf_path = os.path.join(temp_dir, "upload.pdf")
    try:
        f.save(pdf_path)
        measurements = pdf_extractor.extract_measurements_from_pdf(pdf_path)
        return jsonify({"ok": True, **measurements})
    except pdf_extractor.ExtractionError as e:
        return jsonify({"ok": False, "error": f"Extraction failed: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error: {str(e)}"}), 500
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


@bp.route("/pdf", methods=["POST"])
def export_pdf():
    """Generate a one-page PDF summary and save it for download."""
    _sweep_stale()
    data = request.get_json(silent=True) or {}
    print(f"[iws] pdf export: project={data.get('projectName')}, "
          f"actual={data.get('actualTotal')}, full_roll={data.get('fullRollTotal')}")
    project_name = (data.get("projectName") or "Untitled Project").strip()
    project_address = (data.get("projectAddress") or "").strip()
    actual_total = data.get("actualTotal", 0)
    full_roll_total = data.get("fullRollTotal", 0)
    coverage = data.get("coverage", 0)
    eave_length = data.get("eaveLength", 0)
    valley_length = data.get("valleyLength", 0)
    roof_size = data.get("roofSizeSq", 0)
    roof_pitch = data.get("roofPitch", 0)
    felt_reduction = data.get("feltReduction", 0)
    felt_sq = data.get("feltSq", 0)
    calc_mode = data.get("calcMode", "eaveValley")
    wall_thickness = data.get("wallThickness", 0)
    inside_wall = data.get("insideWall", 0)
    soffit_depth = data.get("soffitDepth", 0)
    calc_choice = data.get("calcChoice", "actual")
    diagram_image = data.get("diagramImage") or ""

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # US Letter
    margin = 54
    y = margin

    # Title
    page.insert_text((margin, y), "Ice and Water Shield Calculation",
                     fontname="helv", fontsize=16, color=(0.1, 0.15, 0.1))
    y += 24
    page.draw_line((margin, y), (612 - margin, y),
                   color=(0.6, 0.65, 0.55), width=1)
    y += 20

    # Project info
    page.insert_text((margin, y), f"Project: {project_name}",
                     fontname="helv", fontsize=11, color=(0.1, 0.15, 0.1))
    y += 16
    if project_address:
        page.insert_text((margin, y), f"Address: {project_address}",
                         fontname="helv", fontsize=10, color=(0.35, 0.4, 0.33))
        y += 16
    y += 8

    # Inputs section
    page.insert_text((margin, y), "Inputs",
                     fontname="helv", fontsize=12, color=(0.1, 0.15, 0.1))
    y += 18
    inputs = [
        f"Roof Size: {roof_size} SQ",
        f"Predominant Pitch: {roof_pitch}/12",
        f"Eave Length: {eave_length} LF",
        f"Valley Length: {valley_length} LF" if calc_mode != "eaveOnly" else None,
        f"Inside Exterior Wall: {inside_wall}\"",
        f"Soffit Depth: {soffit_depth}\"",
        f"Wall Thickness: {wall_thickness}\"",
        f"Mode: {'Eave + Valley' if calc_mode == 'eaveValley' else 'Eave Only'}",
    ]
    for line in inputs:
        if line is None:
            continue
        page.insert_text((margin + 12, y), line,
                         fontname="helv", fontsize=10, color=(0.3, 0.35, 0.28))
        y += 15
    y += 10

    # Results section
    page.draw_line((margin, y), (612 - margin, y),
                   color=(0.6, 0.65, 0.55), width=0.5)
    y += 16
    page.insert_text((margin, y), "Results",
                     fontname="helv", fontsize=12, color=(0.1, 0.15, 0.1))
    y += 20

    # Selected coverage result
    col2 = 320
    if calc_choice == "fullRoll":
        chosen_label, chosen_total = "Full Roll Coverage:", full_roll_total
    else:
        chosen_label, chosen_total = "Actual Coverage:", actual_total
    page.insert_text((margin, y), chosen_label,
                     fontname="helv", fontsize=10, color=(0.35, 0.4, 0.33))
    page.insert_text((margin + 120, y), f"{chosen_total} SF",
                     fontname="helv", fontsize=11, color=(0.1, 0.15, 0.1))
    page.insert_text((col2, y), "IWS Coverage Width:",
                     fontname="helv", fontsize=10, color=(0.35, 0.4, 0.33))
    page.insert_text((col2 + 128, y), f"{coverage}\"",
                     fontname="helv", fontsize=11, color=(0.1, 0.15, 0.1))
    y += 18
    page.insert_text((margin, y), "Felt Reduction:",
                     fontname="helv", fontsize=10, color=(0.35, 0.4, 0.33))
    page.insert_text((margin + 110, y), f"{felt_reduction} SF ({felt_sq} SQ)",
                     fontname="helv", fontsize=11, color=(0.1, 0.15, 0.1))
    y += 28

    # Math breakdown
    page.draw_line((margin, y), (612 - margin, y),
                   color=(0.6, 0.65, 0.55), width=0.5)
    y += 16
    page.insert_text((margin, y), "Calculation",
                     fontname="helv", fontsize=12, color=(0.1, 0.15, 0.1))
    y += 18
    math_text = (
        f"Using the predominant soffit depth of {soffit_depth}\", "
        f"wall thickness of {wall_thickness}\", and a {roof_pitch}/12 roof pitch, "
        f"the ice barrier must extend onto the roof's surface at least "
        f"{coverage}\" from the lowest edge to a point not less than "
        f"{inside_wall}\" inside the exterior wall line."
    )
    # Word-wrap the math text
    words = math_text.split()
    line = ""
    for word in words:
        test = (line + " " + word).strip()
        if fitz.get_text_length(test, fontname="helv", fontsize=9) > (612 - 2 * margin):
            page.insert_text((margin + 12, y), line,
                             fontname="helv", fontsize=9, color=(0.3, 0.35, 0.28))
            y += 13
            line = word
        else:
            line = test
    if line:
        page.insert_text((margin + 12, y), line,
                         fontname="helv", fontsize=9, color=(0.3, 0.35, 0.28))
        y += 20

    # Diagram, right underneath the calculation text
    if diagram_image.startswith("data:image"):
        try:
            img_bytes = base64.b64decode(diagram_image.split(",", 1)[1])
            pix = fitz.Pixmap(img_bytes)
            avail_w = 612 - 2 * margin
            avail_h = 792 - margin - y - 8
            scale = min(avail_w / pix.width, avail_h / pix.height, 1.0)
            img_w = pix.width * scale
            img_h = pix.height * scale
            x0 = margin + (avail_w - img_w) / 2
            rect = fitz.Rect(x0, y + 8, x0 + img_w, y + 8 + img_h)
            page.insert_image(rect, stream=img_bytes)
        except Exception as e:
            print(f"[iws] could not embed diagram in pdf: {e}")

    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)

    safe_name = project_name.replace(" ", "_").replace("/", "-")[:40]
    filename = f"IWS_{safe_name}.pdf" if safe_name else "IWS_Calculation.pdf"
    safe_filename = filename.replace(" ", "_")

    # Save to UPLOAD_DIR so pywebview can serve it via the native Save As dialog.
    dest = os.path.join(_upload_dir(), safe_filename)
    with open(dest, "wb") as f:
        f.write(buf.read())

    return jsonify({
        "ok": True,
        "filename": safe_filename,
        "download": url_for("iws.download_file", name=safe_filename),
    })


@bp.route("/download/<name>")
def download_file(name):
    """Serve a generated PDF. In the desktop shell the client calls
    pywebview.api.save_file(name) which reads this from disk; in a browser
    the client falls back to window.location.href here."""
    from werkzeug.utils import secure_filename as safe
    s = safe(name)
    if not s or not s.lower().endswith(".pdf"):
        return "File not found", 404
    filepath = os.path.join(_upload_dir(), s)
    if os.path.exists(filepath):
        return send_file(filepath, mimetype="application/pdf", as_attachment=True)
    return "File not found", 404
