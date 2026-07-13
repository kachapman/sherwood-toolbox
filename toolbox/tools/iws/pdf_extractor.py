import re
from collections import Counter
try:
    import fitz
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


class ExtractionError(Exception):
    pass


def extract_measurements_from_pdf(pdf_path):
    if not PDF_AVAILABLE:
        raise ExtractionError("PyMuPDF (fitz) is not installed. Cannot extract PDF text.")
    
    text = _extract_text_from_pdf(pdf_path)
    if not text:
        raise ExtractionError("Could not extract text from PDF.")
    
    roof_size_sq = _extract_roof_size(text)
    roof_pitch = _extract_pitch(text)
    eave_length = _extract_eave_length(text)
    valley_length = _extract_valley_length(text)
    soffit_depths = _extract_soffit_depths(text)
    
    if soffit_depths:
        predominant_soffit = _calculate_predominant_soffit_depth(soffit_depths)
    else:
        predominant_soffit = None
    
    return {
        'roofSizeSq': roof_size_sq,
        'roofPitch': roof_pitch,
        'eaveLength': eave_length,
        'valleyLength': valley_length,
        'soffitDepth': predominant_soffit,
        'insideWall': 24,
    }


def _extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        try:
            return '\n'.join(page.get_text() for page in doc)
        finally:
            doc.close()
    except Exception as e:
        raise ExtractionError(f"Failed to read PDF: {e}")


def _extract_roof_size(text):
    patterns = [
        r'(?:roof\s+area|total\s+roof\s+area)\s*:?\s*([\d,]+\.?\d*)\s*(?:ft²|sq\s+ft|square\s+feet)',
        r'(?:area)\s*:?\s*([\d,]+\.?\d*)\s*(?:ft²|sq\s+ft)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            area_ft2 = float(match.group(1).replace(',', ''))
            return round(area_ft2 / 100, 2)
    
    return None


def _extract_pitch(text):
    patterns = [
        r'(?:pitch|slope)\s*:?\s*(\d+)\s*/\s*12',
        r'(\d+)\s*/\s*12\s*(?:pitch|slope)',
        r'roof\s+pitch\*?.{0,80}?(\d+)\s*/\s*12',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1))
    
    return None


def _feet_inches_to_decimal(feet_str):
    if not feet_str:
        return None
    
    feet_str = feet_str.strip()
    if feet_str.lower() in ('0', 'none', 'no'):
        return 0.0
    
    feet_match = re.search(r"(\d+)\s*'", feet_str)
    inches_match = re.search(r'(\d+)\s*"', feet_str)
    
    feet = int(feet_match.group(1)) if feet_match else 0
    inches = int(inches_match.group(1)) if inches_match else 0
    
    return round(feet + inches / 12, 2)


def _extract_eave_length(text):
    patterns = [
        r'(?:eaves?|eave\s+length)\s*:?\s*([\d\s\'\"-]+)',
        r'eaves?\s*\(total\)\s*:?\s*([\d\s\'\"-]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            length_str = match.group(1)
            return _feet_inches_to_decimal(length_str)
    
    return None


def _extract_valley_length(text):
    patterns = [
        r'(?:valleys?|valley\s+length)\s*:?\s*([\d\s\'\"-]+|0|none)',
        r'valleys?\s*\(total\)\s*:?\s*([\d\s\'\"-]+|0|none)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            length_str = match.group(1)
            return _feet_inches_to_decimal(length_str)
    
    return None


def _extract_soffit_depths(text):
    depths = []
    
    # HOVER "Soffit Breakdown" table: rows come out of fitz as
    # 'eave' on one line followed by the depth like '33"' on the next.
    breakdown = re.search(r'soffit\s+breakdown(.*?)(?:\n(?-i:[A-Z]{2,})|\Z)', text,
                          re.IGNORECASE | re.DOTALL)
    section = breakdown.group(1) if breakdown else text
    for match in re.finditer(r'\beaves?\b\s*\n\s*(\d+(?:\.\d+)?)\s*"', section,
                             re.IGNORECASE):
        depth = float(match.group(1))
        if 5 <= depth <= 100:
            depths.append(int(depth))
    if depths:
        return depths
    
    patterns = [
        r'(?:eave|depth)\s+(\d+)\s*:.*?(\d+)\s*"',
        r'eave\s+depth\s*:?\s*(\d+)\s*"',
        r'depth[:\s]+(\d+)\s*"',
    ]
    
    for pattern in patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            depth_str = match.group(match.lastindex) if match.lastindex > 1 else match.group(1)
            try:
                depth = int(depth_str)
                if 5 <= depth <= 100:
                    depths.append(depth)
            except ValueError:
                continue
    
    return depths or None


def _extract_numeric_inches(depth_str):
    match = re.search(r'(\d+(?:\.\d+)?)', str(depth_str))
    return float(match.group(1)) if match else None


def _calculate_predominant_soffit_depth(depths):
    if not depths:
        return None
    
    numeric_depths = [_extract_numeric_inches(d) for d in depths]
    numeric_depths = [d for d in numeric_depths if d is not None]
    
    if not numeric_depths:
        return None
    
    if len(numeric_depths) == 1:
        return _as_clean_number(numeric_depths[0])
    
    counts = Counter(numeric_depths)
    max_freq = max(counts.values())
    modes = [v for v, c in counts.items() if c == max_freq]
    
    if len(modes) == 1:
        return _as_clean_number(modes[0])
    
    avg = sum(numeric_depths) / len(numeric_depths)
    return _as_clean_number(round(avg, 1))


def _as_clean_number(value):
    return int(value) if float(value).is_integer() else float(value)
