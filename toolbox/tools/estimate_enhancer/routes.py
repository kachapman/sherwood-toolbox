"""HTTP layer for Estimate Enhancer. Holds the blueprint, wires filesystem
paths from toolbox config, and calls the pure logic in pdf_ops. Edit routes
here; edit analysis behavior in pdf_ops.py.

Coupling fixes vs the original standalone app:
  - uploads dir comes from Config.UPLOAD_DIR (was cwd-relative 'uploads')
  - attachments are the packaged IRC PDFs beside this file (read-only data)
  - the image-link href and the page URLs use url_for, so the tool works under
    the /estimate-enhancer blueprint prefix
  - the fork is found via Config.FORK_PATH and run with sys.executable
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
from flask import (Blueprint, jsonify, render_template, request, send_file, url_for)
from pypdf import PdfReader, PdfWriter
from werkzeug.utils import secure_filename

from ...config import Config
from ...core import crm_search
from . import pdf_ops
from .pdf_ops import CODE_REF_HL_HEX
from .utils.markup_bridge import add_image_links

bp = Blueprint(
    "estimate_enhancer",
    __name__,
    template_folder="templates",
    static_folder="static",
)

ATTACHMENTS_DIR = Path(__file__).resolve().parent / "attachments"


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


def get_document_options():
    """List the packaged IRC attachment PDFs as selectable documents."""
    docs = []
    if ATTACHMENTS_DIR.exists():
        for f in sorted(os.listdir(ATTACHMENTS_DIR)):
            if f.lower().endswith('.pdf'):
                doc_id = f[:-4]
                docs.append({
                    'id': doc_id,
                    'name': doc_id.replace('_', ' ').replace('-', ' ').title(),
                    'file': str(ATTACHMENTS_DIR / f),
                    'code': pdf_ops.parse_attachment_code(doc_id),
                })
    return docs


def build_image_link_payload(filename, links_to_add):
    """Return (label->url map, payload). URLs use url_for so they carry the
    /estimate-enhancer prefix."""
    processed_filename = f'processed_{filename}'
    seen = set()
    link_map = {}
    payload = []
    for link in links_to_add:
        image_name = str(link.get('image_name', '')).strip()
        if not image_name:
            continue
        to_page = link.get('to_page')
        from_page = link.get('from_page')
        if to_page is None:
            continue
        href = url_for('estimate_enhancer.serve_upload', filename=processed_filename) \
            + f"#page={int(to_page) + 1}"
        payload.append({
            'from_page': int(from_page) if from_page is not None else None,
            'to_page': int(to_page), 'image_name': image_name, 'href': href,
        })
        if image_name not in seen:
            link_map[image_name] = href
            seen.add(image_name)
    return link_map, payload


def process_with_fork(input_pdf, output_pdf, fork_highlight_rules=None):
    """Run the bundled add_image_links fork as a subprocess."""
    fork_env = os.environ.copy()
    fork_env['PDF_HIGHLIGHT_RULES_JSON'] = json.dumps(fork_highlight_rules or [])
    fork_path = str(Config.FORK_PATH)
    if not os.path.exists(fork_path):
        print(f"Fork helper missing at {fork_path}")
        return False
    result = subprocess.run([sys.executable, fork_path, input_pdf],
                            capture_output=True, text=True, timeout=120, env=fork_env)
    if result.returncode != 0:
        print(f"Fork error: {result.stderr}")
        return False
    print(result.stdout)
    linked_path = input_pdf.replace('.pdf', '_linked.pdf')
    if os.path.exists(linked_path):
        if os.path.exists(output_pdf):
            os.remove(output_pdf)
        os.rename(linked_path, output_pdf)
        return True
    return False


# === SECTION: routes ===
@bp.route('/')
def index():
    return render_template('estimate_enhancer.html', documents=get_document_options())


@bp.route('/crm-search', methods=['POST'])
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


@bp.route('/crm-files', methods=['POST'])
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



@bp.route('/test', methods=['GET', 'POST'])
def test():
    return jsonify({'test': 'ok'})


@bp.route('/progress/<filename>')
def progress(filename):
    """Poll whether the fork subprocess has finished. Returns {status: 'running'|'done'|'error'}."""
    safe = secure_filename(filename or '')
    if not safe:
        return jsonify({'status': 'error', 'message': 'Invalid filename'})
    upload = _upload_dir()
    output_pdf = os.path.join(upload, safe + '.output.pdf')
    linked_pdf = os.path.join(upload, safe.replace('.pdf', '') + '_linked.pdf')
    original = os.path.join(upload, safe)
    output_exists = os.path.exists(output_pdf)
    linked_exists = os.path.exists(linked_pdf)
    original_exists = os.path.exists(original)
    print(f"[ee] progress: file={safe}, output={output_exists}, "
          f"linked={linked_exists}, original={original_exists}")
    # The fork writes _linked.pdf; once it exists, processing is done.
    if os.path.exists(output_pdf):
        return jsonify({'status': 'done'})
    if os.path.exists(linked_pdf):
        return jsonify({'status': 'done'})
    # Check if the original upload still exists (if deleted, something went wrong)
    original = os.path.join(upload, safe)
    if not os.path.exists(original):
        return jsonify({'status': 'error', 'message': 'Upload file not found'})
    return jsonify({'status': 'running'})


@bp.route('/analyze', methods=['POST'])
def analyze():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        file = request.files['file']
        filename = secure_filename(file.filename or 'unknown.pdf')
        filepath = os.path.join(_upload_dir(), filename)
        file.save(filepath)

        reader = PdfReader(filepath)
        errors_found = []
        estimate_end_page = pdf_ops.detect_estimate_end(reader)

        estimate_texts = []
        for i in range(estimate_end_page):
            text = reader.pages[i].extract_text() or ''
            estimate_texts.append(text)
            errors_found.extend(pdf_ops.check_qty_and_spelling_errors(text, i + 1))

        errors_found.extend(pdf_ops.check_duplicate_photo_names(reader, estimate_end_page))
        errors_found.sort(key=lambda x: x.get('page', 0))

        code_refs = pdf_ops.extract_code_reference_terms("\n".join(estimate_texts))
        auto_selected_docs = pdf_ops.match_attachments_to_references(code_refs, get_document_options())

        return jsonify({
            'filename': filename,
            'has_errors': len(errors_found) > 0,
            'errors': errors_found[:100],
            'total_pages': len(reader.pages),
            'code_references': code_refs,
            'auto_selected_docs': auto_selected_docs,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/process', methods=['POST'])
def process():
    filename = request.form.get('filename')
    filepath = os.path.join(_upload_dir(), filename or '')
    if not filename or not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 400

    reader = PdfReader(filepath)
    page_data = []
    errors_found = []
    image_references = []
    photo_pages = []
    estimate_end_page = pdf_ops.detect_estimate_end(reader)

    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ''
        if i < estimate_end_page:
            errors_found.extend(pdf_ops.check_zero_qty(text, i + 1))
        image_references.extend(pdf_ops.find_image_references(text, i + 1))
        if i >= estimate_end_page:
            photo_name = pdf_ops.extract_photo_name(text)
            if photo_name:
                photo_pages.append({'name': photo_name, 'page': i + 1})
        page_data.append({'page_num': i + 1, 'text': text, 'errors': []})

    photo_map = {p['name'].lower(): p['page'] for p in photo_pages}
    links_to_add = []
    for ref in image_references:
        img_name = ref['image_name'].lower().strip()
        img_name_norm = pdf_ops.normalize_for_match(img_name)
        best_match = None
        best_score = 0
        for photo_name, photo_page in photo_map.items():
            pn = photo_name.lower()
            pn_norm = pdf_ops.normalize_for_match(photo_name)
            if img_name == pn or img_name_norm == pn_norm:
                best_match = photo_page
                break
            if img_name in pn or pn in img_name:
                score = len(min(img_name, pn, key=len)) / len(max(img_name, pn, key=len))
                if score > best_score:
                    best_score = score
                    best_match = photo_page
            if len(img_name) > 15 and len(pn) > 15:
                sim = pdf_ops.similarity_ratio(img_name_norm, pn_norm)
                if sim > best_score and sim > 0.7:
                    best_score = sim
                    best_match = photo_page
        if best_match:
            links_to_add.append({
                'from_page': ref['from_page'] - 1, 'to_page': best_match - 1,
                'image_name': ref['image_name'],
            })

    image_link_map, image_links = build_image_link_payload(filename, links_to_add)

    auto_code_terms = []
    if request.form.get('highlight_code_refs'):
        full_text = "\n".join(pd['text'] for pd in page_data)
        auto_code_terms = pdf_ops.extract_code_reference_terms(full_text)

    highlight_configs = pdf_ops.extract_highlight_configs(
        request.form, auto_terms=auto_code_terms, auto_color=CODE_REF_HL_HEX)

    highlighted_pages = []
    for pd in page_data:
        pd['errors'] = [e for e in errors_found if e['page'] == pd['page_num']]
        pd['text'] = add_image_links(pd['text'], image_link_map)
        if highlight_configs:
            pd['text'] = pdf_ops.highlight_terms(pd['text'], highlight_configs)
        highlighted_pages.append(pd)

    selected_docs = []
    for doc in get_document_options():
        if request.form.get(f'doc_{doc["id"]}') and os.path.exists(doc['file']):
            selected_docs.append(doc['file'])

    temp_pdf = filepath + '.temp.pdf'
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    with open(temp_pdf, 'wb') as f:
        writer.write(f)

    output_pdf = filepath + '.output.pdf'
    fork_rules = pdf_ops.build_fork_highlight_rules(highlight_configs)
    if not process_with_fork(filepath, output_pdf, fork_rules):
        return jsonify({'error': 'Failed to generate linked PDF output'}), 500
    if not os.path.exists(output_pdf):
        return jsonify({'error': 'Linked PDF output file not found'}), 500

    highlight_warning = None
    if fork_rules and pdf_ops.count_pdf_highlight_annotations(output_pdf) == 0:
        highlight_warning = ('No occurrences of the highlight terms were found in the '
                             'document, so nothing was highlighted.')

    pdf_ops.flatten_pdf_highlights(output_pdf, fill_opacity=0.75)
    cleanup_file(temp_pdf)

    output_file = os.path.join(_upload_dir(), 'processed_' + filename)
    final_doc = fitz.open(output_pdf)
    for doc_file in selected_docs:
        if os.path.exists(doc_file):
            attachment_doc = fitz.open(doc_file)
            final_doc.insert_pdf(attachment_doc)
            attachment_doc.close()

    added_user_pdfs = 0
    for user_file in request.files.getlist('user_pdf'):
        if user_file and pdf_ops.allowed_file(user_file.filename):
            temp_path = os.path.join(_upload_dir(), secure_filename(user_file.filename))
            user_file.save(temp_path)
            if os.path.exists(temp_path):
                user_doc = fitz.open(temp_path)
                final_doc.insert_pdf(user_doc)
                user_doc.close()
                os.remove(temp_path)
                added_user_pdfs += 1

    final_doc.save(output_file, garbage=4, deflate=True, clean=True)
    final_doc.close()

    cleanup_file(filepath)
    cleanup_file(output_pdf)

    return jsonify({
        'filename': filename,
        'total_pages': len(reader.pages),
        'errors': errors_found,
        'attachments_added': len(selected_docs) + added_user_pdfs,
        'highlighted_pages': highlighted_pages,
        'image_links': image_links,
        'highlight_warning': highlight_warning,
    })


@bp.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join(_upload_dir(), 'processed_' + filename)
    if os.path.exists(filepath):
        response = send_file(filepath, as_attachment=True)
        cleanup_file(filepath)
        return response
    return "File not found", 404


@bp.route('/uploads/<filename>')
def serve_upload(filename):
    filepath = os.path.join(_upload_dir(), filename)
    if os.path.exists(filepath):
        return send_file(filepath)
    return "File not found", 404
