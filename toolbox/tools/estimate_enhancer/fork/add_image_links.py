#!/usr/bin/env python3
"""
add_image_links.py

Add intra-document hyperlinks to a PDF with robust handling for:
- Line breaks in source text.
- Variations in punctuation (commas vs periods).
- Distinguishing between Headers/Body text and actual Image Captions.
- Long image names with hyphens, underscores, and special characters.
- Captions split by metadata lines (Taken By, Date Taken, etc.)

Usage:
    # 1. To process all non-'_linked' PDFs in the current directory:
    add_image_links 
    
    # 2. To process specific files:
    add_image_links "./ROGERS-J_Siding 12.1.25.pdf"
    
    # 3. Enable debug mode for troubleshooting:
    add_image_links --debug "./ROGERS-J_Siding 12.1.25.pdf"
"""

import sys
import re
import pathlib
import fitz  # PyMuPDF
from difflib import SequenceMatcher
import json
import os

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DEBUG_MODE = False  # Set via --debug flag

def set_debug(value: bool):
    """Set debug mode."""
    global DEBUG_MODE
    DEBUG_MODE = value

def debug_print(*args, **kwargs):
    """Print only if DEBUG mode is enabled."""
    if DEBUG_MODE:
        print("   [DEBUG]", *args, **kwargs)

# ----------------------------------------------------------------------
# Regex patterns (Robust to line breaks, punctuation)
# ----------------------------------------------------------------------
# More flexible pattern - handles various punctuation and whitespace
SEE_IMAGE_RE = re.compile(
    r"See\s+image[.,;:]?\s*(?P<name>.+?)\s*[.,;:]?\s*in\s+the\s+Images\s+section\s+of\s+this\s+report",
    re.IGNORECASE | re.DOTALL
)

def ask_add_highlights() -> bool:
    """Deprecated interactive prompt path (always disabled)."""
    return False


def _normalize_highlight_token(text: str) -> str:
    """Normalize token text for case-insensitive matching."""
    return re.sub(r"[^0-9A-Za-z]+", "", text).lower()


def _normalize_highlight_phrase(phrase: str) -> list[str]:
    """
    Normalize a phrase into token chunks for matching.

    Handles multi-word phrases by splitting on whitespace first, then normalizing
    each word. This ensures phrases like "SEE REVISION" match the corresponding
    words extracted from the PDF.
    """
    # Split on whitespace to handle multi-word phrases.
    words = phrase.split()
    return [
        _normalize_highlight_token(word)
        for word in words
        if _normalize_highlight_token(word)
    ]


def _hex_to_fitz_color(value: str) -> tuple[float, float, float] | None:
    """Convert hex color strings to fitz RGB tuple in 0..1 range."""
    if not isinstance(value, str):
        return None

    color = value.strip()
    if color.startswith("#"):
        hex_color = color.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join(ch * 2 for ch in hex_color)
        if len(hex_color) == 6:
            try:
                r = int(hex_color[0:2], 16) / 255
                g = int(hex_color[2:4], 16) / 255
                b = int(hex_color[4:6], 16) / 255
                return (r, g, b)
            except ValueError:
                return None
        return None

    return None


def _normalize_highlight_rules(raw_rules) -> list[dict]:
    """Normalize fork highlight payload from app into rule dictionaries."""
    if not isinstance(raw_rules, list):
        return []

    rules: list[dict] = []
    for idx, rule in enumerate(raw_rules):
        if not isinstance(rule, dict):
            continue

        color = rule.get('color')
        phrases = rule.get('phrases')
        if not isinstance(phrases, list):
            single = rule.get('term')
            if not single:
                continue
            phrases = [single]

        normalized_phrases: list[str] = []
        for phrase in phrases:
            if not isinstance(phrase, str):
                continue
            normalized = phrase.strip()
            if normalized:
                normalized_phrases.append(normalized)

        if not normalized_phrases:
            continue

        norm_color = str(color).strip() if color is not None else ''
        if not norm_color:
            norm_color = "#FAFFA0"

        resolved_color = _hex_to_fitz_color(norm_color)
        if resolved_color is None:
            # Keep compatibility with legacy tuple input.
            if isinstance(color, (tuple, list)) and len(color) >= 3:
                resolved_color = (float(color[0]), float(color[1]), float(color[2]))
            else:
                resolved_color = (0.78, 0.73, 0.28)

        label = rule.get('label')
        if not label:
            label = f"hl{idx + 1}"

        rules.append({
            "label": str(label),
            "color": resolved_color,
            "phrases": normalized_phrases,
        })

    return rules


def _load_fork_highlight_rules() -> list[dict]:
    """
    Load highlight rules from environment payload passed by the Flask app.

    This function pulls user input from app.py's build_fork_highlight_rules()
    which passes highlight terms via the PDF_HIGHLIGHT_RULES_JSON env variable.
    Terms are already normalized to uppercase by app.py for case-insensitive
    matching - only UPPERCASE text in the PDF will be highlighted.

    Returns empty list if no user terms provided (no annotations added).
    """
    raw = os.environ.get("PDF_HIGHLIGHT_RULES_JSON")
    if not raw:
        return []

    try:
        decoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        print("⚠️ Invalid JSON in PDF_HIGHLIGHT_RULES_JSON; skipping PDF highlights")
        return []

    return _normalize_highlight_rules(decoded)


def add_phrase_highlights(doc: fitz.Document, highlight_rules=None) -> int:
    """
    Add phrase highlights based on user-provided terms.

    Highlights case-insensitive text matches from user-provided terms.
    No annotations added unless user provides terms via
    PDF_HIGHLIGHT_RULES_JSON environment variable.

    Returns count of annotations added.
    """
    # No annotations unless user provides terms
    if not highlight_rules:
        debug_print("No highlight rules provided")
        return 0

    debug_print(f"Processing {len(highlight_rules)} highlight rule(s)")
    for rule in highlight_rules:
        debug_print(f"  Rule '{rule.get('label')}': phrases={rule.get('phrases')}")

    total_highlights = 0
    rules = list(highlight_rules)

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        words = page.get_text("words")
        if not words:
            debug_print(f"Page {page_num + 1}: No words found")
            continue

        debug_print(f"Page {page_num + 1}: Processing {len(words)} word(s)")

        normalized_words = []  # (normalized_token, rect, original_token)
        for word in words:
            original_token = word[4]
            norm_token = _normalize_highlight_token(original_token)
            if not norm_token:
                continue
            normalized_words.append(
                (norm_token, fitz.Rect(word[0], word[1], word[2], word[3]), original_token)
            )

        if not normalized_words:
            debug_print(f"Page {page_num + 1}: No normalized words")
            continue

        debug_print(f"Page {page_num + 1}: {len(normalized_words)} normalized word(s)")
        # Sample first few words for debugging
        for i, (tok, _, orig) in enumerate(normalized_words[:5]):
            debug_print(f"  Word {i}: '{orig}' -> '{tok}'")

        cached = set()

        for rule in rules:
            for phrase in rule["phrases"]:
                phrase_tokens = _normalize_highlight_phrase(phrase)
                phrase_len = len(phrase_tokens)
                debug_print(f"  Searching for phrase '{phrase}' -> tokens={phrase_tokens}")

                if phrase_len == 0 or phrase_len > len(normalized_words):
                    debug_print(f"    Skipping: phrase_len={phrase_len}, words={len(normalized_words)}")
                    continue

                matches_found = 0
                for start in range(0, len(normalized_words) - phrase_len + 1):
                    window = normalized_words[start:start + phrase_len]
                    window_tokens = [token for token, _, _ in window]

                    # Match tokens exactly (case-insensitive after normalization)
                    if window_tokens != phrase_tokens:
                        continue

                    # Group the matched words into per-line segments so phrases
                    # that wrap across lines highlight each line instead of
                    # being rejected or unioned into one page-wide rectangle.
                    segments = []
                    for _, item_rect, _ in window:
                        if segments:
                            base = segments[-1]
                            tolerance = max(4.0, (base.y1 - base.y0) * 0.35)
                            if (abs(item_rect.y0 - base.y0) <= tolerance
                                    and abs(item_rect.y1 - base.y1) <= tolerance):
                                segments[-1] = base | item_rect
                                continue
                        segments.append(fitz.Rect(item_rect))

                    cache_key = (
                        tuple(
                            (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))
                            for r in segments
                        ),
                        rule["label"],
                    )
                    if cache_key in cached:
                        continue
                    cached.add(cache_key)

                    try:
                        annot = page.add_highlight_annot(quads=[r.quad for r in segments])
                        annot.set_colors(stroke=rule["color"])
                        annot.set_opacity(1.0)
                        annot.update()
                        total_highlights += 1
                        matches_found += 1
                        debug_print(f"    ✓ Added highlight for '{phrase}' at page {page_num + 1}")
                    except Exception as exc:
                        # Fallback: painted rectangles only
                        try:
                            for seg_rect in segments:
                                page.draw_rect(seg_rect, color=rule["color"], fill=rule["color"], overlay=True)
                            total_highlights += 1
                            matches_found += 1
                            debug_print(f"    ✓ Added rectangle highlight for '{phrase}' at page {page_num + 1}")
                        except Exception as draw_exc:
                            debug_print(f"Could not add highlight '{phrase}' on page {page_num + 1}: {exc} / {draw_exc}")

                if matches_found == 0:
                    debug_print(f"    No matches found for '{phrase}' on page {page_num + 1}")

    debug_print(f"Total highlights added: {total_highlights}")
    return total_highlights

def normalize_whitespace(text: str) -> str:
    """Flatten all whitespace (including line breaks) to single spaces."""
    return " ".join(text.split())

def normalize_for_comparison(text: str) -> str:
    """
    Normalize text for fuzzy comparison:
    - Lowercase
    - Flatten whitespace
    - Remove/normalize punctuation
    - Handle hyphenated line breaks
    """
    text = text.lower()
    # Handle hyphenated line breaks: "word-\ncontination" -> "word-contination"
    text = re.sub(r'-\s*\n\s*', '-', text)
    # Flatten all whitespace to single spaces
    text = normalize_whitespace(text)
    # Normalize hyphens/underscores/dashes to spaces for comparison
    text = re.sub(r'[-_–—]', ' ', text)
    # Remove extra punctuation that might interfere
    text = re.sub(r'[.,;:!?()[\]{}]', '', text)
    # Collapse multiple spaces
    text = ' '.join(text.split())
    return text


def extract_caption_parts(block_text: str) -> list[str]:
    """
    Extract potential caption text from a block, filtering out common non-caption lines.
    Returns a list of lines that are likely part of the caption.
    """
    lines = block_text.strip().split('\n')
    caption_lines = []
    
    # Patterns to skip (metadata lines that interrupt captions)
    skip_patterns = [
        r'^taken\s+by[:\s]',           # "Taken By: Name"
        r'^date\s+taken[:\s]',         # "Date Taken: 9/26/2025"
        r'^photo\s+by[:\s]',           # "Photo by: Name"
        r'^image\s+by[:\s]',           # "Image by: Name"
        r'^photographer[:\s]',         # "Photographer: Name"
        r'^captured\s+by[:\s]',        # "Captured by: Name"
        r'^shot\s+by[:\s]',            # "Shot by: Name"
        r'^credit[:\s]',               # "Credit: Name"
        r'^source[:\s]',               # "Source: Name"
        r'^\d{1,2}/\d{1,2}/\d{2,4}$',  # Standalone dates like "11/30/2025"
        r'^page[:\s]*\d+',             # "Page: 24"
        r'^\d{1,2}:\d{2}\s*(am|pm)?$', # Times like "2:30 PM"
    ]
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        
        # Check if line matches any skip pattern
        should_skip = False
        for pattern in skip_patterns:
            if re.search(pattern, line_stripped, re.IGNORECASE):
                should_skip = True
                break
        
        if not should_skip:
            caption_lines.append(line_stripped)
    
    return caption_lines


def reassemble_caption(caption_lines: list[str]) -> str:
    """
    Reassemble caption lines, handling hyphenated continuations.
    """
    if not caption_lines:
        return ""
    
    result_parts = []
    for i, line in enumerate(caption_lines):
        if result_parts and result_parts[-1].endswith('-'):
            # Previous line ended with hyphen - join without space
            result_parts[-1] = result_parts[-1] + line
        else:
            result_parts.append(line)
    
    return ' '.join(result_parts)


def similarity_ratio(a: str, b: str) -> float:
    """Calculate similarity between two strings (0.0 to 1.0)."""
    return SequenceMatcher(None, a, b).ratio()

def find_best_match(search_name: str, candidates: dict, threshold: float = 0.7) -> str | None:
    """
    Find the best matching key in candidates for the given search_name.
    Returns the matching key or None.
    """
    norm_search = normalize_for_comparison(search_name)
    
    best_match = None
    best_score = 0
    
    for key in candidates:
        norm_key = normalize_for_comparison(key)
        
        # Exact normalized match
        if norm_search == norm_key:
            return key
        
        # Containment check (one contains the other)
        if norm_search in norm_key or norm_key in norm_search:
            score = len(min(norm_search, norm_key, key=len)) / len(max(norm_search, norm_key, key=len))
            if score > best_score:
                best_score = score
                best_match = key
                continue
        
        # Similarity ratio
        score = similarity_ratio(norm_search, norm_key)
        if score > best_score:
            best_score = score
            best_match = key
    
    if best_score >= threshold:
        debug_print(f"Fuzzy match: '{search_name}' -> '{best_match}' (score: {best_score:.2f})")
        return best_match
    
    return None

def is_likely_caption(block_text: str, image_name: str, y_pos: float, page_height: float) -> tuple[bool, int]:
    """
    Determine if a text block is likely an image caption.
    Returns (is_caption, priority_score) where higher score = more likely to be the target.
    
    Priority scoring:
    - 100: Numbered caption (e.g., "13 Moisture barrier")
    - 80: Standalone caption (block is mostly just the image name)
    - 60: Caption-like context (near bottom half of page, short block)
    - 40: General match
    """
    norm_block = normalize_whitespace(block_text).lower()
    norm_name = normalize_whitespace(image_name).lower()
    
    # Check for numbered caption pattern: "13 Moisture barrier" or "13. Moisture barrier"
    numbered_pattern = rf'^\s*\d+\.?\s+{re.escape(norm_name)}'
    if re.search(numbered_pattern, norm_block, re.IGNORECASE):
        return True, 100
    
    # Also check for number anywhere in the block before the name
    if re.search(rf'\d+\s+{re.escape(norm_name)}', norm_block, re.IGNORECASE):
        return True, 95
    
    # Check if block is mostly the image name (standalone caption)
    block_words = set(norm_block.split())
    name_words = set(norm_name.split())
    if len(block_words) > 0:
        overlap = len(block_words & name_words) / len(block_words)
        if overlap > 0.7:  # Block is >70% the image name
            return True, 80
    
    # Check if it's in the lower portion of the page (captions often are)
    if y_pos > page_height * 0.4:  # Lower 60% of page
        # Short blocks are more likely captions
        if len(norm_block) < 200:
            return True, 60
    
    return True, 40

def build_image_index(doc: fitz.Document, image_names: set) -> dict:
    """
    Scans the document to find the *best* page for each image name.
    
    Strategy:
    1. Skip "See image" reference blocks (source, not target)
    2. Skip obvious headers (top of page)
    3. Prioritize exact matches over partial matches
    4. Prioritize numbered captions
    5. For ties, prefer pages later in the document (Images section is usually at end)
    """
    index = {}
    candidate_matches = {name: [] for name in image_names}
    
    # Sort image names by length (longest first) to prioritize more specific matches
    # This helps with "Existing rake starter2" vs "Existing rake starter"
    sorted_names = sorted(image_names, key=len, reverse=True)

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        page_height = page.rect.height
        blocks = page.get_text("blocks")
        
        for block in blocks:
            block_text = block[4] if len(block) > 4 else ""
            y_pos = block[1] if len(block) > 1 else 0
            
            # Normalize block text, handling hyphenated line breaks
            block_text_dehyphenated = re.sub(r'-\s*\n\s*', '-', block_text)
            norm_block_text = normalize_whitespace(block_text_dehyphenated).lower()
            
            # Also try reassembling the caption by filtering out non-caption lines
            caption_lines = extract_caption_parts(block_text)
            reassembled_caption = reassemble_caption(caption_lines)
            norm_reassembled = normalize_whitespace(reassembled_caption).lower()

            # Skip blocks that are "See image" references (these are sources, not targets)
            if "see image" in norm_block_text:
                continue

            # Skip obvious headers (very top of page)
            if y_pos < 50:
                debug_print(f"Skipping header block on page {page_num+1}: y={y_pos:.0f}")
                continue

            for name in sorted_names:
                norm_name = normalize_whitespace(name).lower()
                norm_name_flexible = normalize_for_comparison(name)
                norm_block_flexible = normalize_for_comparison(block_text_dehyphenated)
                norm_reassembled_flexible = normalize_for_comparison(reassembled_caption)
                
                # Check for match using multiple strategies
                match_found = False
                is_exact = False
                
                # Strategy 1: Exact match check (highest priority)
                # For names like "Existing rake starter" vs "Existing rake starter2"
                # we need to ensure we're matching the exact name, not a substring
                exact_patterns = [
                    # Pattern: "13 Existing rake starter" or "13. Existing rake starter"
                    rf'^\d+\.?\s+{re.escape(norm_name)}\s*$',
                    # Pattern: just the name on its own line
                    rf'^{re.escape(norm_name)}\s*$',
                    # Pattern: name followed by newline or end
                    rf'{re.escape(norm_name)}\s*(\n|$)',
                ]
                
                for pattern in exact_patterns:
                    if re.search(pattern, norm_block_text, re.MULTILINE):
                        match_found = True
                        is_exact = True
                        debug_print(f"Strategy 1 (exact): '{name}' found on page {page_num+1}")
                        break
                    if re.search(pattern, norm_reassembled, re.MULTILINE):
                        match_found = True
                        is_exact = True
                        debug_print(f"Strategy 1 (exact in reassembled): '{name}' found on page {page_num+1}")
                        break
                
                if not match_found:
                    # Strategy 2: Check if this is a boundary match (not a substring of a longer name)
                    # Use word boundary or end-of-string check
                    boundary_pattern = rf'{re.escape(norm_name)}(?!\w|\d)'
                    if re.search(boundary_pattern, norm_block_text):
                        # Make sure we're not matching a longer variant
                        # e.g., "starter" shouldn't match if "starter2" is what's in the block
                        longer_variant_found = False
                        for other_name in sorted_names:
                            if other_name != name and name.lower() in other_name.lower():
                                other_norm = normalize_whitespace(other_name).lower()
                                if other_norm in norm_block_text:
                                    longer_variant_found = True
                                    debug_print(f"Skipping '{name}' - longer variant '{other_name}' found in block")
                                    break
                        if not longer_variant_found:
                            match_found = True
                            debug_print(f"Strategy 2 (boundary): '{name}' found on page {page_num+1}")
                
                if not match_found:
                    # Strategy 3: Direct containment (for simpler cases)
                    if norm_name in norm_block_text:
                        # Check we're not matching a longer variant
                        longer_variant_found = False
                        for other_name in sorted_names:
                            if other_name != name and name.lower() in other_name.lower():
                                other_norm = normalize_whitespace(other_name).lower()
                                if other_norm in norm_block_text:
                                    longer_variant_found = True
                                    break
                        if not longer_variant_found:
                            match_found = True
                            debug_print(f"Strategy 3 (containment): '{name}' found on page {page_num+1}")
                
                if not match_found:
                    # Strategy 4: Check reassembled caption (handles "Taken By:" interruptions)
                    if norm_name in norm_reassembled:
                        longer_variant_found = False
                        for other_name in sorted_names:
                            if other_name != name and name.lower() in other_name.lower():
                                other_norm = normalize_whitespace(other_name).lower()
                                if other_norm in norm_reassembled:
                                    longer_variant_found = True
                                    break
                        if not longer_variant_found:
                            match_found = True
                            debug_print(f"Strategy 4 (reassembled): '{name}' found on page {page_num+1}")
                
                if not match_found:
                    # Strategy 5: Flexible match (handles hyphens/underscores as spaces)
                    if norm_name_flexible in norm_block_flexible or norm_name_flexible in norm_reassembled_flexible:
                        match_found = True
                        debug_print(f"Strategy 5 (flexible): '{name}' found on page {page_num+1}")
                
                if not match_found:
                    # Strategy 6: High similarity match for long names
                    if len(norm_name) > 20:
                        sim = similarity_ratio(norm_name_flexible, norm_block_flexible)
                        sim_reassembled = similarity_ratio(norm_name_flexible, norm_reassembled_flexible)
                        best_sim = max(sim, sim_reassembled)
                        if best_sim > 0.8:
                            match_found = True
                            debug_print(f"Strategy 6 (similarity {best_sim:.2f}): '{name}' on page {page_num+1}")
                
                if match_found:
                    is_caption, priority = is_likely_caption(block_text_dehyphenated, name, y_pos, page_height)
                    
                    # Boost priority for exact matches
                    if is_exact:
                        priority += 50
                    
                    candidate_matches[name].append({
                        "page": page_num,
                        "y": y_pos,
                        "priority": priority,
                        "is_exact": is_exact,
                        "block_preview": norm_block_text[:80]
                    })
                    debug_print(f"Added match for '{name}' on page {page_num+1}, priority={priority}, exact={is_exact}")

    # Resolve best matches
    for name, matches in candidate_matches.items():
        if not matches:
            # Try broader search as last resort
            debug_print(f"No block matches for '{name}', trying page-level search...")
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                page_text = page.get_text("text")
                
                # Filter and reassemble the entire page text
                caption_lines = extract_caption_parts(page_text)
                reassembled_page = reassemble_caption(caption_lines)
                norm_reassembled_page = normalize_for_comparison(reassembled_page)
                name_normalized = normalize_for_comparison(name)
                
                if name_normalized in norm_reassembled_page:
                    # Check it's not just a "See image" reference
                    full_text = page_text.lower()
                    see_image_count = full_text.count("see image")
                    name_count = norm_reassembled_page.count(name_normalized)
                    
                    if name_count > see_image_count:
                        debug_print(f"Page-level match for '{name}' on page {page_num+1}")
                        matches.append({
                            "page": page_num,
                            "y": 500,  # Middle of page assumption
                            "priority": 30,  # Lower priority for page-level match
                            "is_exact": False,
                            "block_preview": "page-level match"
                        })
            
        if not matches:
            continue
        
        # Sort by: priority (descending), then page number (descending - prefer later pages)
        matches.sort(key=lambda m: (m["priority"], m["page"]), reverse=True)
        
        best = matches[0]
        index[name] = best["page"]
        
        debug_print(f"Best match for '{name}': page {best['page']+1}, priority={best['priority']}")
        
        # Warn if there are multiple high-priority matches
        high_priority = [m for m in matches if m["priority"] >= 80]
        if len(high_priority) > 1:
            pages = [m["page"]+1 for m in high_priority]
            debug_print(f"  Multiple high-priority matches on pages: {pages}")

    return index

def find_text_locations(page, full_match_text: str, image_name: str) -> list:
    """
    Robustly find the coordinates of the link text.
    Handles line breaks, different formatting, etc.
    """
    # Strategy 1: Exact search for the full match
    rects = page.search_for(full_match_text)
    if rects:
        debug_print(f"Found exact match for full text")
        return rects
    
    # Strategy 2: Search for normalized version
    normalized = normalize_whitespace(full_match_text)
    rects = page.search_for(normalized)
    if rects:
        debug_print(f"Found normalized full text")
        return rects
    
    # Strategy 3: Search for key parts and combine
    # Look for "See image" near the image name
    start_patterns = ["See image,", "See image.", "See image"]
    start_rects = []
    for pattern in start_patterns:
        start_rects.extend(page.search_for(pattern))
    
    # Search for the image name (try various forms)
    name_rects = []
    name_variants = [
        image_name,
        normalize_whitespace(image_name),
        image_name.replace("-", " "),
        image_name.replace("_", " "),
    ]
    for variant in name_variants:
        name_rects.extend(page.search_for(variant))
    
    # Also try searching for significant portions of long names
    if len(image_name) > 30:
        # Try first half and second half
        words = image_name.split()
        if len(words) > 2:
            first_part = " ".join(words[:len(words)//2 + 1])
            name_rects.extend(page.search_for(first_part))
    
    valid_rects = []
    if start_rects and name_rects:
        for s_rect in start_rects:
            for n_rect in name_rects:
                # Check if they're on the same or adjacent lines
                vertical_distance = abs(n_rect.y0 - s_rect.y0)
                if vertical_distance < 50:  # Within ~3-4 lines
                    # Combine the rectangles
                    combined = s_rect | n_rect
                    valid_rects.append(combined)
                    debug_print(f"Combined rects: start y={s_rect.y0:.0f}, name y={n_rect.y0:.0f}")
    
    if valid_rects:
        return valid_rects
    
    # Strategy 4: Just link the image name if found
    if name_rects:
        debug_print(f"Falling back to just the image name rect")
        return name_rects[:1]  # Return just the first match
    
    # Strategy 5: Search using text blocks for more flexibility
    blocks = page.get_text("blocks")
    for block in blocks:
        block_text = block[4] if len(block) > 4 else ""
        if "see image" in block_text.lower() and image_name.lower() in normalize_whitespace(block_text).lower():
            # Found the block containing our reference
            block_rect = fitz.Rect(block[:4])
            debug_print(f"Found in text block")
            return [block_rect]
    
    return []

def add_hyperlinks(doc: fitz.Document, image_index: dict) -> tuple:
    """
    Add forward links from 'See image' references to image pages.

    Returns:
        (links_added, reverse_links, source_rects)
        - links_added: count of links created
        - reverse_links: dict mapping target_page -> [(source_page, image_name), ...]
        - source_rects: dict mapping (source_page, image_name) -> rect of the source link
    """
    links_added = 0
    reverse_links = {}
    source_rects = {}  # Track source link rectangles for highlighting
    blue_color = (0, 0.4, 0.8)

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")

        for match in SEE_IMAGE_RE.finditer(text):
            full_text = match.group(0)
            image_name = match.group("name").strip()
            image_name_clean = normalize_whitespace(image_name)

            # Try to find target page
            target_page = None

            # Strategy 1: Direct match
            target_page = image_index.get(image_name_clean)

            # Strategy 2: Try original (with line breaks preserved)
            if target_page is None:
                target_page = image_index.get(image_name)

            # Strategy 3: Fuzzy match against all indexed names
            if target_page is None:
                matched_key = find_best_match(image_name_clean, image_index)
                if matched_key:
                    target_page = image_index[matched_key]

            # Strategy 4: Case-insensitive partial match
            if target_page is None:
                for key in image_index:
                    key_norm = normalize_for_comparison(key)
                    name_norm = normalize_for_comparison(image_name_clean)
                    if key_norm in name_norm or name_norm in key_norm:
                        target_page = image_index[key]
                        debug_print(f"Partial match: '{image_name_clean}' -> '{key}'")
                        break

            if target_page is None:
                print(f"   ⚠️  No target found for: '{image_name_clean}'")
                # Print suggestions if any similar names exist
                for key in image_index:
                    sim = similarity_ratio(
                        normalize_for_comparison(image_name_clean),
                        normalize_for_comparison(key)
                    )
                    if sim > 0.5:
                        print(f"       Did you mean: '{key}' (similarity: {sim:.0%})?")
                continue

            rects = find_text_locations(page, full_text, image_name_clean)

            if not rects:
                print(f"   ⚠️  Could not locate text '{image_name_clean}' on page {page_num+1}")
                continue

            for rect in rects:
                page.insert_link({
                    "kind": fitz.LINK_GOTO,
                    "from": rect,
                    "page": target_page,
                    "to": fitz.Point(0, 0),
                    "zoom": 0,
                })

                # Underline
                page.draw_line(
                    fitz.Point(rect.x0, rect.y1 - 1),
                    fitz.Point(rect.x1, rect.y1 - 1),
                    color=blue_color,
                    width=0.8
                )

                # Append target page number as permanent text next to the link
                page_num_text = f" (Pg {target_page + 1})"
                try:
                    page.insert_text(
                        fitz.Point(rect.x1 + 2, rect.y1 - 4),
                        page_num_text,
                        fontsize=8,
                        fontname="helv",
                        color=(0, 0, 0),
                    )
                except Exception:
                    pass  # Fallback: skip page-number text if font/space issues

                # Store the source rect for the first occurrence (for highlighting)
                source_key = (page_num, image_name_clean)
                if source_key not in source_rects:
                    source_rects[source_key] = rect

            if target_page not in reverse_links:
                reverse_links[target_page] = []
            reverse_links[target_page].append((page_num, image_name_clean))

            links_added += 1
            print(f"   ✓ Linked '{image_name_clean}' (Pg {page_num + 1}) → Pg {target_page + 1}")

    return links_added, reverse_links, source_rects

def get_page_images(page) -> list:
    """
    Get all images on a page with their bounding rectangles.
    Returns list of (rect, xref) tuples.
    """
    images = []

    # Method 1: Get images from page's image list
    image_list = page.get_images(full=True)

    for img_info in image_list:
        xref = img_info[0]
        try:
            # Get the image's bounding box on the page
            img_rects = page.get_image_rects(xref)
            for rect in img_rects:
                if rect.is_empty or rect.is_infinite:
                    continue
                # Only include reasonably sized images (not tiny icons)
                if rect.width > 50 and rect.height > 50:
                    images.append((rect, xref))
                    debug_print(f"Found image: xref={xref}, rect={rect}")
        except Exception as e:
            debug_print(f"Could not get rect for image xref={xref}: {e}")

    return images


def get_page_background_color(page) -> tuple:
    """
    Detect the background color of the page by sampling the 4 corners.
    Returns RGB tuple (0-1 scale).
    Default is white (1, 1, 1) if unable to determine.
    """
    try:
        # Get pixmap at full resolution for accurate color detection
        pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
        
        # Sample only the 4 corners (top-left, top-right, bottom-left, bottom-right)
        # Using offset of 10 pixels to avoid any page border artifacts
        offset = 10
        corner_positions = [
            (offset, offset),                           # Top-left
            (pix.width - offset - 1, offset),          # Top-right
            (offset, pix.height - offset - 1),         # Bottom-left
            (pix.width - offset - 1, pix.height - offset - 1),  # Bottom-right
        ]
        
        samples = []
        for x, y in corner_positions:
            try:
                color = pix.pixel(x, y)
                # Convert to RGB (0-1 scale)
                if len(color) >= 3:
                    rgb = (color[0]/255, color[1]/255, color[2]/255)
                    samples.append(rgb)
                    debug_print(f"Corner color at ({x}, {y}): RGB{rgb}")
            except Exception as e:
                debug_print(f"Could not sample corner ({x}, {y}): {e}")
        
        if samples:
            # Return average of corner samples
            avg_r = sum(s[0] for s in samples) / len(samples)
            avg_g = sum(s[1] for s in samples) / len(samples)
            avg_b = sum(s[2] for s in samples) / len(samples)
            debug_print(f"Detected background color: RGB({avg_r:.3f}, {avg_g:.3f}, {avg_b:.3f})")
            return (avg_r, avg_g, avg_b)
    except Exception as e:
        debug_print(f"Could not detect background color: {e}")
    
    # Default to white
    debug_print("Using default white background color")
    return (1, 1, 1)


def remove_taken_by_text(page) -> int:
    """
    Find and remove "Taken By: [name]" text by:
    1. Finding exact text location
    2. Applying PDF redaction (truly removes from content stream)
    3. Drawing background-colored rectangle (visual cover)
    
    Returns the count of text instances removed.
    """
    removed_count = 0
    
    # Get background color for the visual cover
    bg_color = get_page_background_color(page)
    
    # Search patterns for "Taken By" variations
    # Narrowed to only metadata patterns that appear on Xactimate photo pages;
    # removed overly broad patterns (credit, source, etc.) that false-positive
    # on estimate text.
    patterns = [
        r"taken\s+by[:\s]+[^\n]*",  # "Taken By: Name"
        r"photo\s+by[:\s]+[^\n]*",   # "Photo By: Name"
        r"image\s+by[:\s]+[^\n]*",   # "Image By: Name"
    ]
    
    text = page.get_text()
    
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            matched_text = match.group(0)
            
            # Find all rectangles for this text
            try:
                rects = page.search_for(matched_text)
                
                if rects:
                    for rect in rects:
                        # Use exact text bounding box with tuned padding
                        # Keep top padding very small to avoid clipping nearby photo content.
                        tight_rect = fitz.Rect(
                            rect.x0 - 1,   # Minimal left padding
                            rect.y0 - 0.15, # Reduced top padding (was 1)
                            rect.x1 + 1,   # Minimal right padding
                            rect.y1 + 1    # Keep bottom padding for full text coverage
                        )
                        
                        # METHOD 1: Apply PDF redaction (removes text from content stream)
                        # This actually removes the text, making it non-selectable
                        try:
                            page.add_redact_annot(tight_rect, fill=bg_color)
                            debug_print(f"Applied redaction to: '{matched_text}'")
                        except Exception as e:
                            debug_print(f"Redaction failed, using draw method: {e}")
                            # Fallback: just draw the rectangle
                            pass
                        
                        # METHOD 2: Draw background-colored rectangle on top (visual cover)
                        # This provides visual coverage as backup to redaction
                        page.draw_rect(
                            tight_rect,
                            color=None,           # No border
                            fill=bg_color,
                            overlay=True
                        )
                        
                        removed_count += 1
                        debug_print(f"Removed: '{matched_text}' at {rect} (redacted + covered)")
            except Exception as e:
                debug_print(f"Could not remove '{matched_text}': {e}")
    
    # Apply all redaction annotations to actually remove text from content stream
    if removed_count > 0:
        try:
            # Preserve image streams by only removing text/graphics from redaction areas.
            # Default image handling (images=2) can re-encode image xobjects and inflate size.
            page.apply_redactions(images=0, graphics=0, text=0)
            debug_print(f"Applied {removed_count} redaction(s) to page")
        except Exception as e:
            debug_print(f"Warning: Could not apply redactions: {e}")
    
    return removed_count


def add_reverse_links(doc: fitz.Document, reverse_links: dict, source_rects: dict) -> int:
    """
    Add 'back to line item' links on image pages.
    Also makes images clickable to return to the source.

    The links navigate to the source text location. PDF viewers (Chrome, Firefox, Edge)
    will scroll to the destination - no permanent highlighting is added.

    Args:
        doc: The PDF document
        reverse_links: Dict mapping target_page -> [(source_page, image_name), ...]
        source_rects: Dict mapping (source_page, image_name) -> rect of the source link
    """
    reverse_count = 0
    blue_color = (0, 0.4, 0.8)

    for target_page_num, sources in reverse_links.items():
        source_page_num = sources[0][0]
        image_name = sources[0][1]

        if target_page_num <= source_page_num:
            continue

        page = doc.load_page(target_page_num)
        page_rect = page.rect

        # Get the source rectangle for positioning
        source_key = (source_page_num, image_name)
        source_rect = source_rects.get(source_key)

        # Calculate the Y position for the destination (where to scroll to on source page)
        # Use the top of the source rect if available, otherwise use top of page
        dest_y = source_rect.y0 - 50 if source_rect else 0  # 50px above the link
        dest_y = max(0, dest_y)  # Don't go negative

        # --- Add "back to line item" text link ---
        text = "back to line item"
        font_size = 10
        x_center = (page_rect.x0 + page_rect.x1) / 2

        try:
            text_width = fitz.Font("tiro").text_length(text, fontsize=font_size)
        except:
            # Fallback if tiro font not available
            text_width = len(text) * font_size * 0.5

        x_start = x_center - (text_width / 2)
        y_position = page_rect.y1 - 30

        try:
            page.insert_text(
                fitz.Point(x_start, y_position),
                text,
                fontsize=font_size,
                fontname="tiro",
                color=blue_color
            )
        except:
            # Fallback to helv if tiro not available
            page.insert_text(
                fitz.Point(x_start, y_position),
                text,
                fontsize=font_size,
                fontname="helv",
                color=blue_color
            )

        link_rect = fitz.Rect(x_start, y_position - font_size, x_start + text_width, y_position + 2)

        # Insert link that goes to the source page at the correct Y position
        page.insert_link({
            "kind": fitz.LINK_GOTO,
            "from": link_rect,
            "page": source_page_num,
            "to": fitz.Point(0, dest_y),
            "zoom": 0,
        })

        reverse_count += 1

        # --- Make images on this page clickable ---
        images = get_page_images(page)

        for img_rect, xref in images:
            # Add a clickable link over each image
            page.insert_link({
                "kind": fitz.LINK_GOTO,
                "from": img_rect,
                "page": source_page_num,
                "to": fitz.Point(0, dest_y),
                "zoom": 0,
            })
            debug_print(f"Added clickable link on image (xref={xref}) -> page {source_page_num + 1}")

        if images:
            print(f"   ✓ Made {len(images)} image(s) clickable on page {target_page_num + 1}")

    return reverse_count

def main(input_path: pathlib.Path, output_path: pathlib.Path, add_highlights: bool = False, highlight_rules=None):
    if not input_path.is_file():
        sys.exit(f"❌ Input file not found: {input_path}")

    # -----------------------------------------------------------
    # STEP 0: Sanitize the PDF to fix XREF errors
    # -----------------------------------------------------------
    doc = None
    try:
        raw_doc = fitz.open(str(input_path))
        pdf_bytes = raw_doc.tobytes(garbage=4, deflate=True, clean=True)
        raw_doc.close()
        doc = fitz.open("pdf", pdf_bytes)
        print("🧹 PDF Sanitized (attempting XREF repair).")
    except Exception as e:
        print(f"⚠️ Could not sanitize PDF ({e}). Attempting to process original...")
        doc = fitz.open(str(input_path))
    
    if not doc:
        sys.exit("❌ Failed to open document.")

    # 1. Find all potential image names
    print("🔎 Scanning for references...")
    all_text = ""
    for p in doc:
        all_text += p.get_text()
    
    image_names = set()
    for match in SEE_IMAGE_RE.finditer(all_text):
        name = match.group("name").strip()
        name = normalize_whitespace(name)
        image_names.add(name)
        debug_print(f"Found reference: '{name}'")

    if not image_names:
        print("   ⚠️  No image references found (that's OK - highlights will still work).")
    else:
        print(f"   Found {len(image_names)} references: {', '.join(list(image_names)[:3])}...")

    # 2. Remove "Taken By:" metadata text (photo pages only)
    estimate_end_page = os.environ.get('ESTIMATE_END_PAGE')
    photo_start = int(estimate_end_page) if estimate_end_page else len(doc)
    print(f"\n🧹 Removing metadata text (photo pages index >= {photo_start})...")
    total_removed = 0
    for page_num in range(photo_start, len(doc)):
        page = doc.load_page(page_num)
        removed = remove_taken_by_text(page)
        if removed > 0:
            total_removed += removed
            print(f"   Removed {removed} metadata text instance(s) on page {page_num + 1}")
    if total_removed > 0:
        print(f"   Total: {total_removed} metadata text instance(s) removed")

    # 3. Build Index (only if we have image references)
    image_index = {}
    if image_names:
        print("\n🔎 Indexing target pages...")
        image_index = build_image_index(doc, image_names)
        
        # Report any missing targets
        missing = image_names - set(image_index.keys())
        if missing:
            print(f"\n⚠️  Could not find targets for {len(missing)} image(s):")
            for name in list(missing)[:10]:  # Show first 10
                print(f"      - '{name}'")
            if len(missing) > 10:
                print(f"      ... and {len(missing) - 10} more")

    # 4. ALWAYS add phrase highlights FIRST (before the linking step)
    total_highlights = 0
    normalized_rules = _normalize_highlight_rules(highlight_rules or [])
    if normalized_rules:
        print("\n🎨 Applying highlight annotations...")
        total_highlights = add_phrase_highlights(doc, normalized_rules)
        print(f"   Added {total_highlights} highlight annotation(s)")
    else:
        print("\n⏭️  No highlight terms provided (skipping annotations)")

    # 5. Add Hyperlinks (only if we have image references)
    count = 0
    rev_links = {}
    source_rects = {}
    if image_index:
        print("\n✏️  Linking...")
        count, rev_links, source_rects = add_hyperlinks(doc, image_index)
    else:
        print("\n⏭️  No image references to link (skipping hyperlink step)")

    # 6. Add Reverse Links (back to line item links)
    if rev_links:
        rev_count = add_reverse_links(doc, rev_links, source_rects)
        debug_print(f"Added {rev_count} reverse links")

    # 7. Save
    doc.save(str(output_path), garbage=4, deflate=True, clean=True)
    doc.close()
    print(f"\n✅ Saved: {output_path}")
    print(f"   Links created: {count}")

# ----------------------------------------------------------------------
# Execution Block
# ----------------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]
    
    # Check for debug flag
    if "--debug" in args:
        set_debug(True)
        args.remove("--debug")
        print("🔧 Debug mode enabled\n")

    # Load user-provided highlight rules from app.py/web interface
    fork_highlight_rules = _load_fork_highlight_rules()
    
    # Interactive highlighting prompts are disabled.
    # Highlights are applied only when terms are passed via env payload.
    add_highlights = bool(fork_highlight_rules)
    if add_highlights:
        print(f"📌 Using {len(fork_highlight_rules)} highlight rule(s) from user input")
    
    pdf_files_to_process = []
    
    if args:
        print(f"Found {len(args)} file(s) specified in arguments.")
        pdf_files_to_process = [pathlib.Path(f) for f in args]
    else:
        current_dir = pathlib.Path(".")
        pdf_files = list(current_dir.glob("*.pdf"))
        pdf_files_to_process = [f for f in pdf_files if "_linked" not in f.stem]
    
    if not pdf_files_to_process:
        sys.exit("❌ No PDF files found to process. Specify files as arguments or place non-'_linked' PDFs in the current directory.")

    for pdf_file_path in pdf_files_to_process:
        output_file = pdf_file_path.with_stem(f"{pdf_file_path.stem}_linked")
        print("=" * 60)
        print(f"Processing: {pdf_file_path.name}")
        main(
            pdf_file_path,
            output_file,
            add_highlights=add_highlights,
            highlight_rules=fork_highlight_rules,
        )
        print("-" * 60)
