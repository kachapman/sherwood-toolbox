"""HTTP layer for Estimate Enhancer. Holds the blueprint, wires filesystem
paths from toolbox config, and calls the pure logic in pdf_ops. Edit routes
here; edit analysis behavior in pdf_ops.py.

Coupling fixes vs the original standalone app:
  - uploads dir comes from Config.UPLOAD_DIR (was cwd-relative 'uploads')
  - attachments are the packaged IRC PDFs beside this file (read-only data)
  - the image-link href and the page URLs use the /estimate-enhancer blueprint prefix
  - the fork is found via Config.FORK_PATH and run with sys.executable
  - hrefs for image links are built with a pure helper (no Flask context required)
 """
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import fitz
from flask import (Blueprint, jsonify, render_template, request, send_file)
from pypdf import PdfReader, PdfWriter
from werkzeug.utils import secure_filename

from ...config import Config
from ...core.hub import _load_web_limits
from ...registry import TOOLS
from . import pdf_ops
from .pdf_ops import CODE_REF_HL_HEX
from .utils.markup_bridge import add_image_links

bp = Blueprint(
    "estimate_enhancer",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="static",
)

ATTACHMENTS_DIR = Path(__file__).resolve().parent / "attachments"

# Pure prefix + href builder (no Flask context required). Matches the registry mount.
_EE_PREFIX = next((t.url_prefix for t in TOOLS if t.id == "estimate_enhancer"), "/estimate-enhancer")

def _build_processed_href(filename: str, to_page: int) -> str:
    """Pure relative href used inside and outside request context."""
    return f"{_EE_PREFIX}/uploads/processed_{filename}#page={int(to_page) + 1}"


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
    """Return (label->url map, payload) using pure relative hrefs.
    No Flask context is required; hrefs are deterministic."""
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
        href = _build_processed_href(filename, int(to_page))
        payload.append({
            'from_page': int(from_page) if from_page is not None else None,
            'to_page': int(to_page), 'image_name': image_name, 'href': href,
        })
        if image_name not in seen:
            link_map[image_name] = href
            seen.add(image_name)
    return link_map, payload


def process_with_fork(input_pdf, output_pdf, fork_highlight_rules=None):
    """Run the bundled add_image_links fork as a subprocess. Returns (ok, stdout, stderr)."""
    fork_env = os.environ.copy()
    fork_env['PDF_HIGHLIGHT_RULES_JSON'] = json.dumps(fork_highlight_rules or [])
    fork_path = str(Config.FORK_PATH)
    if not os.path.exists(fork_path):
        print(f"Fork helper missing at {fork_path}")
        return False, '', 'Fork helper missing'
    timeout = getattr(Config, 'ENHANCER_FORK_TIMEOUT', 180)
    result = subprocess.run([sys.executable, fork_path, input_pdf],
                            capture_output=True, text=True, timeout=timeout, env=fork_env)
    if result.returncode != 0:
        return False, (result.stdout or ''), (result.stderr or '')
    linked_path = input_pdf.replace('.pdf', '_linked.pdf')
    if os.path.exists(linked_path):
        if os.path.exists(output_pdf):
            os.remove(output_pdf)
        os.rename(linked_path, output_pdf)
        return True, (result.stdout or ''), (result.stderr or '')
    return False, (result.stdout or ''), 'Linked output not produced'


# === SECTION: background job helpers (web-friendly long jobs) ===
def _job_paths(filename):
    base = os.path.join(_upload_dir(), filename)
    return {
        'spec': base + '.job.json',
        'stage': base + '.stage.txt',
        'log': base + '.log.txt',
        'result': base + '.result.json',
        'error': base + '.error.json',
    }


def _write_stage(paths, text):
    try:
        with open(paths['stage'], 'w') as f:
            f.write(text or '')
    except Exception:
        pass


def _append_log(paths, line):
    try:
        with open(paths['log'], 'a') as f:
            f.write((line or '').rstrip() + '\n')
    except Exception:
        pass


def _write_json(path, obj):
    try:
        with open(path, 'w') as f:
            json.dump(obj, f)
    except Exception:
        pass


def _read_text(path, default=''):
    try:
        if os.path.exists(path):
            return open(path, 'r').read()
    except Exception:
        pass
    return default


def _psutil_rss(paths, label, photo_pages=None):
    try:
        import psutil
        rss = psutil.Process().memory_info().rss / (1024 * 1024)
        extra = f' photo_pages={photo_pages}' if photo_pages is not None else ''
        _append_log(paths, f"[enhancer] RSS {rss:.1f} MB{extra}  {label}")
    except Exception:
        pass


def _cleanup_sidecars(filename):
    paths = _job_paths(filename)
    for k in ('spec', 'stage', 'log', 'result', 'error'):
        cleanup_file(paths[k])
    for suffix in ('.temp.pdf', '.output.pdf'):
        cleanup_file(os.path.join(_upload_dir(), filename + suffix))


def _run_enhance(filename):
    """Background worker: heavy lifting moved out of request thread.
    No Flask context is needed; URLs are built with a pure helper.
    """
    paths = _job_paths(filename)
    spec_path = paths['spec']

    try:
        if not os.path.exists(spec_path):
            _write_json(paths['error'], {'error': 'Job spec not found'})
            return
        spec = json.loads(open(spec_path, 'r').read())
        filepath = os.path.join(_upload_dir(), filename)
        if not os.path.exists(filepath):
            _write_json(paths['error'], {'error': 'Source file missing'})
            return

        reader = PdfReader(filepath)
        page_data = []
        errors_found = []
        image_references = []
        photo_pages = []
        estimate_end_page = pdf_ops.detect_estimate_end(reader)
        photo_page_count = max(0, len(reader.pages) - estimate_end_page)

        _append_log(paths, f"enhancer job started filename={filename} photo_pages={photo_page_count}")
        _psutil_rss(paths, 'start', photo_page_count)
        _write_stage(paths, 'Preparing...')

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
        if spec.get('highlight_code_refs'):
            full_text = "\n".join(pd['text'] for pd in page_data)
            auto_code_terms = pdf_ops.extract_code_reference_terms(full_text)

        highlight_configs = pdf_ops.extract_highlight_configs_from_dict(
            spec.get('highlights', {}), auto_terms=auto_code_terms, auto_color=CODE_REF_HL_HEX)

        highlighted_pages = []
        for pd in page_data:
            pd['errors'] = [e for e in errors_found if e['page'] == pd['page_num']]
            pd['text'] = add_image_links(pd['text'], image_link_map)
            if highlight_configs:
                pd['text'] = pdf_ops.highlight_terms(pd['text'], highlight_configs)
            highlighted_pages.append(pd)

        selected_docs = []
        for doc in get_document_options():
            if spec.get('docs', {}).get(doc['id']) and os.path.exists(doc['file']):
                selected_docs.append(doc['file'])

        temp_pdf = filepath + '.temp.pdf'
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        with open(temp_pdf, 'wb') as f:
            writer.write(f)

        output_pdf = filepath + '.output.pdf'
        fork_rules = pdf_ops.build_fork_highlight_rules(highlight_configs)
        _write_stage(paths, 'Linking image references...')
        _psutil_rss(paths, 'before fork', photo_page_count)
        ok, out, err = process_with_fork(filepath, output_pdf, fork_rules)
        if out:
            _append_log(paths, out)
        if err:
            _append_log(paths, 'FORK STDERR: ' + err)
        if not ok or not os.path.exists(output_pdf):
            _write_json(paths['error'], {'error': 'Failed to generate linked PDF output'})
            cleanup_file(temp_pdf)
            cleanup_file(output_pdf)
            return
        _append_log(paths, out or '')

        highlight_warning = None
        if fork_rules and pdf_ops.count_pdf_highlight_annotations(output_pdf) == 0:
            highlight_warning = ('No occurrences of the highlight terms were found in the '
                                 'document, so nothing was highlighted.')

        _write_stage(paths, 'Flattening highlights...')
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
        for up in (spec.get('user_pdfs') or []):
            if up and os.path.exists(up):
                try:
                    user_doc = fitz.open(up)
                    final_doc.insert_pdf(user_doc)
                    user_doc.close()
                    os.remove(up)
                    added_user_pdfs += 1
                except Exception:
                    pass

        _write_stage(paths, 'Finalizing PDF...')
        _psutil_rss(paths, 'before final save', photo_page_count)
        final_doc.save(output_file, garbage=4, deflate=True, clean=True)
        final_doc.close()
        _psutil_rss(paths, 'after final save', photo_page_count)

        cleanup_file(filepath)
        cleanup_file(output_pdf)

        # Opportunistic 1h sweeper for old processed files
        try:
            cutoff = time.time() - 3600
            for p in Path(_upload_dir()).glob('processed_*'):
                try:
                    if p.is_file() and p.stat().st_mtime < cutoff:
                        p.unlink()
                except Exception:
                    pass
        except Exception:
            pass

        _write_stage(paths, 'Done')
        _append_log(paths, 'enhancer job complete')
        _write_json(paths['result'], {
            'filename': filename,
            'total_pages': len(reader.pages),
            'errors': errors_found,
            'attachments_added': len(selected_docs) + added_user_pdfs,
            'highlighted_pages': highlighted_pages,
            'image_links': image_links,
            'highlight_warning': highlight_warning,
        })
    except Exception as e:
        _append_log(paths, 'ERROR: ' + str(e))
        _write_json(paths['error'], {'error': str(e)})
    finally:
        # remove spec so status does not think it is still queued
        cleanup_file(paths['spec'])


# === SECTION: routes ===
@bp.route('/')
def index():
    return render_template('estimate_enhancer.html', documents=get_document_options())


@bp.route('/test', methods=['GET', 'POST'])
def test():
    return jsonify({'test': 'ok'})


@bp.route('/analyze', methods=['POST'])
def analyze():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        file = request.files['file']

        # Always store under a unique name so re-uploading a file with the same basename
        # (even different content) starts a completely fresh session. No cache of old bytes.
        orig = secure_filename(file.filename or 'estimate.pdf')
        unique = f"{uuid.uuid4().hex[:8]}_{int(time.time())}_{orig}"
        filepath = os.path.join(_upload_dir(), unique)
        file.save(filepath)

        # Web size guard (early reject before heavy work)
        if Config.WEB_MODE:
            limits = _load_web_limits()
            max_mb = int(limits.get("enhancer_max_mb", 15))
            try:
                size = os.path.getsize(filepath)
                if size > max_mb * 1024 * 1024:
                    cleanup_file(filepath)
                    return jsonify({'error': f"PDF must be {max_mb} MB or smaller on the web version."}), 400
            except Exception:
                pass

        reader = PdfReader(filepath)
        errors_found = []
        estimate_end_page = pdf_ops.detect_estimate_end(reader)
        photo_page_count = max(0, len(reader.pages) - estimate_end_page)

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
            'filename': unique,   # unique key for the rest of the flow
            'has_errors': len(errors_found) > 0,
            'errors': errors_found[:100],
            'total_pages': len(reader.pages),
            'photo_page_count': photo_page_count,
            'code_references': code_refs,
            'auto_selected_docs': auto_selected_docs,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/process', methods=['POST'])
def process():
    """Starter: persist job spec + any user PDFs, start background worker, return immediately."""
    filename = request.form.get('filename')
    filepath = os.path.join(_upload_dir(), filename or '')
    if not filename or not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 400

    # Build a portable spec (no request-bound file objects)
    highlights = {}
    for k in ['highlight_1', 'highlight_2', 'highlight_3', 'highlight_4', 'highlight_5']:
        t = (request.form.get(f'{k}_term') or '').strip()
        c = (request.form.get(f'{k}_color') or '').strip()
        if t:
            highlights[k] = {'term': t, 'color': c}
    docs = {}
    for doc in get_document_options():
        if request.form.get(f'doc_{doc["id"]}'):
            docs[doc['id']] = True
    highlight_code_refs = bool(request.form.get('highlight_code_refs'))

    # Persist user PDFs to stable paths so the worker can consume them after request ends
    saved_user_pdfs = []
    for user_file in request.files.getlist('user_pdf'):
        if user_file and pdf_ops.allowed_file(user_file.filename):
            safe = secure_filename(user_file.filename)
            stable = os.path.join(_upload_dir(), f"user_{uuid.uuid4().hex[:8]}_{int(time.time())}_{safe}")
            user_file.save(stable)
            if os.path.exists(stable):
                saved_user_pdfs.append(stable)

    spec = {
        'highlights': highlights,
        'docs': docs,
        'highlight_code_refs': highlight_code_refs,
        'user_pdfs': saved_user_pdfs,
    }
    paths = _job_paths(filename)
    _write_json(paths['spec'], spec)
    # clear any prior sidecars
    for k in ('stage', 'log', 'result', 'error'):
        cleanup_file(paths[k])

    # Start worker in a background thread.
    # Pure href builder is used; no Flask context or app object is required.
    t = threading.Thread(target=_run_enhance, args=(filename,), daemon=True)
    t.start()

    return jsonify({'status': 'started', 'filename': filename})


@bp.route('/download/<filename>')
def download_file(filename):
    # Do NOT delete here. Lifetime is 1h (mtime) or explicit Start new (which deletes source+processed).
    # Same button must allow re-download of the exact same processed PDF while it lives.
    filepath = os.path.join(_upload_dir(), 'processed_' + filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return "File not found", 404


@bp.route('/uploads/<filename>')
def serve_upload(filename):
    filepath = os.path.join(_upload_dir(), filename)
    if os.path.exists(filepath):
        return send_file(filepath)
    return "File not found", 404


@bp.route('/clear', methods=['POST'])
def clear_current():
    """Delete source and processed for a given unique filename.
    Used by "Start new" and on fresh file selection to ensure no stale content.
    """
    fn = (request.form.get('filename') or '').strip()
    if not fn:
        return jsonify({'ok': True})
    src = os.path.join(_upload_dir(), fn)
    proc = os.path.join(_upload_dir(), 'processed_' + fn)
    cleanup_file(src)
    cleanup_file(proc)
    # Also clean any temp artifacts from previous run
    for suffix in ('.temp.pdf', '.output.pdf'):
        cleanup_file(os.path.join(_upload_dir(), fn + suffix))
    # Clean job sidecars for this enhancer job
    _cleanup_sidecars(fn)
    return jsonify({'ok': True})


@bp.route('/process/status', methods=['GET'])
def process_status():
    """Return job status for a filename: {status: 'running'|'done'|'error', stage?, result...}"""
    fn = (request.args.get('filename') or '').strip()
    if not fn:
        return jsonify({'status': 'error', 'error': 'Missing filename'}), 400
    paths = _job_paths(fn)
    if os.path.exists(paths['result']):
        try:
            data = json.loads(open(paths['result'], 'r').read())
            return jsonify({'status': 'done', **data})
        except Exception as e:
            return jsonify({'status': 'error', 'error': str(e)})
    if os.path.exists(paths['error']):
        try:
            err = json.loads(open(paths['error'], 'r').read())
        except Exception:
            err = {'error': 'Unknown error'}
        return jsonify({'status': 'error', **err})
    if os.path.exists(paths['spec']) or os.path.exists(os.path.join(_upload_dir(), fn)):
        stage = _read_text(paths['stage'], 'Processing...')
        return jsonify({'status': 'running', 'stage': stage})
    return jsonify({'status': 'error', 'error': 'Job not found'}), 404


@bp.route('/process/log', methods=['GET'])
def process_log():
    """Return (tail of) the enhancer job log for the given filename."""
    fn = (request.args.get('filename') or '').strip()
    if not fn:
        return 'Missing filename', 400
    paths = _job_paths(fn)
    log_text = _read_text(paths['log'], '')
    # Tail to ~400 lines for the modal
    lines = log_text.splitlines()[-400:]
    return '\n'.join(lines)
