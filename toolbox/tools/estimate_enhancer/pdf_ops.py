"""Pure PDF analysis and enhancement logic for Estimate Enhancer.

No Flask, no config, no filesystem layout assumptions: every function takes
explicit text, paths, or PDF objects. Ported verbatim from the original
EstimateEnhancer app.py so behavior is unchanged. The HTTP layer lives in
routes.py; the heavy lifting lives here.

Sections below are grouped so an edit target is found by name:
  - constants and color normalization
  - attachment code parsing
  - estimate / photo page detection
  - issue checks (zero qty, notes, duplicate photo names)
  - fuzzy matching helpers
  - code-reference + highlight config building
  - PyMuPDF operations (flatten, links, redaction)
"""
import os
import re
from difflib import SequenceMatcher

import fitz

from .utils.markup_bridge import split_term_input, highlight_terms as _highlight_terms

# === SECTION: constants and color normalization ===
SEE_IMAGE_RE = re.compile(
    r"See\s+image[.,;:]?\s*(?P<name>.+?)\s*[.,;:]?\s*in\s+the\s+Images\s+section\s+of\s+this\s+report",
    re.IGNORECASE | re.DOTALL,
)
CODE_REFERENCE_RE = re.compile(
    r"\[?(R\.?\d{3}(?:\.\d+)+(?:\(\d+\))?)\]?",
    re.IGNORECASE,
)
ATTACHMENT_CODE_RE = re.compile(r'\b(R\d{3}(?:[._]\d+)+)', re.IGNORECASE)

YELLOW_HL_HEX = '#FAFFA0'
ORANGE_HL_HEX = '#FFBCA6'
CODE_REF_HL_HEX = '#A8D2FC'

ALLOWED_EXTENSIONS = {'pdf'}


def normalize_highlight_color(color: str) -> str:
    """Normalize supported highlight colors to canonical hex values."""
    raw = (color or '').strip()
    if not raw:
        return YELLOW_HL_HEX
    value = raw.upper()
    if value in {'#FFEB3B', YELLOW_HL_HEX}:
        return YELLOW_HL_HEX
    if value in {'#FF7043', ORANGE_HL_HEX}:
        return ORANGE_HL_HEX
    if value in {CODE_REF_HL_HEX, '#42A5F5'}:
        return CODE_REF_HL_HEX
    return raw


# === SECTION: attachment code parsing ===
def parse_attachment_code(doc_id):
    """'2015 IRC R905_2_8_2 - Valley Required' -> 'R905.2.8.2'."""
    match = ATTACHMENT_CODE_RE.search(doc_id or '')
    if not match:
        return None
    return match.group(1).upper().replace('_', '.')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# === SECTION: estimate / photo page detection ===
def detect_estimate_end(reader):
    """Detect where the estimate ends and photo pages start."""
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ''
        lines = text.split('\n')
        first_line = lines[0].strip() if lines else ''
        if first_line.isdigit() and 'Taken By:' in text:
            return i
        if 'Date Taken:' in text or 'Taken By:' in text:
            return i
    return len(reader.pages)


def extract_photo_name(text):
    """Extract a photo caption from a photo page, filtering metadata lines."""
    lines = text.strip().split('\n')
    skip_patterns = [
        r'^taken\s+by[:\s]', r'^date\s+taken[:\s]', r'^photo\s+by[:\s]',
        r'^photographer[:\s]', r'^captured\s+by[:\s]', r'^shot\s+by[:\s]',
        r'^credit[:\s]', r'^source[:\s]', r'^\d{1,2}/\d{1,2}/\d{2,4}$', r'^page[:\s]*\d+',
    ]
    caption_lines = []
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        if any(re.search(p, line_stripped, re.IGNORECASE) for p in skip_patterns):
            continue
        caption_lines.append(line_stripped)

    result_parts = []
    for line in caption_lines:
        if result_parts and result_parts[-1].endswith('-'):
            result_parts[-1] = result_parts[-1] + line
        else:
            result_parts.append(line)
    reassembled = ' '.join(result_parts)

    patterns = [
        r'Page:\s*\d+\s+(.+?)\s+Date\s+Taken:',
        r'Page:\s*\d+\s+(.+?)\s+Taken\s+By:',
        r'Page:\s*\d+\s+(.+?)$',
        r'^\d+\.?\s+(.+)$',
    ]
    for pattern in patterns:
        match = re.search(pattern, reassembled, re.IGNORECASE | re.MULTILINE)
        if match:
            name = match.group(1).strip()
            if name:
                return name
    for line in caption_lines:
        if line and not line.isdigit():
            return line
    return None


# === SECTION: issue checks ===
def check_zero_qty(text, page_num):
    errors = []
    lines = text.split('\n')
    in_item_section = False
    line_item_pattern = re.compile(r'^(\d+)\.\s+(.+)$')
    qty_pattern = re.compile(r'(\d+\.?\d*)\s*(SQ|EA|SF|LF|CY|YD|MT|PC|LN|YD)', re.IGNORECASE)
    for line_idx, line in enumerate(lines):
        line = line.strip()
        if line.startswith('DESCRIPTION QUANTITY') or 'DESCRIPTION QUANTITY UNIT' in line:
            in_item_section = True
            continue
        if in_item_section and (line.startswith('Totals:') or line.startswith('Total:')):
            in_item_section = False
            continue
        if in_item_section and line:
            item_match = line_item_pattern.match(line)
            if item_match:
                description = item_match.group(2).strip()
                qty_match = qty_pattern.search(description)
                if qty_match and float(qty_match.group(1)) == 0:
                    errors.append({
                        'page': page_num, 'line': line_idx + 1,
                        'description': description[:100], 'units': qty_match.group(2)[:20],
                        'full_line': line[:200], 'type': 'Zero Quantity',
                    })
    return errors


def check_qty_and_spelling_errors(text, page_num):
    errors = []
    lines = text.split('\n')
    in_item_section = False
    line_item_pattern = re.compile(r'^(\d+)\.\s+(.+)$')
    current_item = None
    for line_idx, line in enumerate(lines):
        line = line.strip()
        if line.startswith('DESCRIPTION'):
            in_item_section = True
            continue
        if in_item_section and line.startswith(('Totals:', 'Total:')):
            in_item_section = False
            current_item = None
            continue
        if in_item_section and line:
            item_match = line_item_pattern.match(line)
            if item_match:
                current_item = item_match.group(1).strip()
                description = item_match.group(2).strip()
                qty_pattern = re.compile(r'(\d+\.?\d*)\s*(SQ|EA|SF|LF|CY|YD|MT|PC|LN|YD)', re.IGNORECASE)
                qty_match = qty_pattern.search(description)
                if qty_match and float(qty_match.group(1)) == 0:
                    errors.append({
                        'page': page_num, 'line': line_idx + 1,
                        'description': f"0 Qty: {description[:60]}", 'units': qty_match.group(2),
                        'type': 'Zero Quantity',
                    })
            elif current_item and 'ERROR' in line:
                errors.append({
                    'page': page_num, 'line': line_idx + 1,
                    'description': f"Note under item {current_item}: {line[:60]}",
                    'units': '', 'type': 'Spelling Error',
                })
    return errors[:30]


def normalize_for_match(text):
    """Normalize for fuzzy matching."""
    text = text.lower()
    text = re.sub(r'-\s*\n\s*', '-', text)
    text = " ".join(text.split())
    text = re.sub(r'[-_]', ' ', text)
    text = re.sub(r'[.,;:!?()\[\]{}]', '', text)
    return text


def normalize_whitespace(text):
    return " ".join(text.split())


def similarity_ratio(a, b):
    return SequenceMatcher(None, a, b).ratio()


def find_image_references(text, page_num):
    """Find "See image" references using the fork's regex."""
    references = []
    seen_names = set()
    for match in SEE_IMAGE_RE.finditer(text):
        name = " ".join(match.group("name").strip().split())
        if name and name.lower() not in seen_names:
            seen_names.add(name.lower())
            references.append({'image_name': name, 'from_page': page_num})
    return references


def check_duplicate_photo_names(reader, estimate_end_page):
    """Warn when two or more photo pages share the same caption."""
    warnings = []
    groups = {}
    for i in range(estimate_end_page, len(reader.pages)):
        text = reader.pages[i].extract_text() or ''
        name = extract_photo_name(text)
        if not name:
            continue
        key = normalize_for_match(name)
        if not key:
            continue
        groups.setdefault(key, {'name': name, 'pages': []})['pages'].append(i + 1)
    for group in groups.values():
        pages = group['pages']
        if len(pages) < 2:
            continue
        warnings.append({
            'page': pages[0], 'line': '-', 'type': 'Duplicate Photo Name',
            'description': f'Photo name "{group["name"][:80]}" appears on {len(pages)} photo pages '
                           f'({", ".join(str(p) for p in pages)})',
            'units': 'Rename so each photo is unique; duplicates make "See image" links ambiguous',
        })
    return warnings


# === SECTION: code references + highlight config ===
def highlight_terms(text, highlight_configs, case_sensitive=False, whole_word=True):
    """Wrapper around utils.markup_bridge.highlight_terms."""
    if not highlight_configs:
        return text
    terms, colors = [], []
    for config in highlight_configs:
        term = (config.get('term', '') or '').strip()
        if not term:
            continue
        terms.append(term)
        colors.append((config.get('color') or '').strip())
    if not terms:
        return text
    return _highlight_terms(
        text, terms, css_class='hl', case_sensitive=False, whole_word=whole_word,
        overlap_strategy='first', term_colors=colors,
    )


def extract_code_reference_terms(text: str) -> list:
    if not text:
        return []
    found, seen = [], set()
    for match in CODE_REFERENCE_RE.finditer(text):
        raw = (match.group(1) or '').strip()
        if not raw:
            continue
        canonical = raw.upper()
        if canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
    return found


def match_attachments_to_references(refs, docs):
    """Return doc ids whose parsed IRC code matches any extracted reference."""
    canonical_refs = []
    for ref in (refs or []):
        ref_canon = re.sub(r'^R\.', 'R', (ref or '').strip().upper())
        ref_canon = re.sub(r'\(\d+\)$', '', ref_canon)
        if ref_canon:
            canonical_refs.append(ref_canon)
    matched = []
    for doc in docs:
        code = doc.get('code')
        if not code:
            continue
        for ref_canon in canonical_refs:
            if ref_canon == code or ref_canon.startswith(code + '.'):
                matched.append(doc['id'])
                break
    return matched


def extract_highlight_configs(form, *, auto_terms=None, auto_color=CODE_REF_HL_HEX):
    """Normalize and dedupe highlight form inputs (preserving user case/color)."""
    configs = []
    seen_terms = set()
    for key in ['highlight_1', 'highlight_2', 'highlight_3', 'highlight_4', 'highlight_5']:
        raw_term_input = (form.get(f'{key}_term', '') or '').strip()
        if not raw_term_input:
            continue
        color = normalize_highlight_color((form.get(f'{key}_color', '') or '').strip())
        for term in split_term_input(raw_term_input):
            if term in seen_terms:
                continue
            seen_terms.add(term)
            configs.append({'term': term, 'color': color})
    for raw_term in (auto_terms or []):
        term = (raw_term or '').strip()
        if not term or term in seen_terms:
            continue
        seen_terms.add(term)
        configs.append({'term': term, 'color': normalize_highlight_color(auto_color)})
    return configs


def build_fork_highlight_rules(highlight_configs: list) -> list:
    """Build fork-compatible highlight rules payload from normalized terms."""
    rules = []
    for idx, config in enumerate(highlight_configs, start=1):
        term = str(config.get('term', '')).strip()
        if not term:
            continue
        color = normalize_highlight_color(str(config.get('color', '') or '').strip())
        if CODE_REFERENCE_RE.fullmatch(term):
            color = CODE_REF_HL_HEX
        rules.append({'label': f'hl{idx}', 'color': color, 'phrases': [term]})
    return rules


# === SECTION: PyMuPDF operations ===
def count_pdf_highlight_annotations(pdf_path: str) -> int:
    if not os.path.exists(pdf_path):
        return 0
    total = 0
    doc = fitz.open(pdf_path)
    try:
        for page_num in range(len(doc)):
            annots = doc.load_page(page_num).annots()
            if not annots:
                continue
            for annot in annots:
                if (annot.type[1] or '').lower() == 'highlight':
                    total += 1
    finally:
        doc.close()
    return total


def flatten_pdf_highlights(pdf_path: str, output_path=None, fill_opacity: float = 0.4) -> int:
    """Flatten highlight annotations to permanent page graphics."""
    doc = fitz.open(pdf_path)
    total_flattened = 0
    for page in doc:
        for annot in list(page.annots()):
            if annot.type[1] != 'Highlight':
                continue
            original_color = annot.colors.get('stroke')
            if not original_color:
                continue
            vertices = annot.vertices
            if not vertices or len(vertices) < 4:
                continue
            shape = page.new_shape()
            for i in range(0, len(vertices), 4):
                quad_points = vertices[i:i + 4]
                if len(quad_points) != 4:
                    continue
                shape.draw_quad(fitz.Quad(quad_points))
            shape.finish(fill=original_color, color=None, fill_opacity=fill_opacity, closePath=True)
            shape.commit(overlay=False)
            page.delete_annot(annot)
            total_flattened += 1
    temp_path = pdf_path + '.flat.tmp'
    doc.save(temp_path, garbage=4, deflate=True)
    doc.close()
    os.replace(temp_path, output_path or pdf_path)
    return total_flattened


def sanitize_pdf(input_path):
    """Sanitize PDF to fix XREF errors and corruptions."""
    try:
        raw_doc = fitz.open(input_path)
        pdf_bytes = raw_doc.tobytes(garbage=4, deflate=True, clean=True)
        raw_doc.close()
        return fitz.open("pdf", pdf_bytes)
    except Exception as e:
        print(f"Could not sanitize PDF: {e}")
        return fitz.open(input_path)


def get_page_background_color(page):
    """Detect page background color by sampling corners."""
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
        offset = 10
        samples = []
        corners = [(offset, offset), (pix.width - offset - 1, offset),
                   (offset, pix.height - offset - 1),
                   (pix.width - offset - 1, pix.height - offset - 1)]
        for x, y in corners:
            try:
                color = pix.pixel(x, y)
                if len(color) >= 3:
                    samples.append((color[0] / 255, color[1] / 255, color[2] / 255))
            except Exception:
                pass
        if samples:
            return tuple(sum(s[i] for s in samples) / len(samples) for i in range(3))
    except Exception:
        pass
    return (1, 1, 1)


def remove_taken_by_text(page):
    """Redact 'Taken By:' style metadata text from a PDF page."""
    bg_color = get_page_background_color(page)
    patterns = [
        r"taken\s+by[:\s]+[^\n]*", r"photo\s+by[:\s]+[^\n]*", r"image\s+by[:\s]+[^\n]*",
        r"photographer[:\s]+[^\n]*", r"captured\s+by[:\s]+[^\n]*", r"shot\s+by[:\s]+[^\n]*",
        r"credit[:\s]+[^\n]*", r"source[:\s]+[^\n]*",
    ]
    text = page.get_text()
    removed_count = 0
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            try:
                for rect in page.search_for(match.group(0)):
                    tight = fitz.Rect(rect.x0 - 1, rect.y0 - 0.15, rect.x1 + 1, rect.y1 + 1)
                    page.add_redact_annot(tight, fill=bg_color)
                    removed_count += 1
            except Exception as e:
                print(f"Could not remove '{match.group(0)}': {e}")
    if removed_count > 0:
        try:
            page.apply_redactions(images=0, graphics=0, text=0)
        except Exception as e:
            print(f"Could not apply redactions: {e}")
    return removed_count


def find_text_location(page, image_name: str):
    """Robustly find coordinates of a 'See image' reference on a page."""
    patterns_to_try = [
        f"See image, {image_name}, in the Images section",
        f"See image {image_name} in the Images section",
        f"See image {image_name}",
        "See image",
    ]
    for pattern in patterns_to_try:
        rects = page.search_for(pattern)
        if rects:
            return rects
    start_rects = []
    for p in ["See image,", "See image.", "See image"]:
        start_rects.extend(page.search_for(p))
    name_rects = page.search_for(image_name)
    valid_rects = []
    if start_rects and name_rects:
        for s_rect in start_rects:
            for n_rect in name_rects:
                if abs(n_rect.y0 - s_rect.y0) < 50:
                    valid_rects.append(s_rect | n_rect)
    if valid_rects:
        return valid_rects
    if name_rects:
        return name_rects[:1]
    return []


def add_links_with_pymupdf(input_path, output_path, links_to_add, remove_taken_by=False):
    """Add intra-document links with blue underlines using PyMuPDF."""
    doc = sanitize_pdf(input_path)
    blue_color = (0, 0.4, 0.8)
    if remove_taken_by:
        for page_num in range(len(doc)):
            remove_taken_by_text(doc.load_page(page_num))
    for link in links_to_add:
        from_page = link['from_page']
        to_page = link['to_page']
        image_name = link.get('image_name', '')
        if from_page >= len(doc):
            continue
        page = doc.load_page(from_page)
        rects = find_text_location(page, image_name)
        if rects:
            rect = rects[0]
            page.draw_line(fitz.Point(rect.x0, rect.y1 - 1), fitz.Point(rect.x1, rect.y1 - 1),
                           color=blue_color, width=1)
            page.insert_link({"kind": fitz.LINK_GOTO, "from": rect, "page": to_page,
                              "to": fitz.Point(0, 0), "zoom": 0})
        else:
            page.insert_link({"kind": fitz.LINK_GOTO, "from": page.rect, "page": to_page,
                              "to": fitz.Point(0, 0), "zoom": 0})
    doc.save(output_path)
    doc.close()
